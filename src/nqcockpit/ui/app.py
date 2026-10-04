"""Application Streamlit Consolidée Multipage NQ Cockpit (Design System Swetrix).

Design System extrait de Swetrix (Analytics Dashboard) :
- Fond principal : #020617 (Tailwind Slate-950)
- Cartes & Panneaux : #0F172A (Tailwind Slate-900 / 0.6)
- Bordures : rgba(51, 65, 85, 0.6) (Tailwind Slate-800/60)
- Texte principal : #F8FAFC (Gray-50), Secondaire : #CBD5E1 (Slate-300), Muted : #94A3B8 (Slate-400)
- Accents : Indigo #6366F1 / #818CF8
- Rayons de bordure : rounded-lg (8px) pour cartes, rounded-md (6px) pour badges
- Typographie soignée, alignement net, zéro emoji, conformité totale aux règles.
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
    page_title="NQ Cockpit — Desk de Trading",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Injection CSS Thème Swetrix
st.markdown(
    """
    <style>
    .stApp {
        background-color: #020617;
        color: #F8FAFC;
        font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 98% !important;
    }
    /* En-tête de barre latérale Swetrix */
    .sidebar-brand {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
    }
    .sidebar-brand-title {
        font-size: 1.15rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: #F8FAFC;
    }
    .sidebar-brand-badge {
        background-color: rgba(99, 102, 241, 0.15);
        border: 1px solid rgba(99, 102, 241, 0.35);
        color: #A5B4FC;
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 0.7rem;
        font-weight: 600;
        font-family: ui-monospace, monospace;
    }
    .sidebar-clock {
        background-color: #0F172A;
        border: 1px solid rgba(51, 65, 85, 0.6);
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 14px;
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-size: 0.76rem;
        color: #94A3B8;
        line-height: 1.5;
    }
    .sidebar-clock b {
        color: #F8FAFC;
    }
    /* Force l'élargissement complet des composants HTML personnalisés */
    [data-testid="stCustomComponentV1"] {
        width: 100% !important;
    }
    [data-testid="stCustomComponentV1"] iframe {
        width: 100% !important;
        min-width: 100% !important;
        border-radius: 8px !important;
        border: 1px solid rgba(51, 65, 85, 0.6) !important;
    }
    /* Stylisation du menu de navigation */
    .stRadio label {
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        color: #CBD5E1 !important;
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
    # En-tête & Navigation Latérale Swetrix
    # ---------------------------------------------------------------------------
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <span class="sidebar-brand-title">NQ COCKPIT</span>
            <span class="sidebar-brand-badge">DESK</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        f"""
        <div class="sidebar-clock">
            <b>Alger :</b> {now_algiers.strftime('%Y-%m-%d %H:%M:%S')}<br>
            <b>New York :</b> {now_ny.strftime('%Y-%m-%d %H:%M:%S')} ET
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

    page_keys = list(PAGES.keys())
    default_idx = 0
    param_page = str(st.query_params.get("page", "")).lower()
    if param_page in ["1", "cockpit"]:
        default_idx = 0
    elif param_page in ["2", "journal"]:
        default_idx = 1
    elif param_page in ["3", "discipline"]:
        default_idx = 2
    elif param_page in ["4", "coaching"]:
        default_idx = 3
    elif param_page in ["5", "briefing"]:
        default_idx = 4

    choice = st.sidebar.radio(
        "Navigation Sections",
        page_keys,
        index=default_idx,
    )

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "NQ Cockpit P13 · Design System Swetrix · "
        "Strictement non-directionnel"
    )

    # Exécution du composant de la page choisie
    renderer = PAGES[choice]
    renderer()


if __name__ == "__main__":
    main()
