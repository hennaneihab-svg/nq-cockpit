"""Importateur de trades depuis des fichiers CSV vers la base SQLite (P10).

Règles impératives :
- Validation stricte des colonnes obligatoires (erreur claire si manquante)
- Tolérance aux colonnes optionnelles absentes (signalées dans le résumé, valeurs None/défaut)
- Détection et rejet explicite des doublons (même date + instrument + entrée/sortie)
- Résumé complet : lignes lues, importées, ignorées (doublons), rejetées
"""

from __future__ import annotations

import csv
import io
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nqcockpit.config import AppConfig
from nqcockpit.journal.engine import finalize_trade
from nqcockpit.journal.models import (
    GammaRegime,
    TradeDirection,
    TradeEntry,
    VolRegime,
)
from nqcockpit.journal.store import load_trades, save_trade

logger = logging.getLogger(__name__)

# Colonnes obligatoires et leurs alias reconnus
REQUIRED_COLUMN_ALIASES: dict[str, list[str]] = {
    "session_date": ["session_date", "date", "session"],
    "instrument": ["instrument", "symbol", "ticker"],
    "direction": ["direction", "side", "dir"],
    "entry_price": ["entry_price", "entry", "prix_entree", "prix_entrée"],
    "stop_price": ["stop_price", "stop", "sl", "prix_stop"],
    "exit_price": ["exit_price", "exit", "sortie", "prix_sortie"],
}

# Colonnes optionnelles standard du modèle TradeEntry
OPTIONAL_COLUMNS: list[str] = [
    "entry_time_ny",
    "exit_time_ny",
    "tp1_price",
    "tp2_price",
    "exit_reason",
    "fees_points",
    "window_name",
    "setup_tag",
    "notes",
    "sl_moved",
    "early_exit",
    "risk_pct_used",
    "minutes_after_last_sl",
    "event_risk_label",
    "gamma_regime",
    "vol_regime",
    "screenshot_path",
    "contracts",
]


@dataclass
class CSVImportSummary:
    """Résumé détaillé d'une opération d'import CSV."""

    total_rows: int = 0
    imported: int = 0
    duplicates: int = 0
    rejected: int = 0
    missing_optional_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        """Indique si l'import a pu s'exécuter sans erreur bloquante."""
        return len(self.errors) == 0 or self.imported > 0


def _parse_bool(val: Any) -> bool:
    """Convertit une chaîne en booléen."""
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "oui", "vrai", "t")


def _parse_direction(val: str) -> TradeDirection:
    """Parse la direction du trade."""
    s = val.strip().upper()
    if s in ("LONG", "BUY", "ACHAT"):
        return TradeDirection.LONG
    if s in ("SHORT", "SELL", "VENTE"):
        return TradeDirection.SHORT
    return TradeDirection.NONE


def _parse_datetime(val: Any) -> Optional[datetime]:
    """Parse une chaîne datetime au format ISO ou date/heure standard."""
    if not val or not str(val).strip():
        return None
    s = str(val).strip()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def import_trades_from_csv(
    csv_file: str | Path | io.StringIO,
    conn: sqlite3.Connection,
    config: Optional[AppConfig] = None,
) -> CSVImportSummary:
    """Importe des trades depuis un fichier ou flux CSV vers SQLite.

    Args:
        csv_file: Chemin vers le fichier CSV ou flux StringIO.
        conn: Connexion SQLite active.
        config: Configuration optionnelle.

    Returns:
        CSVImportSummary avec comptage et détail des erreurs/doublons.
    """
    summary = CSVImportSummary()

    # 1. Ouverture du fichier ou buffer
    if isinstance(csv_file, (str, Path)):
        p = Path(csv_file)
        if not p.is_file():
            summary.errors.append(f"Fichier introuvable : {p}")
            return summary
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except OSError as exc:
            summary.errors.append(f"Erreur de lecture du fichier : {exc}")
            return summary
    else:
        content = csv_file.getvalue()

    if not content.strip():
        summary.errors.append("Le fichier CSV est vide.")
        return summary

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        summary.errors.append("Aucun en-tête trouvé dans le fichier CSV.")
        return summary

    # 2. Résolution des colonnes obligatoires via alias
    raw_headers = {name.strip().lower(): name for name in reader.fieldnames}
    resolved_required: dict[str, str] = {}
    missing_required: list[str] = []

    for req_key, aliases in REQUIRED_COLUMN_ALIASES.items():
        found = False
        for alias in aliases:
            if alias.lower() in raw_headers:
                resolved_required[req_key] = raw_headers[alias.lower()]
                found = True
                break
        if not found:
            missing_required.append(req_key)

    if missing_required:
        summary.errors.append(
            f"Colonnes obligatoires manquantes dans l'en-tête CSV : "
            f"{', '.join(sorted(missing_required))}. "
            f"En-têtes présents : {list(reader.fieldnames)}"
        )
        return summary

    # 3. Détection des colonnes optionnelles absentes
    for opt_col in OPTIONAL_COLUMNS:
        if opt_col.lower() not in raw_headers:
            summary.missing_optional_columns.append(opt_col)

    if "contracts" not in raw_headers:
        summary.warnings.append(
            "Colonne optionnelle 'contracts' absente : taille non renseignée (laissée à None)."
        )

    # 4. Chargement des trades existants pour détection des doublons
    # Si entry_time_ny est fourni dans le CSV, on l'inclut dans la clé de déduplication :
    # (session_date, instrument, entry_price, exit_price, direction, entry_time_ny)
    # pour éviter les faux doublons sur deux trades identiques en prix mais pris à
    # des heures différentes. Sans entry_time_ny, la déduplication reste sur les 5
    # champs existants (session_date, instrument, entry_price, exit_price, direction)
    # sous l'hypothèse de gestion stricte (pas deux trades identiques en prix le même
    # jour pour le même instrument et la même direction).
    existing_trades = load_trades(conn)
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

    # 5. Traitement ligne par ligne
    rows = list(reader)
    summary.total_rows = len(rows)

    for row_idx, row in enumerate(rows, start=2):
        # Validation des champs obligatoires
        s_date = row.get(resolved_required["session_date"], "").strip()
        s_inst = row.get(resolved_required["instrument"], "").strip().upper()
        s_dir_raw = row.get(resolved_required["direction"], "").strip()
        s_entry_raw = row.get(resolved_required["entry_price"], "").strip()
        s_stop_raw = row.get(resolved_required["stop_price"], "").strip()
        s_exit_raw = row.get(resolved_required["exit_price"], "").strip()

        if not (s_date and s_inst and s_dir_raw and s_entry_raw and s_stop_raw and s_exit_raw):
            summary.rejected += 1
            summary.errors.append(
                f"Ligne {row_idx} : un champ obligatoire est vide."
            )
            continue

        direction = _parse_direction(s_dir_raw)
        if direction == TradeDirection.NONE:
            summary.rejected += 1
            summary.errors.append(
                f"Ligne {row_idx} : direction invalide ({s_dir_raw!r}). "
                "Valeurs acceptées : LONG, SHORT, BUY, SELL."
            )
            continue

        try:
            entry_p = float(s_entry_raw)
            stop_p = float(s_stop_raw)
            exit_p = float(s_exit_raw)
        except ValueError:
            summary.rejected += 1
            summary.errors.append(
                f"Ligne {row_idx} : valeur numérique de prix invalide "
                f"(entrée={s_entry_raw!r}, stop={s_stop_raw!r}, sortie={s_exit_raw!r})."
            )
            continue

        # Extraction des champs optionnels
        def get_opt(name: str, default: Any = "") -> Any:
            for alias in [name, name.lower()]:
                if alias in raw_headers:
                    val = row.get(raw_headers[alias], "")
                    if val is not None and str(val).strip() != "":
                        return str(val).strip()
            return default

        entry_time_raw = get_opt("entry_time_ny", None)
        entry_time_dt = _parse_datetime(entry_time_raw)
        exit_time_raw = get_opt("exit_time_ny", None)
        exit_time_dt = _parse_datetime(exit_time_raw)

        # Détection de doublons contextuelle
        is_dup = False
        if entry_time_dt is not None:
            timed_key = (
                s_date,
                s_inst,
                round(entry_p, 2),
                round(exit_p, 2),
                direction.value,
                entry_time_dt.isoformat(),
            )
            if timed_key in existing_timed_keys:
                is_dup = True
        else:
            five_key = (
                s_date,
                s_inst,
                round(entry_p, 2),
                round(exit_p, 2),
                direction.value,
            )
            if five_key in existing_5_keys:
                is_dup = True

        if is_dup:
            summary.duplicates += 1
            continue

        tp1_val = get_opt("tp1_price", None)
        tp1_p = float(tp1_val) if tp1_val is not None else None

        tp2_val = get_opt("tp2_price", None)
        tp2_p = float(tp2_val) if tp2_val is not None else None

        fees_val = get_opt("fees_points", "0.0")
        try:
            fees_pts = float(fees_val)
        except ValueError:
            fees_pts = 0.0

        min_after_sl_val = get_opt("minutes_after_last_sl", None)
        min_after_sl = (
            float(min_after_sl_val) if min_after_sl_val is not None else None
        )

        risk_pct_val = get_opt("risk_pct_used", "0.0")
        try:
            risk_pct = float(risk_pct_val)
        except ValueError:
            risk_pct = 0.0

        # Normalisation de screenshot_path : toujours résolu en absolu avant stockage
        # (cohérent avec attach-screenshot dans cli.py). Si un chemin relatif est
        # fourni dans le CSV, il est résolu par rapport au répertoire de travail (CWD).
        raw_screenshot = get_opt("screenshot_path", "").strip()
        resolved_screenshot = (
            str(Path(raw_screenshot).resolve()) if raw_screenshot else ""
        )

        # Parsing de la taille en contrats (optionnelle)
        raw_contracts = get_opt("contracts", None)
        contracts_val: Optional[int] = None
        if raw_contracts is not None and str(raw_contracts).strip() != "":
            try:
                contracts_val = int(raw_contracts)
            except (ValueError, TypeError):
                summary.warnings.append(
                    f"Ligne {row_idx} : valeur de 'contracts' invalide ({raw_contracts!r}), "
                    "laissée à None."
                )
                contracts_val = None
        elif "contracts" in raw_headers:
            summary.warnings.append(
                f"Ligne {row_idx} : colonne 'contracts' vide, laissée à None."
            )

        trade = TradeEntry(
            trade_id=str(uuid.uuid4()),
            recorded_at=datetime.now(timezone.utc),
            session_date=s_date,
            instrument=s_inst,
            direction=direction,
            entry_price=entry_p,
            stop_price=stop_p,
            exit_price=exit_p,
            tp1_price=tp1_p,
            tp2_price=tp2_p,
            exit_reason=get_opt("exit_reason", ""),
            fees_points=fees_pts,
            window_name=get_opt("window_name", ""),
            entry_time_ny=entry_time_dt,
            exit_time_ny=exit_time_dt,
            setup_tag=get_opt("setup_tag", ""),
            notes=get_opt("notes", ""),
            sl_moved=_parse_bool(get_opt("sl_moved", False)),
            early_exit=_parse_bool(get_opt("early_exit", False)),
            risk_pct_used=risk_pct,
            minutes_after_last_sl=min_after_sl,
            event_risk_label=get_opt("event_risk_label", ""),
            gamma_regime=GammaRegime(get_opt("gamma_regime", "inconnu"))
            if get_opt("gamma_regime", "inconnu") in [g.value for g in GammaRegime]
            else GammaRegime.UNKNOWN,
            vol_regime=VolRegime(get_opt("vol_regime", "inconnu"))
            if get_opt("vol_regime", "inconnu") in [v.value for v in VolRegime]
            else VolRegime.UNKNOWN,
            screenshot_path=resolved_screenshot,
            contracts=contracts_val,
        )

        # Calcul automatique du R et de l'outcome via le moteur
        trade = finalize_trade(trade)

        # Sauvegarde en base et mise à jour du set de dédoublonnage
        save_trade(conn, trade)
        existing_5_keys.add((
            s_date,
            s_inst,
            round(entry_p, 2),
            round(exit_p, 2),
            direction.value,
        ))
        if entry_time_dt is not None:
            existing_timed_keys.add((
                s_date,
                s_inst,
                round(entry_p, 2),
                round(exit_p, 2),
                direction.value,
                entry_time_dt.isoformat(),
            ))
        summary.imported += 1

    return summary
