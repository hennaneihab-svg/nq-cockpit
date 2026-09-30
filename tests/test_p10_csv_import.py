"""Tests pytest pour l'import CSV du journal de bord (P10 reliquat).

Couvre :
- Import complet valide
- Colonne optionnelle manquante (tolérée et signalée)
- Colonne obligatoire manquante (erreur explicite sans exception brute)
- Détection et rejet des doublons
- CSV vide
- Exécution CLI `journal import-csv`
"""

from __future__ import annotations

import io
import sqlite3

import pytest

from nqcockpit.config import load_config
from nqcockpit.journal.importer import (
    import_trades_from_csv,
)
from nqcockpit.journal.models import TradeDirection, TradeOutcome
from nqcockpit.journal.store import init_journal_db, load_trades


@pytest.fixture()
def mem_conn() -> sqlite3.Connection:
    """Base SQLite en mémoire pour isoler les tests."""
    return init_journal_db(":memory:")


@pytest.fixture()
def config():
    """Configuration réelle."""
    return load_config()


VALID_CSV = """session_date,instrument,direction,entry_price,stop_price,exit_price,notes,setup_tag
2026-09-25,MNQ,LONG,20800.0,20750.0,20900.0,Test long win,VWAP_bounce
2026-09-25,MNQ,SHORT,20850.0,20890.0,20890.0,Test short loss,Reversal_fail
"""

CSV_MISSING_OPTIONAL = """session_date,instrument,direction,entry_price,stop_price,exit_price
2026-09-26,NQ,LONG,20500.0,20460.0,20580.0
"""

CSV_MISSING_REQUIRED = """session_date,instrument,entry_price,stop_price,exit_price
2026-09-26,MNQ,20500.0,20460.0,20580.0
"""

CSV_INVALID_PRICES = """session_date,instrument,direction,entry_price,stop_price,exit_price
2026-09-26,MNQ,LONG,pas_un_prix,20460.0,20580.0
"""


def test_import_valid_full_csv(mem_conn, config):
    """Import complet valide : calcule R et enregistre en base."""
    summary = import_trades_from_csv(io.StringIO(VALID_CSV), mem_conn, config)

    assert summary.is_success is True
    assert summary.total_rows == 2
    assert summary.imported == 2
    assert summary.duplicates == 0
    assert summary.rejected == 0

    trades = load_trades(mem_conn)
    assert len(trades) == 2

    # Vérification des calculs automatiques
    long_trade = next(t for t in trades if t.direction == TradeDirection.LONG)
    assert long_trade.r_realized == pytest.approx(2.0, abs=1e-2)
    assert long_trade.outcome == TradeOutcome.WIN
    assert long_trade.setup_tag == "VWAP_bounce"

    short_trade = next(t for t in trades if t.direction == TradeDirection.SHORT)
    assert short_trade.r_realized == pytest.approx(-1.0, abs=1e-2)
    assert short_trade.outcome == TradeOutcome.LOSS


def test_import_missing_optional_column(mem_conn, config):
    """Colonne optionnelle absente : l'import réussit et signale les colonnes manquantes."""
    summary = import_trades_from_csv(
        io.StringIO(CSV_MISSING_OPTIONAL), mem_conn, config
    )

    assert summary.is_success is True
    assert summary.imported == 1
    assert "notes" in summary.missing_optional_columns
    assert "setup_tag" in summary.missing_optional_columns
    assert "tp1_price" in summary.missing_optional_columns

    trades = load_trades(mem_conn)
    assert len(trades) == 1
    assert trades[0].notes == ""
    assert trades[0].tp1_price is None


def test_import_missing_required_column(mem_conn, config):
    """Colonne obligatoire ('direction') manquante : échec clair sans exception brute."""
    summary = import_trades_from_csv(
        io.StringIO(CSV_MISSING_REQUIRED), mem_conn, config
    )

    assert summary.is_success is False
    assert summary.imported == 0
    assert len(summary.errors) >= 1
    assert "direction" in summary.errors[0]
    assert load_trades(mem_conn) == []


def test_import_invalid_price_row(mem_conn, config):
    """Ligne avec prix non numérique : rejetée et signalée proprement."""
    summary = import_trades_from_csv(
        io.StringIO(CSV_INVALID_PRICES), mem_conn, config
    )

    assert summary.rejected == 1
    assert summary.imported == 0
    assert any("invalide" in err for err in summary.errors)


def test_import_duplicate_detection(mem_conn, config):
    """Importation du même trade deux fois : détecté comme doublon et non inséré."""
    # 1er import
    summary1 = import_trades_from_csv(
        io.StringIO(VALID_CSV), mem_conn, config
    )
    assert summary1.imported == 2
    assert summary1.duplicates == 0

    # 2nd import du même contenu
    summary2 = import_trades_from_csv(
        io.StringIO(VALID_CSV), mem_conn, config
    )
    assert summary2.imported == 0
    assert summary2.duplicates == 2
    assert summary2.total_rows == 2

    # Nombre total en base reste 2
    assert len(load_trades(mem_conn)) == 2


def test_import_empty_csv(mem_conn, config):
    """CSV vide : message d'erreur clair, aucun crash."""
    summary = import_trades_from_csv(io.StringIO("   \n  \n"), mem_conn, config)

    assert summary.is_success is False
    assert summary.imported == 0
    assert any("vide" in err.lower() for err in summary.errors)


def test_import_reference_template_file(mem_conn, config):
    """Vérifie que le modèle de référence journal_import_template.csv est 100% valide."""
    from pathlib import Path

    tpl = Path("reports/templates/journal_import_template.csv")
    assert tpl.is_file(), f"Modèle {tpl} manquant"

    summary = import_trades_from_csv(tpl, mem_conn, config)
    assert summary.is_success is True
    assert summary.imported == 3
    assert summary.duplicates == 0
    assert summary.rejected == 0
    assert len(summary.errors) == 0


def test_cli_journal_import_csv(tmp_path, monkeypatch):
    """Vérifie l'exécution CLI `journal import-csv`."""
    csv_file = tmp_path / "test_import.csv"
    csv_file.write_text(VALID_CSV, encoding="utf-8")

    db_file = tmp_path / "test_journal.db"
    monkeypatch.setenv("NQ_DATA_DB_PATH", str(db_file))

    from nqcockpit.cli import main

    exit_code = main(["journal", "import-csv", str(csv_file)])
    assert exit_code == 0


def test_import_two_trades_same_price_different_entry_time(mem_conn, config):
    """Deux trades avec mêmes prix/date/instrument/direction mais entry_time_ny différent.

    Tous deux doivent être importés sans faux doublon.
    """
    header = (
        "session_date,instrument,direction,entry_price,"
        "stop_price,exit_price,entry_time_ny\n"
    )
    r1 = "2026-09-28,MNQ,LONG,20850.0,20800.0,20900.0,2026-09-28 09:35:00\n"
    r2 = "2026-09-28,MNQ,LONG,20850.0,20800.0,20900.0,2026-09-28 11:15:00\n"
    csv_timed = header + r1 + r2
    summary = import_trades_from_csv(io.StringIO(csv_timed), mem_conn, config)
    assert summary.is_success is True
    assert summary.imported == 2
    assert summary.duplicates == 0
    assert summary.total_rows == 2

    trades = load_trades(mem_conn)
    assert len(trades) == 2
    times = {t.entry_time_ny.strftime("%H:%M:%S") for t in trades if t.entry_time_ny}
    assert times == {"09:35:00", "11:15:00"}
