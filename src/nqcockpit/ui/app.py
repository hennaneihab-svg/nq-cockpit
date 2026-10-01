"""Application Streamlit Consolidée Multipage NQ Cockpit (P13).

Design System Final : Bloomberg Terminal x TradingView Desk.
- Fond principal : #0D0D0D (Bloomberg Terminal)
- Panels & Cartes : #131722 (TradingView Dark Slate)
- Bordures : #2A2E39 (TradingView 1px)
- Accents Marque/Navigation : #FA7900 (Orange Signature Bloomberg)
- Zéro emoji, badges en contour 1px, typographie tabulaire pour données.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from nqcockpit.config import load_config
from nqcockpit.ui.briefing_page import render_briefing_page
from nqcockpit.ui.coaching_page import render_coaching_app
from nqcockpit.ui.cockpit_page import render_cockpit
from nqcockpit.ui.discipline_page import render_discipline_page
from nqcockpit.ui.journal_page import render_journal_page

# ---------------------------------------------------------------------------
# Configuration Initiale Unique
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="NQ Cockpit — Terminal Multipage",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Injection CSS Thème Final Bloomberg x TradingView
st.markdown(
    """
    <style>
    .stApp {
        background-color: #0D0D0D;
        color: #D1D4DC;
        font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .sidebar-header {
        font-family: ui-monospace, SFMono-Regular, "JetBrains Mono", Consolas, monospace;
        font-size: 1.1rem;
        font-weight: 700;
        color: #FA7900;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }
    .sidebar-clock {
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        font-size: 0.78rem;
        color: #787B86;
        background-color: #131722;
        border: 1px solid #2A2E39;
        border-radius: 3px;
        padding: 8px 10px;
        margin-bottom: 12px;
    }
    /* Stylisation du menu radio dans la sidebar */
    .stRadio label {
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace !important;
        font-size: 0.82rem !important;
        color: #D1D4DC !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    """Point d'entrée principal de l'application multipage NQ Cockpit."""
    config = load_config()
    tz_algiers = ZoneInfo(config.timezones.display)
    tz_ny = ZoneInfo(config.timezones.market)

    now_algiers = datetime.now(tz_algiers)
    now_ny = datetime.now(tz_ny)

    # ---------------------------------------------------------------------------
    # Navigation Latérale Consolidée
    # ---------------------------------------------------------------------------
    st.sidebar.markdown(
        '<div class="sidebar-header">NQ COCKPIT // TERMINAL</div>',
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        f"""
        <div class="sidebar-clock">
            <b>Alger</b> : {now_algiers.strftime('%Y-%m-%d %H:%M:%S')}<br>
            <b>New York</b> : {now_ny.strftime('%Y-%m-%d %H:%M:%S')} (ET)
        </div>
        """,
        unsafe_allow_html=True,
    )

    db_file = Path(config.data.db_path)
    db_status_str = f"`{db_file.name}` (OK)" if db_file.exists() else "`Base absente` (DÉGRADÉ)"
    st.sidebar.caption(f"Base SQLite : {db_status_str}")
    st.sidebar.markdown("---")

    PAGES = {
        "[01] COCKPIT LIVE": render_cockpit,
        "[02] JOURNAL DE BORD": render_journal_page,
        "[03] DISCIPLINE & SIZING": render_discipline_page,
        "[04] COACHING & ANALYTICS": render_coaching_app,
        "[05] BRIEFING PRE-SEANCE": render_briefing_page,
    }

    choice = st.sidebar.radio(
        "Navigation Sections",
        list(PAGES.keys()),
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "NQ Cockpit P13 · Bloomberg x TradingView Desk · "
        "Strictement non-directionnel"
    )

    # Exécution du composant de la page choisie
    renderer = PAGES[choice]
    renderer()


if __name__ == "__main__":
    main()
