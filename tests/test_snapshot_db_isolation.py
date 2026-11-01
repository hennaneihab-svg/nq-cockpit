"""Preuve d'isolation : les tests n'écrivent jamais dans la base de production.

Déterministe et sans réseau ni sous-processus. Vérifie que :
1. ``NQ_DATA_DB_PATH`` est redirigé (par conftest) hors du fichier de production.
2. Une écriture de journal atterrit dans cette base isolée, sans toucher
   ``data/nqcockpit.db``.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB = REPO_ROOT / "data" / "nqcockpit.db"


def _snapshot_count(db_path: Path) -> int:
    """Nombre de lignes de la table snapshots (0 si la base/table n'existe pas)."""
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM snapshots"
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def test_db_path_is_isolated_to_temp() -> None:
    """NQ_DATA_DB_PATH pointe ailleurs que sur la base de production."""
    db_path = os.environ.get("NQ_DATA_DB_PATH")
    assert db_path, "NQ_DATA_DB_PATH doit être défini par conftest"
    assert Path(db_path).resolve() != PRODUCTION_DB.resolve(), (
        "NQ_DATA_DB_PATH ne doit pas pointer sur la base de production"
    )


def test_journal_writes_stay_off_production() -> None:
    """Une écriture de journal reste dans la base isolée, production intacte."""
    before = _snapshot_count(PRODUCTION_DB)

    from nqcockpit.journal.models import TradeDirection, TradeEntry, TradeOutcome
    from nqcockpit.journal.store import init_journal_db, save_trade

    db_path = os.environ["NQ_DATA_DB_PATH"]
    conn = init_journal_db(db_path)
    save_trade(
        conn,
        TradeEntry(
            trade_id="isolation-check-1",
            recorded_at=datetime.now(timezone.utc),
            session_date="2026-10-31",
            instrument="MNQ",
            direction=TradeDirection.LONG,
            entry_price=20000.0,
            stop_price=19980.0,
            exit_price=20020.0,
            r_realized=1.0,
            outcome=TradeOutcome.WIN,
        ),
    )
    conn.close()

    # L'écriture est allée dans la base isolée.
    iso_conn = sqlite3.connect(db_path)
    try:
        count = int(iso_conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0])
    finally:
        iso_conn.close()
    assert count >= 1

    # La base de production n'a pas bougé.
    assert _snapshot_count(PRODUCTION_DB) == before
