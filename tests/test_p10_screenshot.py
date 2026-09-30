"""Tests pytest pour l'attachement de captures d'écran aux trades du journal (P10 élément 2/3).

Couvre :
- Attachement d'une capture valide (fichier existant)
- Rejet si le fichier image est introuvable sur le disque (pas d'enregistrement silencieux)
- Rejet si l'identifiant du trade n'existe pas en base
- Import CSV avec et sans colonne screenshot_path
- Vérification de l'état dégradé si le fichier référencé a disparu du disque
"""

from __future__ import annotations

import io
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nqcockpit.config import load_config
from nqcockpit.journal.importer import import_trades_from_csv
from nqcockpit.journal.models import TradeDirection, TradeEntry
from nqcockpit.journal.store import (
    get_trade,
    init_journal_db,
    load_trades,
    save_trade,
    update_trade_screenshot,
)


@pytest.fixture()
def mem_conn() -> sqlite3.Connection:
    """Base SQLite en mémoire isolée."""
    return init_journal_db(":memory:")


@pytest.fixture()
def config():
    """Configuration réelle."""
    return load_config()


def _create_sample_trade(conn: sqlite3.Connection) -> TradeEntry:
    t = TradeEntry(
        trade_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        session_date="2026-09-30",
        instrument="MNQ",
        direction=TradeDirection.LONG,
        entry_price=20800.0,
        stop_price=20750.0,
        exit_price=20900.0,
        r_realized=2.0,
    )
    save_trade(conn, t)
    return t


def test_attach_screenshot_valid(mem_conn, tmp_path):
    """Attachement d'un fichier image réel existant -> enregistré avec succès."""
    trade = _create_sample_trade(mem_conn)
    img_file = tmp_path / "chart_trade.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_data")

    assert img_file.is_file()

    updated = update_trade_screenshot(mem_conn, trade.trade_id, str(img_file))
    assert updated is True

    loaded = get_trade(mem_conn, trade.trade_id)
    assert loaded is not None
    assert loaded.screenshot_path == str(img_file)
    assert Path(loaded.screenshot_path).is_file() is True


def test_attach_screenshot_cli_valid(tmp_path, monkeypatch):
    """Exécution CLI attach-screenshot avec fichier existant."""
    db_file = tmp_path / "test_journal.db"
    conn = init_journal_db(db_file)
    trade = _create_sample_trade(conn)
    conn.close()

    img_file = tmp_path / "screenshot_test.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setenv("NQ_DATA_DB_PATH", str(db_file))
    from nqcockpit.cli import main

    code = main(["journal", "attach-screenshot", trade.trade_id, str(img_file)])
    assert code == 0

    # Vérification en base
    conn2 = init_journal_db(db_file)
    loaded = get_trade(conn2, trade.trade_id)
    assert loaded is not None
    assert Path(loaded.screenshot_path).resolve() == img_file.resolve()
    conn2.close()


def test_attach_screenshot_missing_file_cli_fails(tmp_path, monkeypatch, capsys):
    """Attachement d'un fichier inexistant -> échec explicite sans enregistrement."""
    db_file = tmp_path / "test_journal.db"
    conn = init_journal_db(db_file)
    trade = _create_sample_trade(conn)
    conn.close()

    fake_img = tmp_path / "inexistant.png"
    monkeypatch.setenv("NQ_DATA_DB_PATH", str(db_file))
    from nqcockpit.cli import main

    code = main(["journal", "attach-screenshot", trade.trade_id, str(fake_img)])
    assert code == 1

    out = capsys.readouterr().out
    assert "introuvable" in out.lower()

    # Le trade ne doit pas avoir été altéré
    conn2 = init_journal_db(db_file)
    loaded = get_trade(conn2, trade.trade_id)
    assert loaded is not None
    assert loaded.screenshot_path == ""
    conn2.close()


def test_attach_screenshot_missing_trade_cli_fails(tmp_path, monkeypatch, capsys):
    """Attachement avec un trade_id inconnu -> échec explicite."""
    db_file = tmp_path / "test_journal.db"
    conn = init_journal_db(db_file)
    conn.close()

    img_file = tmp_path / "valid.png"
    img_file.write_bytes(b"data")

    monkeypatch.setenv("NQ_DATA_DB_PATH", str(db_file))
    from nqcockpit.cli import main

    code = main(["journal", "attach-screenshot", "id-inexistant-12345", str(img_file)])
    assert code == 1

    out = capsys.readouterr().out
    assert "aucun trade trouvé" in out.lower()


def test_csv_import_with_screenshot_path(mem_conn, config):
    """Importation CSV avec la colonne optionnelle screenshot_path."""
    csv_data = (
        "session_date,instrument,direction,entry_price,stop_price,exit_price,screenshot_path\n"
        "2026-09-30,MNQ,LONG,20800.0,20750.0,20900.0,reports/screenshots/trade_01.png\n"
    )
    summary = import_trades_from_csv(io.StringIO(csv_data), mem_conn, config)
    assert summary.is_success is True
    assert summary.imported == 1
    assert "screenshot_path" not in summary.missing_optional_columns

    trades = load_trades(mem_conn)
    assert len(trades) == 1
    expected_abs = str(Path("reports/screenshots/trade_01.png").resolve())
    assert trades[0].screenshot_path == expected_abs
    assert Path(trades[0].screenshot_path).is_absolute() is True


def test_csv_import_relative_screenshot_path_resolved_to_absolute(mem_conn, config):
    """Import CSV avec screenshot_path relatif : stocké en chemin absolu en base."""
    rel_path = "reports/screenshots/my_chart.png"
    csv_data = (
        "session_date,instrument,direction,entry_price,stop_price,exit_price,screenshot_path\n"
        f"2026-09-30,MNQ,LONG,20800.0,20750.0,20900.0,{rel_path}\n"
    )
    summary = import_trades_from_csv(io.StringIO(csv_data), mem_conn, config)
    assert summary.is_success is True

    trades = load_trades(mem_conn)
    assert len(trades) == 1
    stored_path = trades[0].screenshot_path
    assert Path(stored_path).is_absolute() is True
    assert stored_path == str(Path(rel_path).resolve())


def test_csv_import_without_screenshot_path(mem_conn, config):
    """Importation CSV sans colonne screenshot_path -> signalée dans les colonnes absentes."""
    csv_data = """session_date,instrument,direction,entry_price,stop_price,exit_price
2026-09-30,MNQ,LONG,20800.0,20750.0,20900.0
"""
    summary = import_trades_from_csv(io.StringIO(csv_data), mem_conn, config)
    assert summary.is_success is True
    assert summary.imported == 1
    assert "screenshot_path" in summary.missing_optional_columns

    trades = load_trades(mem_conn)
    assert len(trades) == 1
    assert trades[0].screenshot_path == ""


def test_screenshot_degraded_status_when_file_deleted(mem_conn, tmp_path):
    """Vérifie la détection d'état dégradé si le fichier image référencé a été supprimé."""
    trade = _create_sample_trade(mem_conn)
    img_file = tmp_path / "deleted_chart.png"
    img_file.write_bytes(b"content")

    update_trade_screenshot(mem_conn, trade.trade_id, str(img_file))
    # Suppression du fichier du disque
    img_file.unlink()

    loaded = get_trade(mem_conn, trade.trade_id)
    assert loaded is not None
    assert loaded.screenshot_path != ""
    # Le fichier est introuvable -> condition d'état dégradé UI vérifiée
    assert Path(loaded.screenshot_path).is_file() is False
