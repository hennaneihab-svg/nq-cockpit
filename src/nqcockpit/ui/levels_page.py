"""Levels & Chart page — exact gamma levels, the session chart and scenarios."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from nqcockpit.config import AppConfig, load_config
from nqcockpit.profile.engine import export_levels_to_csv
from nqcockpit.profile.models import DayProfile
from nqcockpit.ui import sections
from nqcockpit.ui.cockpit_page import (
    load_chart_bars_cached,
    load_day_profile_cached,
)
from nqcockpit.ui.i18n import label, t

log = logging.getLogger(__name__)


@dataclass
class LevelsData:
    """Data displayed by the Levels & Chart page."""

    profile: DayProfile
    config: AppConfig
    now_utc: datetime
    session_bars: list = field(default_factory=list)
    last_bar_utc: datetime | None = None


def load_levels_data() -> LevelsData:
    """Load the profile and the latest local bars (no new calculation)."""
    config = load_config()
    db_path = Path(config.data.db_path)
    profile = load_day_profile_cached(str(db_path))
    try:
        session_bars, last_bar_utc = load_chart_bars_cached(str(db_path))
    except Exception as exc:  # noqa: BLE001 - empty chart is a valid state
        log.warning("Chart bars unavailable on Levels: %s", exc)
        session_bars, last_bar_utc = [], None
    return LevelsData(
        profile=profile,
        config=config,
        now_utc=datetime.now(timezone.utc),
        session_bars=session_bars,
        last_bar_utc=last_bar_utc,
    )


def render_levels_page(data: LevelsData | None = None) -> None:
    """Render the Levels & Chart page."""
    if data is None:
        with st.spinner(t("Chargement des niveaux…", "Loading levels…")):
            data = load_levels_data()

    sections.inject_ui_css()
    sections.render_page_heading("ui.levels.title", "ui.levels.desc")

    chart_col, levels_col = st.columns([1.7, 1], gap="medium")
    with chart_col:
        sections.render_chart_section(
            data.profile, data.session_bars, data.last_bar_utc
        )
    with levels_col:
        sections.render_levels_table(data.profile)

    sections.render_full_levels_table(data.profile)

    if data.profile.key_levels:
        csv_text = export_levels_to_csv(
            data.profile.key_levels,
            now_utc=data.now_utc,
            snapshot_timestamp_utc=data.profile.snapshot_timestamp_utc,
            snapshot_age_minutes=data.profile.snapshot_age_minutes,
            basis_ndx_nq=data.profile.basis_ndx_nq,
        )
        st.download_button(
            label=f"{label('ui.levels.export')} ↓",
            data=csv_text,
            file_name=f"nq_levels_{data.profile.target_date}.csv",
            mime="text/csv",
            use_container_width=True,
            help=label("ui.hint.download"),
        )

    with st.expander(label("ui.levels.scenarios"), expanded=False):
        sections.render_scenarios(data.profile)

    with st.expander(label("ui.expander.health"), expanded=False):
        sections.render_health(data.profile)


if __name__ == "__main__":
    render_levels_page()
