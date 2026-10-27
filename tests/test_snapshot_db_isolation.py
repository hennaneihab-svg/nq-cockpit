"""Preuve de non-pollution : une exécution complète de pytest ne touche pas la base de production.

Le test lance la suite dans un sous-processus (en excluant ce test lui-même) puis
compare le nombre de snapshots de `data/nqcockpit.db` avant et après.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB = REPO_ROOT / "data" / "nqcockpit.db"


def _snapshot_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
    finally:
        conn.close()


def test_full_pytest_run_does_not_touch_production_snapshots() -> None:
    before = _snapshot_count(PRODUCTION_DB)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-p",
            "no:cacheprovider",
            "--deselect",
            "tests/test_snapshot_db_isolation.py::"
            "test_full_pytest_run_does_not_touch_production_snapshots",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )

    assert result.returncode == 0, (
        "La suite pytest lancée depuis le test a échoué :\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
    assert "passed" in result.stdout, result.stdout[-2000:]
    assert _snapshot_count(PRODUCTION_DB) == before
