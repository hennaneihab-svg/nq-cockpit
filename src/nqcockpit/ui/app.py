"""NQ Cockpit Streamlit entry point — single-screen Terminal layout.

Top area: brand + compact horizontal navigation (Terminal | Journal &
Discipline | Coaching | Settings). The sidebar starts collapsed and no longer
carries the language switch (it lives in Settings). Colour stays reserved for
data status; the active tab only gets a neutral border.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import streamlit as st

from nqcockpit.config import load_config
from nqcockpit.levels.scheduler import start_levels_scheduler_once
from nqcockpit.ui.coaching_page import render_coaching_app
from nqcockpit.ui.components import render_page_safely
from nqcockpit.ui.i18n import t
from nqcockpit.ui.journal_discipline_page import render_journal_discipline_page
from nqcockpit.ui.nav import active_page, page_name, render_top_nav
from nqcockpit.ui.settings_page import render_settings_page
from nqcockpit.ui.terminal_page import render_terminal

log = logging.getLogger(__name__)

# One renderer per destination. Levels, Macro and Briefing are now panels of
# the Terminal page instead of separate destinations.
PAGE_RENDERERS = {
    "terminal": render_terminal,
    "journal": render_journal_discipline_page,
    "coaching": render_coaching_app,
    "settings": render_settings_page,
}

# ---------------------------------------------------------------------------
# Initial configuration (single call per run)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="NQ Cockpit — Trading Desk",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Swetrix dark theme, shared by every destination.
st.markdown(
    """
    <style>
    .stApp {
        background-color: #020617;
        color: #F8FAFC;
        font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    /* Streamlit's header is fixed on top (3.75rem tall): keep the brand and
       the top navigation below it instead of letting them slide underneath. */
    .block-container {
        padding-top: 4rem !important;
        padding-bottom: 1rem !important;
        max-width: 99% !important;
    }
    .app-brand {
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        color: #F8FAFC;
        white-space: nowrap;
        padding-top: 4px;
    }
    .app-brand span {
        color: #64748B;
        font-weight: 600;
        font-size: 0.72rem;
        margin-left: 6px;
    }
    [data-testid="stCustomComponentV1"] {
        width: 100% !important;
    }
    [data-testid="stCustomComponentV1"] iframe {
        width: 100% !important;
        min-width: 100% !important;
        border-radius: 8px !important;
        border: 1px solid rgba(51, 65, 85, 0.6) !important;
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
    """Configure file logging once (full tracebacks stay consultable)."""
    from nqcockpit.logging import setup_logging

    setup_logging()
    return True


@st.cache_resource(show_spinner=False)
def _prewarm_cockpit_caches() -> bool:
    """Warm the 60 s cockpit caches in parallel for a fast first paint.

    A failed pre-warm is logged and never blocks the page: the terminal shows
    its usual degraded status instead.
    """
    from nqcockpit.ui.cockpit_page import (
        load_chart_bars_cached,
        load_day_profile_cached,
        load_macro_radar_cached,
        load_news_wire_cached,
    )

    db_path = str(Path(load_config().data.db_path))
    loaders = {
        "session profile": lambda: load_day_profile_cached(db_path),
        "macro radar": load_macro_radar_cached,
        "news wire": lambda: load_news_wire_cached(max_items_per_source=4),
    }
    with ThreadPoolExecutor(max_workers=len(loaders)) as pool:
        futures = {pool.submit(loader): name for name, loader in loaders.items()}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - a missing cache never blocks the app
                log.warning("Pre-warm %s incomplete: %s", futures[future], exc)

    try:
        load_chart_bars_cached(db_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("Pre-warm chart incomplete: %s", exc)
    return True


def main() -> None:
    """Application entry point: top navigation + one page at a time."""
    _ensure_file_logging()
    # A single scheduler start per process (Streamlit reruns reuse it).
    start_levels_scheduler_once()

    # Deep links: ?page=terminal|journal|coaching|settings, legacy aliases too.
    query_page = str(st.query_params.get("page", ""))
    page_key = active_page(query_page)

    if page_key == "terminal":
        with st.spinner(
            t(
                "Préchauffage des données de marché (première ouverture)…",
                "Pre-warming market data (first run)…",
            )
        ):
            _prewarm_cockpit_caches()

    brand_col, nav_col = st.columns([2.2, 9.8], vertical_alignment="center")
    with brand_col:
        st.markdown(
            '<div class="app-brand">NQ COCKPIT<span>DESK</span></div>',
            unsafe_allow_html=True,
        )
    with nav_col:
        page_key = render_top_nav(page_key)

    # One renderer per destination; unexpected exceptions are caught and logged.
    renderer = PAGE_RENDERERS[page_key]
    render_page_safely(renderer, page_name(page_key))

    st.caption(
        t(
            "Aide à la décision non-directionnelle · aucune exécution d'ordre · NQ Cockpit",
            "Non-directional decision support · no order execution · NQ Cockpit",
        )
    )


if __name__ == "__main__":
    main()
