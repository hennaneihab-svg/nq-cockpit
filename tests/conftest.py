"""Isolation de l'environnement de test.

Aucun test ne doit écrire dans la base de production `data/nqcockpit.db` :
`NQ_DATA_DB_PATH` pointe vers un fichier temporaire propre à chaque test.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_db(tmp_path, monkeypatch):
    """Redirige la base de données et les exports de niveaux vers le tmp_path du test."""
    monkeypatch.setenv("NQ_DATA_DB_PATH", str(tmp_path / "nqcockpit_test.db"))
    monkeypatch.setenv("NQ_LEVELS_OUTPUT_DIR", str(tmp_path / "levels"))
