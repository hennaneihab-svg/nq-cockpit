"""Client d'intégration MetaTrader 5 (MT5) en LECTURE SEULE.

Règles impératives :
- STRICTEMENT AUCUNE fonction d'exécution ou d'envoi d'ordres (conformité avec
  la règle fondatrice R9 : "l'outil prépare, discipline et mesure, il n'exécute pas d'ordres").
- Statut honnête : OK ou DÉGRADÉ avec motif explicite (terminal non installé, non lancéé,
  authentification échouée). Jamais de solde ni de trades fictifs inventés.
- Identifiants : lus depuis .env ou passés explicitement. Mot de passe masqué,
  jamais journalisé en clair dans les logs structurés.
- Fuseaux horaires : conversion stricte depuis l'horodatage serveur broker vers
  America/New_York (logique marché) et Africa/Algiers (affichage/fenêtres) via zoneinfo.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo

from nqcockpit.env import get_mt5_raw_credentials
from nqcockpit.journal.models import TradeDirection, TradeEntry, TradeOutcome
from nqcockpit.journal.store import load_trades, save_trade
from nqcockpit.time import TZ_ALGIERS, TZ_NEW_YORK, TZ_UTC, is_in_trading_window

if TYPE_CHECKING:
    from nqcockpit.config import AppConfig

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5

    HAS_MT5_PACKAGE = True
except ImportError:
    mt5 = None
    HAS_MT5_PACKAGE = False

@dataclass
class MT5Status:
    """État de santé et de connexion de la liaison MT5."""

    status: str  # "OK" | "DÉGRADÉ"
    reason: str
    error_code: Optional[int] = None
    terminal_detected: bool = False
    connected: bool = False
    account_login: Optional[int] = None
    server: Optional[str] = None
    currency: Optional[str] = None
    balance: Optional[float] = None
    equity: Optional[float] = None
    Échecked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_ok(self) -> bool:
        return self.status == "OK" and self.connected


@dataclass
class MT5AccountInfo:
    """Informations de compte MT5 en lecture seule."""

    login: int
    trade_mode: str  # "DEMO" | "REAL" | "CONTEST"
    server: str
    currency: str
    balance: float
    equity: float
    profit: float
    margin: float
    margin_free: float
    margin_level: float
    leverage: int
    company: str
    name: str


@dataclass
class MT5PositionRecord:
    """Position ouverte en lecture seule."""

    ticket: int
    symbol: str
    direction: TradeDirection
    volume: float
    price_open: float
    sl: Optional[float]
    tp: Optional[float]
    price_current: float
    profit: float
    swap: float
    time_open_utc: datetime
    time_open_ny: datetime
    time_open_algiers: datetime
    comment: str = ""


@dataclass
class MT5TradeRecord:
    """Trade fermé (round-trip) consolidé depuis l'historique des deals."""

    position_id: int
    symbol: str
    direction: TradeDirection
    volume: float
    entry_price: float
    exit_price: float
    stop_price: Optional[float] = None
    take_profit: Optional[float] = None
    pnl: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    entry_time_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exit_time_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    entry_time_ny: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exit_time_ny: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    entry_time_algiers: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exit_time_algiers: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exit_reason: str = ""
    entry_deal_id: Optional[int] = None
    exit_deal_id: Optional[int] = None
    comment: str = ""

    @property
    def net_profit(self) -> float:
        """Profit net consolidé (profit + commission + swap + fee)."""
        return round(self.pnl + self.commission + self.swap + self.fee, 2)


@dataclass
class MT5ImportSummary:
    """Résumé de l'import des deals MT5 vers le Journal de bord."""

    total_deals: int = 0
    total_positions: int = 0
    imported: int = 0
    duplicates: int = 0
    rejected: int = 0
    ignored_out_of_scope: int = 0
    status: str = "OK"  # "OK" | "DÉGRADÉ"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return len(self.errors) == 0 or self.imported > 0


# ---------------------------------------------------------------------------
# Client MT5 en lecture seule
# ---------------------------------------------------------------------------


class MT5Client:
    """Client de communication locale IPC avec MetaTrader 5 en LECTURE SEULE.

    Garantit l'absence totale de méthode d'envoi d'ordres (Rule R9).
    """

    READ_ONLY: bool = True

    def __init__(
        self,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None,
        broker_tz: str = "UTC",
    ) -> None:
        raw_env = get_mt5_raw_credentials()
        self.login: Optional[int] = login if login is not None else raw_env.get("login")
        self._password: str = password if password is not None else (raw_env.get("password") or "")
        self.server: str = server if server is not None else (raw_env.get("server") or "")
        self.path: str = path if path is not None else (raw_env.get("path") or "")
        self.broker_tz_name: str = broker_tz or raw_env.get("broker_tz") or "UTC"
        self._is_connected: bool = False

    def __enter__(self) -> MT5Client:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.disconnect()

    def __repr__(self) -> str:
        login_display = str(self.login) if self.login else "None"
        server_display = self.server or "None"
        return (
            f"MT5Client(login={login_display}, server={server_display}, "
            f"connected={self._is_connected}, read_only=True)"
        )

    # -----------------------------------------------------------------------
    # Sécurité R9 : interdiction absolue d'exécuter des ordres
    # -----------------------------------------------------------------------

    def order_send(self, *args: Any, **kwargs: Any) -> None:
        """Méthode interdite par le principe fondateur R9."""
        raise NotImplementedError(
            "Le client MT5 est STRICTEMENT en lecture seule conformément à la règle R9 "
            "('l'outil prépare, discipline et mesure, il n'exécute pas d'ordres')."
        )

    # -----------------------------------------------------------------------
    # Connexion et Déconnexion
    # -----------------------------------------------------------------------

    def connect(self) -> MT5Status:
        """Initialise la communication IPC et authentifie la session si identifiants configurés.

        Retourne un objet MT5Status avec diagnostic explicite OK ou DÉGRADÉ.
        """
        if not HAS_MT5_PACKAGE or mt5 is None:
            self._is_connected = False
            return MT5Status(
                status="DÉGRADÉ",
                reason="Package Python MetaTrader5 non disponible dans l'environnement.",
                terminal_detected=False,
                connected=False,
            )

        init_kwargs: dict[str, Any] = {}
        if self.path and self.path.strip():
            init_kwargs["path"] = self.path.strip()
        if self.server and self.server.strip():
            init_kwargs["server"] = self.server.strip()
        if self.login is not None:
            init_kwargs["login"] = int(self.login)
        if self._password and self._password.strip():
            init_kwargs["password"] = self._password.strip()

        try:
            init_ok = mt5.initialize(**init_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Exception lors de mt5.initialize : %s", exc)
            self._is_connected = False
            return MT5Status(
                status="DÉGRADÉ",
                reason=f"Erreur d'initialisation MT5 : {exc}",
                terminal_detected=False,
                connected=False,
            )

        if not init_ok:
            code, msg = self._get_last_error()
            self._is_connected = False
            return MT5Status(
                status="DÉGRADÉ",
                reason=f"Terminal MT5 non détecté ou non lancéé ({code}: {msg})",
                error_code=code,
                terminal_detected=False,
                connected=False,
            )

        # Si un login spécifique était demandé mais pas déjà authentifié par initialize
        if self.login is not None and self._password:
            acc = mt5.account_info()
            if acc is None or getattr(acc, "login", None) != self.login:
                login_ok = mt5.login(
                    login=self.login,
                    password=self._password,
                    server=self.server or "",
                )
                if not login_ok:
                    code, msg = self._get_last_error()
                    mt5.shutdown()
                    self._is_connected = False
                    login_err = (
                        f"ÉÉchec d'authentification MT5 pour le compte {self.login} ({code}: {msg})"
                    )
                    return MT5Status(
                        status="DÉGRADÉ",
                        reason=login_err,
                        error_code=code,
                        terminal_detected=True,
                        connected=False,
                    )

        acc = mt5.account_info()
        self._is_connected = True

        acc_dict: dict[str, Any] = (
            acc._asdict() if acc is not None and hasattr(acc, "_asdict") else {}
        )
        return MT5Status(
            status="OK",
            reason="Connecté au terminal MT5",
            terminal_detected=True,
            connected=True,
            account_login=acc_dict.get("login") or self.login,
            server=acc_dict.get("server") or self.server,
            currency=acc_dict.get("currency"),
            balance=acc_dict.get("balance"),
            equity=acc_dict.get("equity"),
        )

    def disconnect(self) -> None:
        """Ferme la session IPC MT5 en toute sécurité."""
        if HAS_MT5_PACKAGE and mt5 is not None and self._is_connected:
            try:
                mt5.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self._is_connected = False

    def is_connected(self) -> bool:
        """Vérifie si la connexion IPC est active."""
        return self._is_connected

    def get_status(self) -> MT5Status:
        """Retourne le statut courant honnête (sans inventer)."""
        if not self._is_connected:
            return self.connect()

        if not HAS_MT5_PACKAGE or mt5 is None:
            return MT5Status(
                status="DÉGRADÉ",
                reason="Package Python MetaTrader5 non disponible.",
                connected=False,
            )

        acc = mt5.account_info()
        if acc is None:
            code, msg = self._get_last_error()
            self._is_connected = False
            return MT5Status(
                status="DÉGRADÉ",
                reason=f"Connexion au terminal perdue ({code}: {msg})",
                error_code=code,
                terminal_detected=True,
                connected=False,
            )

        acc_dict = acc._asdict() if hasattr(acc, "_asdict") else {}
        return MT5Status(
            status="OK",
            reason="Connecté au terminal MT5",
            terminal_detected=True,
            connected=True,
            account_login=acc_dict.get("login"),
            server=acc_dict.get("server"),
            currency=acc_dict.get("currency"),
            balance=acc_dict.get("balance"),
            equity=acc_dict.get("equity"),
        )

    # -----------------------------------------------------------------------
    # Récupération en LECTURE SEULE
    # -----------------------------------------------------------------------

    def get_account_info(self) -> Optional[MT5AccountInfo]:
        """Retourne les informations du compte ou None si non disponible."""
        if not self._is_connected:
            status = self.connect()
            if not status.is_ok:
                return None

        if not HAS_MT5_PACKAGE or mt5 is None:
            return None

        acc = mt5.account_info()
        if acc is None:
            return None

        d = acc._asdict() if hasattr(acc, "_asdict") else {}
        mode_val = d.get("trade_mode", 0)
        mode_str = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(mode_val, "DEMO")

        return MT5AccountInfo(
            login=int(d.get("login", 0)),
            trade_mode=mode_str,
            server=str(d.get("server", "")),
            currency=str(d.get("currency", "USD")),
            balance=float(d.get("balance", 0.0)),
            equity=float(d.get("equity", 0.0)),
            profit=float(d.get("profit", 0.0)),
            margin=float(d.get("margin", 0.0)),
            margin_free=float(d.get("margin_free", 0.0)),
            margin_level=float(d.get("margin_level", 0.0)),
            leverage=int(d.get("leverage", 100)),
            company=str(d.get("company", "")),
            name=str(d.get("name", "")),
        )

    def get_open_positions(self, symbol: Optional[str] = None) -> list[MT5PositionRecord]:
        """Retourne la liste des positions ouvertes en cours."""
        if not self._is_connected:
            status = self.connect()
            if not status.is_ok:
                return []

        if not HAS_MT5_PACKAGE or mt5 is None:
            return []

        kwargs: dict[str, Any] = {}
        if symbol:
            kwargs["symbol"] = symbol

        raw_positions = mt5.positions_get(**kwargs)
        if raw_positions is None:
            return []

        results: list[MT5PositionRecord] = []
        for p in raw_positions:
            d = p._asdict() if hasattr(p, "_asdict") else {}
            pos_type = d.get("type", 0)
            direction = TradeDirection.LONG if pos_type == 0 else TradeDirection.SHORT

            t_epoch = d.get("time", 0)
            t_utc, t_ny, t_algiers = self._convert_broker_time(t_epoch)

            sl_val = float(d["sl"]) if d.get("sl") and float(d["sl"]) > 0 else None
            tp_val = float(d["tp"]) if d.get("tp") and float(d["tp"]) > 0 else None

            results.append(
                MT5PositionRecord(
                    ticket=int(d.get("ticket", 0)),
                    symbol=str(d.get("symbol", "")),
                    direction=direction,
                    volume=float(d.get("volume", 0.0)),
                    price_open=float(d.get("price_open", 0.0)),
                    sl=sl_val,
                    tp=tp_val,
                    price_current=float(d.get("price_current", 0.0)),
                    profit=float(d.get("profit", 0.0)),
                    swap=float(d.get("swap", 0.0)),
                    time_open_utc=t_utc,
                    time_open_ny=t_ny,
                    time_open_algiers=t_algiers,
                    comment=str(d.get("comment", "")),
                )
            )

        return results

    def get_closed_trades(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        symbol: Optional[str] = None,
    ) -> list[MT5TradeRecord]:
        """Récupère l'historique des deals et les consolide en round-trips de trades fermés.

        Gère l'association entrée/sortie via position_id et récupère le stop initial.
        """
        if not self._is_connected:
            status = self.connect()
            if not status.is_ok:
                return []

        if not HAS_MT5_PACKAGE or mt5 is None:
            return []

        # Construction des arguments d'historique
        _from = date_from if date_from is not None else datetime(2000, 1, 1, tzinfo=timezone.utc)
        _to = date_to if date_to is not None else datetime.now(timezone.utc)
        raw_deals = mt5.history_deals_get(_from, _to)
        if raw_deals is None or len(raw_deals) == 0:
            return []

        # Grouper les deals par position_id
        deals_by_pos: dict[int, list[dict[str, Any]]] = {}
        for d in raw_deals:
            deal_dict = d._asdict() if hasattr(d, "_asdict") else {}
            sym = deal_dict.get("symbol", "")
            # Filtrer les opérations d'ééquilibrage / compte sans symbole
            if not sym or deal_dict.get("type", 0) not in (0, 1):
                continue
            if symbol and sym.upper() != symbol.upper():
                continue

            pos_id = int(deal_dict.get("position_id", 0))
            if pos_id <= 0:
                continue

            deals_by_pos.setdefault(pos_id, []).append(deal_dict)

        results: list[MT5TradeRecord] = []

        for pos_id, deals in deals_by_pos.items():
            # Trier les deals chronologiquement
            deals.sort(key=lambda x: (x.get("time_msc", 0), x.get("time", 0)))

            entry_deals = [d for d in deals if d.get("entry", 0) == 0]
            exit_deals = [d for d in deals if d.get("entry", 0) in (1, 2, 3)]

            # Si le deal de sortie existe mais pas le deal d'entrée dans la plage date_from/date_to,
            # interroger spécifiquement l'historique de cette position complète
            if exit_deals and not entry_deals:
                pos_deals = mt5.history_deals_get(position=pos_id)
                if pos_deals:
                    full_deals = [
                        pd._asdict() if hasattr(pd, "_asdict") else {} for pd in pos_deals
                    ]
                    full_deals.sort(
                        key=lambda x: (x.get("time_msc", 0), x.get("time", 0))
                    )
                    entry_deals = [d for d in full_deals if d.get("entry", 0) == 0]
                    # Conserver l'ensemble pour le calcul des frais complets
                    deals = full_deals

            # Si pas de deal de sortie, la position est encore ouverte
            if not exit_deals:
                continue

            # Si toujours pas de deal d'entrée trouvé, ignorer (donnée incomplète)
            if not entry_deals:
                continue

            first_entry = entry_deals[0]
            last_exit = exit_deals[-1]

            direction = (
                TradeDirection.LONG
                if first_entry.get("type", 0) == 0
                else TradeDirection.SHORT
            )
            sym = first_entry.get("symbol", "")
            entry_price = float(first_entry.get("price", 0.0))
            exit_price = float(last_exit.get("price", 0.0))

            vol_exit = sum(float(d.get("volume", 0.0)) for d in exit_deals)
            volume = vol_exit if vol_exit > 0 else float(first_entry.get("volume", 0.0))

            total_pnl = sum(float(d.get("profit", 0.0)) for d in deals)
            total_comm = sum(float(d.get("commission", 0.0)) for d in deals)
            total_swap = sum(float(d.get("swap", 0.0)) for d in deals)
            total_fee = sum(float(d.get("fee", 0.0)) for d in deals)

            # Recherche des SL / TP initiaux depuis les ordres de la position
            stop_price: Optional[float] = None
            take_profit: Optional[float] = None
            try:
                orders = mt5.history_orders_get(position=pos_id)
                if orders:
                    for o in orders:
                        o_dict = o._asdict() if hasattr(o, "_asdict") else {}
                        o_sl = float(o_dict.get("sl", 0.0))
                        o_tp = float(o_dict.get("tp", 0.0))
                        if o_sl > 0 and stop_price is None:
                            stop_price = round(o_sl, 2)
                        if o_tp > 0 and take_profit is None:
                            take_profit = round(o_tp, 2)
            except Exception:  # noqa: BLE001
                pass

            # Si non trouvé dans les ordres, vérifier également les deals
            if stop_price is None or take_profit is None:
                for d_chk in deals:
                    d_sl = float(d_chk.get("sl", 0.0)) if "sl" in d_chk else 0.0
                    d_tp = float(d_chk.get("tp", 0.0)) if "tp" in d_chk else 0.0
                    if d_sl > 0 and stop_price is None:
                        stop_price = round(d_sl, 2)
                    if d_tp > 0 and take_profit is None:
                        take_profit = round(d_tp, 2)

            # Détermination de la raison de sortie
            deal_reason = last_exit.get("reason", 0)
            comment_str = str(last_exit.get("comment", "")).lower()
            sl_code = getattr(mt5, "DEAL_REASON_SL", 3)
            tp_code = getattr(mt5, "DEAL_REASON_TP", 4)

            if deal_reason == sl_code or "[sl" in comment_str or "sl]" in comment_str:
                exit_reason = "SL"
            elif deal_reason == tp_code or "[tp" in comment_str or "tp]" in comment_str:
                exit_reason = "TP1"
            elif "time" in comment_str or "close" in comment_str:
                exit_reason = "Temps"
            else:
                exit_reason = "Manuel"

            t_entry_utc, t_entry_ny, t_entry_algiers = self._convert_broker_time(
                first_entry.get("time", 0)
            )
            t_exit_utc, t_exit_ny, t_exit_algiers = self._convert_broker_time(
                last_exit.get("time", 0)
            )

            results.append(
                MT5TradeRecord(
                    position_id=pos_id,
                    symbol=sym,
                    direction=direction,
                    volume=volume,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    stop_price=stop_price,
                    take_profit=take_profit,
                    pnl=total_pnl,
                    commission=total_comm,
                    swap=total_swap,
                    fee=total_fee,
                    entry_time_utc=t_entry_utc,
                    exit_time_utc=t_exit_utc,
                    entry_time_ny=t_entry_ny,
                    exit_time_ny=t_exit_ny,
                    entry_time_algiers=t_entry_algiers,
                    exit_time_algiers=t_exit_algiers,
                    exit_reason=exit_reason,
                    entry_deal_id=first_entry.get("ticket"),
                    exit_deal_id=last_exit.get("ticket"),
                    comment=str(last_exit.get("comment", "")),
                )
            )

        # Trier du plus ancien au plus récent
        results.sort(key=lambda x: x.exit_time_utc)
        return results

    # -----------------------------------------------------------------------
    # Importation vers SQLite (Journal de bord P09/P10)
    # -----------------------------------------------------------------------

    def import_trades_to_journal(
        self,
        conn: sqlite3.Connection,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        symbol: Optional[str] = None,
        config: Optional[AppConfig] = None,
    ) -> MT5ImportSummary:
        """Importe automatiquement les trades MT5 fermés dans le Journal SQLite.

        Déduplique contre les trades existants, calcule le R et persiste.
        """
        summary = MT5ImportSummary()

        status = self.get_status()
        if not status.is_ok:
            summary.status = "DÉGRADÉ"
            summary.errors.append(f"Connexion MT5 inactive : {status.reason}")
            return summary

        closed_trades = self.get_closed_trades(
            date_from=date_from, date_to=date_to, symbol=symbol
        )
        summary.total_positions = len(closed_trades)

        if not closed_trades:
            return summary

        existing_trades = load_trades(conn)
        existing_ids = {t.trade_id for t in existing_trades}
        existing_timed_keys: set[tuple[str, str, float, float, str, str]] = {
            (
                t.session_date,
                t.instrument.upper(),
                round(t.entry_price, 2),
                round(t.exit_price, 2),
                t.direction.value,
                t.entry_time_ny.isoformat(),
            )
            for t in existing_trades
            if t.entry_time_ny is not None
        }
        existing_5_keys: set[tuple[str, str, float, float, str]] = {
            (
                t.session_date,
                t.instrument.upper(),
                round(t.entry_price, 2),
                round(t.exit_price, 2),
                t.direction.value,
            )
            for t in existing_trades
        }

        windows_cfg = getattr(config, "trading_windows_algiers", None) if config else None

        for tr in closed_trades:
            if not tr.symbol.upper().startswith(("NQ", "MNQ")):
                summary.ignored_out_of_scope += 1
                summary.warnings.append(
                    f"Position #{tr.position_id} ({tr.symbol}) ignorée (hors NQ)"
                )
                continue
            trade_id = f"mt5_{tr.position_id}"
            norm_symbol = self._normalize_symbol(tr.symbol)
            session_date = tr.entry_time_ny.strftime("%Y-%m-%d")

            # Détection des doublons
            is_dup = False
            if trade_id in existing_ids:
                is_dup = True
            else:
                timed_key = (
                    session_date,
                    norm_symbol.upper(),
                    round(tr.entry_price, 2),
                    round(tr.exit_price, 2),
                    tr.direction.value,
                    tr.entry_time_ny.isoformat(),
                )
                if timed_key in existing_timed_keys:
                    is_dup = True
                else:
                    five_key = (
                        session_date,
                        norm_symbol.upper(),
                        round(tr.entry_price, 2),
                        round(tr.exit_price, 2),
                        tr.direction.value,
                    )
                    if five_key in existing_5_keys:
                        is_dup = True

            if is_dup:
                summary.duplicates += 1
                continue

            # Détection de la fenêtre de trading
            in_window, win_name = is_in_trading_window(
                tr.entry_time_algiers, windows=windows_cfg
            )
            window_label = win_name or ""

            # Frais cumulés
            total_fees = abs(tr.commission) + abs(tr.swap) + abs(tr.fee)

            # Nombre de contrats
            contracts_count: Optional[int] = (
                int(tr.volume)
                if tr.volume >= 1 and tr.volume.is_integer()
                else int(max(1, round(tr.volume)))
            )

            # Détermination directe du résultat Gain / Perte / Breakeven depuis le profit net MT5
            net_pnl = tr.net_profit
            if net_pnl > 0.001:
                outcome = TradeOutcome.WIN
            elif net_pnl < -0.001:
                outcome = TradeOutcome.LOSS
            else:
                outcome = TradeOutcome.BREAKEVEN

            # Gestion honnête de SL et TP (jamais de chiffre inventé)
            has_sl = tr.stop_price is not None and tr.stop_price > 0
            has_tp = tr.take_profit is not None and tr.take_profit > 0

            stop_price_val = round(tr.stop_price, 2) if has_sl else 0.0
            tp_price_val = round(tr.take_profit, 2) if has_tp else None

            sl_desc = f"{stop_price_val:.2f}" if has_sl else "non défini"
            tp_desc = f"{tp_price_val:.2f}" if has_tp else "non défini"

            pnl_label = (
                "GAIN"
                if outcome == TradeOutcome.WIN
                else ("PERTE" if outcome == TradeOutcome.LOSS else "BREAKEVEN")
            )
            notes_str = (
                f"Auto-import MT5 (#{tr.position_id}) {chr(183)} {pnl_label} "
                f'PnL net: {"-" if net_pnl < 0 else "+"}${abs(net_pnl):.2f} '
                f'| SL: {sl_desc} | TP: {tp_desc}'
            )

            # Calcul du R si SL défini, sinon 0.0 (non calculable sans risque initial)
            if has_sl:
                initial_risk = abs(tr.entry_price - stop_price_val)
                if initial_risk > 0:
                    raw_r = (tr.exit_price - tr.entry_price) / initial_risk
                    if tr.direction == TradeDirection.SHORT:
                        raw_r = -raw_r
                    r_calc = round(raw_r - (total_fees / max(initial_risk, 1e-9)), 4)
                else:
                    r_calc = 0.0
            else:
                r_calc = 0.0

            entry = TradeEntry(
                trade_id=trade_id,
                recorded_at=tr.exit_time_algiers,
                session_date=session_date,
                instrument=norm_symbol,
                direction=tr.direction,
                entry_price=round(tr.entry_price, 2),
                stop_price=stop_price_val,
                tp1_price=tp_price_val,
                exit_price=round(tr.exit_price, 2),
                exit_reason=tr.exit_reason,
                fees_points=round(total_fees, 2),
                r_realized=r_calc,
                outcome=outcome,
                window_name=window_label,
                entry_time_ny=tr.entry_time_ny,
                exit_time_ny=tr.exit_time_ny,
                day_of_week=tr.entry_time_ny.weekday(),
                notes=notes_str,
                contracts=contracts_count,
            )

            save_trade(conn, entry)

            # Mise àƒÂ  jour des index de dàƒÂ©duplication en màƒÂ©moire
            existing_ids.add(trade_id)
            existing_timed_keys.add(
                (
                    session_date,
                    norm_symbol.upper(),
                    round(tr.entry_price, 2),
                    round(tr.exit_price, 2),
                    tr.direction.value,
                    tr.entry_time_ny.isoformat(),
                )
            )
            existing_5_keys.add(
                (
                    session_date,
                    norm_symbol.upper(),
                    round(tr.entry_price, 2),
                    round(tr.exit_price, 2),
                    tr.direction.value,
                )
            )

            summary.imported += 1

        return summary

    # -----------------------------------------------------------------------
    # Helpers internes
    # -----------------------------------------------------------------------

    def _convert_broker_time(self, timestamp_epoch: int) -> tuple[datetime, datetime, datetime]:
        """Convertit l'horodatage serveur broker vers UTC, NY et Alger via zoneinfo.

        Ne code JAMAIS de dàƒÂ©calage horaire en dur.
        """
        if not timestamp_epoch or timestamp_epoch <= 0:
            dt_utc = datetime.now(timezone.utc)
        elif self.broker_tz_name.upper() == "UTC":
            dt_utc = datetime.fromtimestamp(timestamp_epoch, tz=timezone.utc)
        else:
            try:
                tz_broker = ZoneInfo(self.broker_tz_name)
                # InterpràƒÂ©tation de l'horodatage dans le fuseau du broker
                dt_broker = datetime.fromtimestamp(timestamp_epoch, tz=tz_broker)
                dt_utc = dt_broker.astimezone(TZ_UTC)
            except Exception:  # noqa: BLE001
                dt_utc = datetime.fromtimestamp(timestamp_epoch, tz=timezone.utc)

        dt_ny = dt_utc.astimezone(TZ_NEW_YORK)
        dt_algiers = dt_utc.astimezone(TZ_ALGIERS)
        return dt_utc, dt_ny, dt_algiers

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalise le nom du symbole pour l'instrument du journal."""
        s = symbol.strip().upper()
        if "MNQ" in s:
            return "MNQ"
        if "NQ" in s or "NAS100" in s or "US100" in s or "USTEC" in s:
            return "NQ"
        return s

    @staticmethod
    def _get_last_error() -> tuple[int, str]:
        """RàƒÂ©cupàƒÂ¨re l'erreur systàƒÂ¨me MT5."""
        if HAS_MT5_PACKAGE and mt5 is not None and hasattr(mt5, "last_error"):
            try:
                err = mt5.last_error()
                if isinstance(err, tuple) and len(err) == 2:
                    return int(err[0]), str(err[1])
                return -1, str(err)
            except Exception:  # noqa: BLE001
                return -1, "Erreur MT5 indàƒÂ©terminàƒÂ©e"
        return -1, "Package MT5 indisponible"



