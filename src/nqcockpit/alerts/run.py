"""Alerteur Telegram autonome (hors Streamlit).

Usage :
    python -m nqcockpit.alerts.run           # évalue les règles une fois et quitte
    python -m nqcockpit.alerts.run --test    # envoie un message de test unique

Une exécution = une évaluation des règles + envoi + sortie (le Planificateur de
tâches Windows l'appelle toutes les 3 minutes). L'état de déduplication est
conservé dans un JSON à côté de la base (chemin NQ_DATA_DB_PATH).

Règles (chacune est ignorée avec un log d'une ligne si sa source est absente) :
  1. événement programmé dans les N prochaines minutes (défaut 15)
  2. source dégradée / rétablie (changement d'état uniquement)
  3. MT5 déconnecté / reconnecté (changement d'état uniquement)
  4. verrou discipline réel (perte journalière, tilt/premier trade perdant,
     nombre max de trades) ; hors fenêtre horaire n'alerte jamais
  5. toucher d'un niveau gamma (Call Wall / Gamma Flip / Put Support)

Langue : variable d'environnement ALERT_LANG (EN par défaut, FR supporté).
Tout le texte est construit ici à partir des CODES de statut ; les textes
français des moteurs ne sont jamais réutilisés.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from nqcockpit.briefing.telegram_client import send_telegram_message
from nqcockpit.config import load_config
from nqcockpit.events.radar import fetch_event_radar

log = logging.getLogger("nqcockpit.alerts")

UTC = timezone.utc
try:
    TZ_ALGIERS = ZoneInfo("Africa/Algiers")
except Exception:  # noqa: BLE001 - tzdata absente sous Windows : Algérie = UTC+1 fixe
    TZ_ALGIERS = timezone(timedelta(hours=1), "Africa/Algiers")

# --- Table de libellés EN/FR (aucune chaîne issue des moteurs) ---------------

_LABELS: dict[str, dict[str, str]] = {
    "EN": {
        "status.OK": "OK",
        "status.DEGRADED": "DEGRADED",
        "status.BLOCKED": "DOWN",
        "source": "Source {source}: {prev} → {cur}",
        "event": "Scheduled event: {name} at {when}{tier}",
        "mt5.connected": "MT5 connected",
        "mt5.disconnected": "MT5 disconnected",
        "discipline.lock": "Discipline lock active: {reasons}.",
        "discipline.clear": "Discipline lock cleared",
        "discipline.reason.LOCKED_DAILY_LOSS": "daily loss limit reached",
        "discipline.reason.LOCKED_TRADE1_LOSS": "first-trade loss / tilt lock",
        "discipline.reason.LOCKED_MAX_TRADES": "max trades reached",
        "level": "Price {dist:.0f} pts from {name} {level:,.0f}",
    },
    "FR": {
        "status.OK": "OK",
        "status.DEGRADED": "DÉGRADÉ",
        "status.BLOCKED": "HORS LIGNE",
        "source": "Source {source} : {prev} → {cur}",
        "event": "Événement programmé : {name} à {when}{tier}",
        "mt5.connected": "MT5 connecté",
        "mt5.disconnected": "MT5 déconnecté",
        "discipline.lock": "Verrou discipline actif : {reasons}.",
        "discipline.clear": "Verrou discipline levé",
        "discipline.reason.LOCKED_DAILY_LOSS": "limite de perte journalière atteinte",
        "discipline.reason.LOCKED_TRADE1_LOSS": "tilt / premier trade perdant",
        "discipline.reason.LOCKED_MAX_TRADES": "nombre maximal de trades atteint",
        "level": "Prix à {dist:.0f} pts de {name} {level:,.0f}",
    },
}

# Seuls ces codes sont de vrais verrous (OUT_OF_WINDOW et COOLDOWN n'alertent pas).
_LOCK_CODES = {"LOCKED_DAILY_LOSS", "LOCKED_TRADE1_LOSS", "LOCKED_MAX_TRADES"}
_STATUS_CODE_ALIASES = {
    "DÉGRADÉ": "DEGRADED",
    "DEGRADE": "DEGRADED",
    "BLOQUÉ": "BLOCKED",
    "HORS LIGNE": "BLOCKED",
}


def _t(lang: str, key: str, **kwargs) -> str:
    table = _LABELS[lang]
    return table[key].format(**kwargs)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


def _cfg() -> dict:
    return {
        "event_window_min": _env_int("ALERT_EVENT_WINDOW_MIN", 15),
        "level_touch_pts": _env_int("ALERT_LEVEL_TOUCH_PTS", 10),
        "cooldown_min": _env_int("ALERT_COOLDOWN_MIN", 30),
        "max_per_hour": _env_int("ALERT_MAX_PER_HOUR", 20),
        "quiet_start": os.getenv("ALERT_QUIET_START", "00:30"),
        "quiet_end": os.getenv("ALERT_QUIET_END", "08:00"),
        "enabled": {
            s.strip()
            for s in os.getenv(
                "ALERT_ENABLED_RULES", "event,source,mt5,discipline,level"
            ).split(",")
            if s.strip()
        },
    }


def _state_path() -> Path:
    db = os.getenv("NQ_DATA_DB_PATH", "data/nqcockpit.db")
    return Path(db).with_name("alerts_state.json")


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("État alerteur non sauvegardé: %s", exc)


def _in_quiet_hours(cfg: dict, now_utc: datetime) -> bool:
    now = now_utc.astimezone(TZ_ALGIERS).time()
    start = time.fromisoformat(cfg["quiet_start"])
    end = time.fromisoformat(cfg["quiet_end"])
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def _lang() -> str:
    """Langue de l'alerteur : ALERT_LANG (EN par défaut, FR supporté)."""
    lang = os.getenv("ALERT_LANG", "EN").strip().upper()
    return lang if lang in _LABELS else "EN"


def _status_code(status) -> str:
    code = getattr(status, "name", None) or str(status)
    code = str(code).strip().upper()
    return _STATUS_CODE_ALIASES.get(code, code)


def _rule_event(cfg: dict, report, now_utc: datetime, fr: bool) -> list[str]:
    lang = "FR" if fr else "EN"
    horizon = now_utc + timedelta(minutes=cfg["event_window_min"])
    msgs: list[str] = []
    for ev in getattr(report, "events", []) or []:
        sched = getattr(ev, "scheduled_utc", None)
        if not sched or not (now_utc <= sched <= horizon):
            continue
        when = sched.astimezone(TZ_ALGIERS).strftime("%H:%M")
        tier = f" T{getattr(ev, 'tier', '')}" if getattr(ev, "tier", None) else ""
        msgs.append(_t(lang, "event", name=ev.name, when=when, tier=tier))
    return msgs


def _status_label(lang: str, code: str) -> str:
    return _LABELS[lang].get(f"status.{code}", str(code))


def _rule_source(state: dict, report, now_utc: datetime, fr: bool) -> list[str]:
    lang = "FR" if fr else "EN"
    src_state = state.setdefault("source_state", {})
    msgs: list[str] = []
    for sh in getattr(report, "source_health", []) or []:
        cur = _status_code(sh.status)
        prev_raw = src_state.get(sh.source)
        prev = _status_code(prev_raw) if prev_raw is not None else None
        if prev is not None and prev != cur:
            msgs.append(
                _t(
                    lang,
                    "source",
                    source=sh.source,
                    prev=_status_label(lang, prev),
                    cur=_status_label(lang, cur),
                )
            )
        src_state[sh.source] = cur
    state["source_state"] = src_state
    return msgs


def _rule_mt5(state: dict, now_utc: datetime, fr: bool) -> list[str]:
    lang = "FR" if fr else "EN"
    from nqcockpit.broker.mt5_client import MT5Client

    status = MT5Client().get_status()
    connected = bool(status.is_ok)
    prev = state.get("mt5_connected")
    state["mt5_connected"] = connected
    if prev is None or prev == connected:
        return []
    return [_t(lang, "mt5.connected" if connected else "mt5.disconnected")]


def _rule_discipline(state: dict, now_utc: datetime, config, db_path: str, fr: bool) -> list[str]:
    lang = "FR" if fr else "EN"
    from nqcockpit.discipline.engine import evaluate_session_state
    from nqcockpit.journal.store import init_journal_db, load_trades

    conn = init_journal_db(db_path)
    try:
        trades = load_trades(conn)
    finally:
        conn.close()
    st = evaluate_session_state(trades, now_utc, config)
    code = _status_code(st.status)
    locked = code in _LOCK_CODES
    prev = state.get("discipline_locked", False)
    state["discipline_locked"] = locked
    if locked:
        reasons = _LABELS[lang].get(f"discipline.reason.{code}", code)
        return [_t(lang, "discipline.lock", reasons=reasons)]
    # Hors fenêtre horaire = état normal : aucun message.
    if prev and code != "OUT_OF_WINDOW":
        return [_t(lang, "discipline.clear")]
    return []


def _last_nq_price(now_utc: datetime) -> float | None:
    from nqcockpit.data.fetcher import DataFetcher

    series = DataFetcher().fetch_yahoo_bars("NQ=F", interval="1m", period="1d")
    if not series.bars:
        return None
    last = series.bars[-1]
    if last.timestamp_utc and (now_utc - last.timestamp_utc).total_seconds() > 15 * 60:
        log.info("Prix NQ périmé (>15 min), règle niveau ignorée")
        return None
    return float(last.close)


def _rule_level(cfg: dict, state: dict, now_utc: datetime, db_path: str, fr: bool) -> list[str]:
    from nqcockpit.data.db import get_db_connection, get_latest_snapshot

    conn = get_db_connection(db_path)
    try:
        snap = get_latest_snapshot(conn)
    finally:
        conn.close()
    if not snap:
        log.info("Snapshot niveaux absent, règle niveau ignorée")
        return []
    price = _last_nq_price(now_utc)
    if price is None:
        log.info("Prix NQ indisponible, règle niveau ignorée")
        return []

    lang = "FR" if fr else "EN"
    levels = {
        "Call Wall": snap.get("call_wall"),
        "Gamma Flip": snap.get("gamma_flip"),
        "Put Support": snap.get("put_support"),
    }
    today = now_utc.astimezone(TZ_ALGIERS).date().isoformat()
    touched = state.setdefault("level_touch", {})
    msgs: list[str] = []
    for name, level in levels.items():
        if level is None:
            continue
        key = f"{name}:{today}"
        if touched.get(key):
            continue
        if abs(price - level) <= cfg["level_touch_pts"]:
            msgs.append(
                _t(lang, "level", dist=abs(price - level), name=name, level=level)
            )
            touched[key] = True
    state["level_touch"] = touched
    return msgs


def _dedupe_and_send(state: dict, msgs: list[str], cfg: dict, now_utc: datetime) -> int:
    sent_map = state.setdefault("sent", {})
    hour = now_utc.strftime("%Y-%m-%dT%H")
    hourly = state.setdefault("hourly", {})
    if hourly.get("hour") != hour:
        hourly = {"hour": hour, "count": 0}
        state["hourly"] = hourly
    cooldown = cfg["cooldown_min"] * 60
    for msg in msgs:
        last = sent_map.get(msg)
        if last:
            try:
                if (now_utc - datetime.fromisoformat(last)).total_seconds() < cooldown:
                    continue
            except ValueError:
                pass
        if hourly["count"] >= cfg["max_per_hour"]:
            log.info("Plafond horaire atteint, alerte ignorée")
            return 0
        res = send_telegram_message(msg)
        log.info("Alerte envoyée [%s]: %s", res.status, msg)
        if res.status in ("OK", "DRY_RUN"):
            sent_map[msg] = now_utc.isoformat()
            hourly["count"] += 1
    return 0


def _setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = logging.FileHandler(log_dir / "alerter.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("nqcockpit.alerts")
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def evaluate() -> int:
    _setup_logging()
    now_utc = datetime.now(UTC)
    config = load_config()
    fr = _lang() == "FR"
    cfg = _cfg()
    state_path = _state_path()
    state = _load_state(state_path)

    if _in_quiet_hours(cfg, now_utc):
        log.info("Heures calmes: alerteur silencieux")
        return 0

    db_path = os.getenv("NQ_DATA_DB_PATH", config.data.db_path)
    enabled = cfg["enabled"]
    msgs: list[str] = []

    report = None
    if ("event" in enabled) or ("source" in enabled):
        try:
            report = fetch_event_radar(config=config, ref_utc=now_utc)
        except Exception as exc:  # noqa: BLE001
            log.info("Radar indisponible, règles événement/source ignorées: %s", exc)

    if "event" in enabled and report is not None:
        try:
            msgs += _rule_event(cfg, report, now_utc, fr)
        except Exception as exc:  # noqa: BLE001
            log.info("Règle événement ignorée: %s", exc)
    if "source" in enabled and report is not None:
        try:
            msgs += _rule_source(state, report, now_utc, fr)
        except Exception as exc:  # noqa: BLE001
            log.info("Règle source ignorée: %s", exc)
    if "mt5" in enabled:
        try:
            msgs += _rule_mt5(state, now_utc, fr)
        except Exception as exc:  # noqa: BLE001
            log.info("Règle MT5 ignorée: %s", exc)
    if "discipline" in enabled:
        try:
            msgs += _rule_discipline(state, now_utc, config, db_path, fr)
        except Exception as exc:  # noqa: BLE001
            log.info("Règle discipline ignorée: %s", exc)
    if "level" in enabled:
        try:
            msgs += _rule_level(cfg, state, now_utc, db_path, fr)
        except Exception as exc:  # noqa: BLE001
            log.info("Règle niveau ignorée: %s", exc)

    _dedupe_and_send(state, msgs, cfg, now_utc)
    _save_state(state_path, state)
    return 0


def _test_message() -> int:
    """Envoie un message de test unique et n'affiche que le statut HTTP."""
    res = send_telegram_message("NQ Cockpit alerter OK")
    print(res.status)
    return 0


def main(argv: list[str] | None = None) -> int:
    from nqcockpit.env import load_environment

    load_environment()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--test" in argv:
        return _test_message()
    return evaluate()


if __name__ == "__main__":
    raise SystemExit(main())
