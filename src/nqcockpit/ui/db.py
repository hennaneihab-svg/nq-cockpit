"""Gestion centralisée de la connexion SQLite pour l'interface UI Streamlit (P13).

Fournit une fonction mise en cache via @st.cache_resource unique et thread-safe
pour l'ensemble des pages de l'application multipage.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from nqcockpit.config import load_config
from nqcockpit.journal.store import init_journal_db


@st.cache_resource
def get_ui_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Ouvre et met en cache une connexion SQLite partagée pour l'UI."""
    if db_path is None:
        config = load_config()
        db_path = config.data.db_path
    return init_journal_db(db_path)
