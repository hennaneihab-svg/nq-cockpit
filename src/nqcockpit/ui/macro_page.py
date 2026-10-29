"""Macro & News page — the six drivers, the live wire and CFTC positioning."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

from nqcockpit.config import load_config
from nqcockpit.macro.news_radar import MacroNewsRadar, NewsWireReport
from nqcockpit.profile.models import DayProfile
from nqcockpit.ui import sections
from nqcockpit.ui.cockpit_page import (
    load_day_profile_cached,
    load_macro_radar_cached,
    load_news_wire_cached,
)
from nqcockpit.ui.i18n import label

log = logging.getLogger(__name__)


@dataclass
class MacroData:
    """Data displayed by the Macro & News page."""

    radar: MacroNewsRadar | None = None
    wire: NewsWireReport | None = None
    profile: DayProfile | None = field(default=None)


def load_macro_data() -> MacroData:
    """Load radar, wire and the CFTC block from existing cached engines."""
    radar: MacroNewsRadar | None
    try:
        radar = load_macro_radar_cached()
    except Exception as exc:  # noqa: BLE001
        log.warning("Macro radar unavailable: %s", exc)
        radar = None

    wire: NewsWireReport | None
    try:
        wire = load_news_wire_cached(max_items_per_source=4)
    except Exception as exc:  # noqa: BLE001
        log.warning("News wire unavailable: %s", exc)
        wire = None

    profile: DayProfile | None
    try:
        config = load_config()
        profile = load_day_profile_cached(str(Path(config.data.db_path)))
    except Exception as exc:  # noqa: BLE001
        log.warning("Profile unavailable on Macro page: %s", exc)
        profile = None

    return MacroData(radar=radar, wire=wire, profile=profile)


def render_macro_page(data: MacroData | None = None) -> None:
    """Render the Macro & News page."""
    if data is None:
        data = load_macro_data()

    sections.inject_ui_css()
    sections.render_page_heading("ui.macro.title", "ui.macro.desc")

    st.markdown(
        f'<div class="section-title">{label("ui.macro.drivers_title")}</div>',
        unsafe_allow_html=True,
    )
    if data.radar is not None:
        sections.render_radar_cards(data.radar.as_list())
    else:
        st.warning(label("ui.today.no_drivers"))

    st.markdown(
        f'<div class="section-title">{label("ui.macro.news_title")}</div>',
        unsafe_allow_html=True,
    )
    sections.render_news_wire(data.wire)

    sections.render_cot(data.profile.cot if data.profile is not None else None)

    if data.profile is not None:
        with st.expander(label("ui.expander.health"), expanded=False):
            sections.render_health(data.profile)


if __name__ == "__main__":
    render_macro_page()
