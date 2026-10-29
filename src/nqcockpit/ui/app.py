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

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import streamlit as st

from nqcockpit.config import load_config
from nqcockpit.levels.scheduler import start_levels_scheduler_once
from nqcockpit.ui.coaching_page import render_coaching_app
from nqcockpit.ui.cockpit_page import render_cockpit
from nqcockpit.ui.components import render_page_safely
from nqcockpit.ui.i18n import render_lang_selector, t
from nqcockpit.ui.journal_discipline_page import render_journal_discipline_page
from nqcockpit.ui.levels_page import render_levels_page
from nqcockpit.ui.macro_page import render_macro_page
from nqcockpit.ui.nav import (
    active_page,
    page_name,
    render_sidebar_nav,
)
from nqcockpit.ui.settings_page import render_settings_page

log = logging.getLogger(__name__)

# One renderer per plain-language destination. The pre-session briefing is
# embedded in Settings, so the historical briefing page is reused there.
PAGE_RENDERERS = {
    "today": render_cockpit,
    "levels": render_levels_page,
    "macro": render_macro_page,
    "journal": render_journal_discipline_page,
    "coaching": render_coaching_app,
    "settings": render_settings_page,
}

# ---------------------------------------------------------------------------
# Configuration Initiale Unique
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="NQ Cockpit — Trading Desk",
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
    /* Buttons stay neutral: colour is reserved for data status. */
    .stButton > button[kind="primary"] {
        background-color: #0F172A !important;
        border: 1px solid #94A3B8 !important;
        color: #F8FAFC !important;
        font-weight: 700 !important;
    }
    .stButton > button[kind="secondary"] {
        background-color: transparent !important;
        border: 1px solid #334155 !important;
        color: #E2E8F0 !important;
    }
    .stButton > button:hover {
        border-color: #94A3B8 !important;
        color: #F8FAFC !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def _ensure_file_logging() -> bool:
    """Configure une seule fois les logs fichier (tracebacks complets consultables)."""
    from nqcockpit.logging import setup_logging

    setup_logging()
    return True


@st.cache_resource(show_spinner=False)
def _prewarm_cockpit_caches() -> bool:
    """Préchauffe une seule fois les caches 60 s du cockpit (première ouverture).

    Les chargements indépendants (profil, radar, fil) partent en parallèle : le
    premier rendu lit ensuite les caches, au lieu de refaire les appels réseau.
    Une erreur de préchauffage est journalisée et n'empêche pas l'affichage :
    la page montre son statut DÉGRADÉ habituel.
    """
    from nqcockpit.ui.cockpit_page import (
        load_chart_bars_cached,
        load_day_profile_cached,
        load_macro_radar_cached,
        load_news_wire_cached,
    )

    db_path = str(Path(load_config().data.db_path))
    loaders = {
        "profil de séance": lambda: load_day_profile_cached(db_path),
        "radar macro": load_macro_radar_cached,
        "fil d'actualités": lambda: load_news_wire_cached(max_items_per_source=4),
    }
    with ThreadPoolExecutor(max_workers=len(loaders)) as pool:
        futures = {pool.submit(loader): name for name, loader in loaders.items()}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - un cache manquant ne bloque pas l'app
                log.warning("Préchauffage %s incomplet: %s", futures[future], exc)

    # Après le profil (qui peut insérer des barres) pour lire la séance la plus fraîche.
    try:
        load_chart_bars_cached(db_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("Préchauffage graphique incomplet: %s", exc)
    return True


def main() -> None:
    """Application entry point: sidebar navigation + one page at a time."""
    _ensure_file_logging()
    # A single scheduler start per process (Streamlit reruns reuse it).
    start_levels_scheduler_once()

    # Deep links: ?page=today|levels|macro|journal|coaching|settings
    # plus the historical section numbers (1-5).
    query_page = str(st.query_params.get("page", ""))
    page_key = active_page(query_page)

    # Pre-warm only the default landing page (first run), so Today paints fast.
    if page_key == "today":
        with st.spinner(
            t(
                "Préchauffage des données de marché (première ouverture)…",
                "Pre-warming market data (first run)…",
            )
        ):
            _prewarm_cockpit_caches()

    # ---------------------------------------------------------------------------
    # Sidebar: brand, language, then the six plain-language destinations.
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

    with st.sidebar:
        render_lang_selector(key_prefix="sidebar_main")

    render_sidebar_nav(page_key)

    st.sidebar.markdown("---")
    st.sidebar.caption(
        t(
            "Aide à la décision non-directionnelle · NQ Cockpit",
            "Non-directional decision support · NQ Cockpit",
        )
    )

    # One renderer per destination; unexpected exceptions are caught and logged.
    renderer = PAGE_RENDERERS[page_key]
    render_page_safely(renderer, page_name(page_key))


if __name__ == "__main__":
    main()
