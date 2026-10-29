"""Today page — the default landing of the NQ Cockpit.

Progressive disclosure: four visible blocks (status strip, plain-language read,
chart + levels, watch next) and five collapsed expanders for the full detail.

This module also keeps the historical entry points used by the rest of the
application and the test-suite: ``render_cockpit`` (alias of the Today page)
and the four cached loaders.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.config import AppConfig, load_config
from nqcockpit.macro.news_radar import (
    MacroNewsRadar,
    NewsWireReport,
    fetch_live_news_wire,
    fetch_macro_news_radar,
)
from nqcockpit.profile.engine import build_day_profile
from nqcockpit.profile.models import DayProfile
from nqcockpit.ui import sections
from nqcockpit.ui.chart import load_latest_session_bars
from nqcockpit.ui.i18n import label, t
from nqcockpit.ui.sections import (
    _radar_card_html,
    _wire_item_html,
    inject_ui_css,
    render_chart_section,
    render_cot,
    render_header_strip,
    render_health,
    render_levels_table,
    render_news_wire,
    render_radar_cards,
    render_scenarios,
    render_today_read,
    render_watch_next,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached loaders (kept for backwards compatibility with the historical page)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60, show_spinner=False)
def load_day_profile_cached(db_path_str: str) -> DayProfile:
    """Build the session profile with a 60 s cache (keyed by database path)."""
    from nqcockpit.data.db import apply_migrations, get_db_connection

    cfg = load_config()
    conn = get_db_connection(Path(db_path_str))
    try:
        apply_migrations(conn)
        return build_day_profile(
            conn=conn, config=cfg, now_utc=datetime.now(timezone.utc)
        )
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def load_macro_radar_cached() -> MacroNewsRadar:
    """Macro radar cached for 60 s: no network call on every UI click."""
    return fetch_macro_news_radar()


@st.cache_data(ttl=60, show_spinner=False)
def load_news_wire_cached(max_items_per_source: int = 4) -> NewsWireReport:
    """Live news wire cached for 60 s: no RSS call on every UI click."""
    return fetch_live_news_wire(max_items_per_source=max_items_per_source)


@st.cache_data(ttl=60, show_spinner=False)
def load_chart_bars_cached(db_path_str: str) -> tuple[list, datetime | None]:
    """Latest 1m NQ=F bars from local SQLite + timestamp of the last bar."""
    path = Path(db_path_str)
    if not path.exists():
        return [], None
    from nqcockpit.data.db import get_db_connection

    conn = get_db_connection(path)
    try:
        return load_latest_session_bars(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Data assembly + rendering
# ---------------------------------------------------------------------------


@dataclass
class TodayData:
    """Everything the Today page displays, loaded once per render."""

    profile: DayProfile
    config: AppConfig
    now_utc: datetime
    radar: MacroNewsRadar | None = None
    wire: NewsWireReport | None = None
    session_bars: list = field(default_factory=list)
    last_bar_utc: datetime | None = None


def load_today_data() -> TodayData:
    """Load the Today page data, degrading each optional feed independently."""
    config = load_config()
    db_path = Path(config.data.db_path)
    profile = load_day_profile_cached(str(db_path))

    radar: MacroNewsRadar | None
    try:
        radar = load_macro_radar_cached()
    except Exception as exc:  # noqa: BLE001 - a missing feed never breaks the page
        log.warning("Macro radar unavailable on Today: %s", exc)
        radar = None

    wire: NewsWireReport | None
    try:
        wire = load_news_wire_cached(max_items_per_source=4)
    except Exception as exc:  # noqa: BLE001
        log.warning("News wire unavailable on Today: %s", exc)
        wire = None

    try:
        session_bars, last_bar_utc = load_chart_bars_cached(str(db_path))
    except Exception as exc:  # noqa: BLE001
        log.warning("Chart bars unavailable on Today: %s", exc)
        session_bars, last_bar_utc = [], None

    return TodayData(
        profile=profile,
        config=config,
        now_utc=datetime.now(timezone.utc),
        radar=radar,
        wire=wire,
        session_bars=session_bars,
        last_bar_utc=last_bar_utc,
    )


def render_today(data: TodayData | None = None) -> None:
    """Render the Today page (four visible blocks, then collapsed detail)."""
    if data is None:
        with st.spinner(t("Chargement du cockpit…", "Loading the cockpit…")):
            data = load_today_data()

    inject_ui_css()

    # Block 1 — header strip.
    render_header_strip(data.profile, data.config, data.now_utc)

    # Block 2 — one plain-language read card.
    render_today_read(data.profile)

    # Block 3 — hero: existing chart next to the compact levels table.
    st.markdown(
        f'<div class="section-title">{label("ui.today.hero_title")}</div>',
        unsafe_allow_html=True,
    )
    chart_col, levels_col = st.columns([1.7, 1], gap="medium")
    with chart_col:
        render_chart_section(
            data.profile, data.session_bars, data.last_bar_utc
        )
    with levels_col:
        render_levels_table(data.profile)

    # Block 4 — watch next: next high-impact event + top three drivers.
    render_watch_next(data.profile, data.radar)

    # Everything else — collapsed, plain-English expanders.
    with st.expander(label("ui.expander.radar"), expanded=False):
        if data.radar is not None:
            render_radar_cards(data.radar.as_list())
        else:
            st.warning(label("ui.today.no_drivers"))
    with st.expander(label("ui.expander.news"), expanded=False):
        render_news_wire(data.wire)
    with st.expander(label("ui.expander.cot"), expanded=False):
        render_cot(data.profile.cot)
    with st.expander(label("ui.expander.scenarios"), expanded=False):
        render_scenarios(data.profile)
    with st.expander(label("ui.expander.health"), expanded=False):
        render_health(data.profile)

    st.caption(
        t(
            "Aide à la décision non-directionnelle · aucune exécution d'ordre.",
            "Non-directional decision support · no order execution.",
        )
    )


def render_cockpit() -> None:
    """Historical entry point — the cockpit is now the Today page."""
    try:
        st.set_page_config(
            page_title=t("NQ Cockpit · Aujourd'hui", "NQ Cockpit · Today"),
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except StreamlitAPIException:
        pass
    render_today()


# Backwards-compatible helper aliases (used by older tests / callers).
_render_radar_card_html = _radar_card_html
_render_wire_item_html = _wire_item_html

__all__ = [
    "TodayData",
    "load_chart_bars_cached",
    "load_day_profile_cached",
    "load_macro_radar_cached",
    "load_news_wire_cached",
    "load_today_data",
    "render_cockpit",
    "render_today",
    "sections",
]


if __name__ == "__main__":
    render_cockpit()
