"""Application Streamlit Consolidée Multipage NQ Cockpit (P13).

Point d'entrée unique regroupant les 5 pages du cockpit :
1. ⚡ Cockpit Live (Profil de séance P08)
2. 📓 Journal de Bord (Saisie et suivi P09)
3. 🛡️ Discipline & Sizing (Porte de discipline et risques P09)
4. 📊 Coaching & Analytics (Visualisations Plotly et fuites P11)
5. 📄 Briefing Pré-Séance (Document consolidé P12)

Strictement non-directionnel, thème sombre trading terminal sur le port unique 8501.
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
    page_title="NQ Cockpit — Terminal Trading Multipage",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Injection CSS Thème Sombre & Terminal Typography
st.markdown(
    """
    <style>
    .stApp {
        background-color: #0d1117;
        color: #e6edf3;
        font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    }
    .sidebar-header {
        font-size: 1.2rem;
        font-weight: bold;
        color: #3fb950;
        margin-bottom: 0.5rem;
    }
    .sidebar-clock {
        font-size: 0.85rem;
        color: #8b949e;
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 6px 10px;
        margin-bottom: 12px;
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
        '<div class="sidebar-header">⚡ NQ COCKPIT TERMINAL</div>',
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
        "⚡ Cockpit Live": render_cockpit,
        "📓 Journal de Bord": render_journal_page,
        "🛡️ Discipline & Sizing": render_discipline_page,
        "📊 Coaching & Analytics": render_coaching_app,
        "📄 Briefing Pré-Séance": render_briefing_page,
    }

    choice = st.sidebar.radio(
        "Navigation",
        list(PAGES.keys()),
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "NQ Cockpit P13 · Port unique 8501 · "
        "Strictement non-directionnel"
    )

    # Exécution du composant de la page choisie
    renderer = PAGES[choice]
    renderer()


if __name__ == "__main__":
    main()
