"""Terminal page — one non-scrolling trading screen.

Layout (1920x1080, no page-level scrolling):

- top bar: spot, one data-status chip, Algiers kill-zone state, next event and
  the Brief button that opens the pre-session briefing in a dialog;
- main area: the TradingView advanced chart (symbol picker + key-level pills)
  on the left, and Radar / News / Events / Coach tabs on the right;
- bottom strip: trades today, kill-zone state and gamma regime.

Every number comes from an existing engine/DB field: this module only lays out
data already produced by the application. No calculation is added here.
"""

from __future__ import annotations

import logging
from html import escape

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.discipline.engine import evaluate_session_state
from nqcockpit.discipline.models import DisciplineSessionState
from nqcockpit.events.health import (
    load_latest_event_source_health,
    render_source_health,
    source_health_chip_html,
)
from nqcockpit.journal.store import load_trades
from nqcockpit.profile.models import DayProfile, NoTradeFlagCode
from nqcockpit.ui import sections, tv_widgets
from nqcockpit.ui.briefing_page import render_briefing_page
from nqcockpit.ui.coaching_page import render_coaching_summary
from nqcockpit.ui.cockpit_page import TodayData, load_today_data
from nqcockpit.ui.components import badge_html
from nqcockpit.ui.db import get_ui_db
from nqcockpit.ui.i18n import (
    get_lang,
    label,
    normalize_status_code,
    status_label,
    t,
    tr_text,
)

log = logging.getLogger(__name__)

SYMBOL_STATE_KEY = "terminal_chart_symbol"
# Height budget (1920x1080, single screen). The block container now clears the
# fixed Streamlit header (3.75rem) with 4rem of top padding (+57.6px versus the
# old 0.4rem). The chart (640 -> 600) and the right panel (690 -> 630) absorb
# that padding, so the terminal still fits on one screen without page-level
# scrolling.
CHART_HEIGHT = 600
RIGHT_PANEL_HEIGHT = 630

TERMINAL_CSS = """
<style>
.block-container {
    padding-top: 4rem !important;
    padding-bottom: 0.4rem !important;
    max-width: 99% !important;
}
.terminal-topbar {
    display: flex;
    flex-wrap: nowrap;
    gap: 18px;
    align-items: stretch;
    background: #111827;
    border: 1px solid #1F2937;
    border-radius: 8px;
    padding: 8px 14px;
    min-height: 64px;
    overflow: hidden;
}
.terminal-topbar .tb-item {
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.terminal-topbar .tb-item.tb-wide {
    flex: 1 1 0;
}
.terminal-topbar .tb-label {
    font-size: 0.68rem;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
}
.terminal-topbar .tb-value {
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 1.05rem;
    font-weight: 700;
    color: #F8FAFC;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.terminal-topbar .tb-meta {
    font-size: 0.72rem;
    color: #94A3B8;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.terminal-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin: 4px 0;
}
.distance-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 2px 0 6px 0;
}
.distance-chip {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    border: 1px solid #1F2937;
    background: #0F172A;
    border-radius: 6px;
    padding: 3px 10px;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 0.76rem;
    color: #E2E8F0;
    white-space: nowrap;
}
.distance-chip b {
    color: #94A3B8;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.terminal-bottom {
    display: flex;
    flex-wrap: nowrap;
    gap: 20px;
    align-items: center;
    background: #111827;
    border: 1px solid #1F2937;
    border-radius: 8px;
    padding: 7px 14px;
    margin-top: 6px;
    font-size: 0.8rem;
    color: #E2E8F0;
    white-space: nowrap;
    overflow: hidden;
}
.terminal-bottom b {
    color: #94A3B8;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-right: 6px;
}
.terminal-bottom .tb-value {
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    color: #F8FAFC;
    font-weight: 700;
}
.event-row {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    padding: 6px 0;
    border-bottom: 1px solid #1F2937;
    font-size: 0.82rem;
}
.event-row:last-child {
    border-bottom: none;
}
.event-row .event-name {
    color: #E2E8F0;
    font-weight: 600;
    overflow-wrap: anywhere;
}
.event-row .event-meta {
    color: #94A3B8;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    white-space: nowrap;
}
.terminal-empty {
    color: #94A3B8;
    font-size: 0.84rem;
    padding: 8px 0;
}
</style>
"""


# ---------------------------------------------------------------------------
# Data status (one chip for the whole terminal)
# ---------------------------------------------------------------------------


def terminal_status_code(
    profile: DayProfile | None, data: TodayData | None = None
) -> str:
    """OK / DEGRADED / STALE / NO_DATA from fields the profile already carries."""
    if profile is None or profile.spot_nq is None:
        return "NO_DATA"
    statuses = [
        normalize_status_code(health.status)
        for health in (profile.component_statuses or {}).values()
    ]
    if statuses and all(code == "NO_DATA" for code in statuses):
        return "NO_DATA"
    stale_flag = any(
        getattr(flag.code, "value", flag.code) == NoTradeFlagCode.STALE_DATA.value
        and flag.triggered
        for flag in (profile.no_trade.all_flags if profile.no_trade else [])
    )
    if stale_flag or any(code == "STALE" for code in statuses):
        return "STALE"
    missing_feed = data is not None and (
        data.radar is None or data.wire is None or not data.session_bars
    )
    if (
        missing_feed
        or normalize_status_code(profile.status) != "OK"
        or any(code in ("DEGRADED", "NO_DATA") for code in statuses)
    ):
        return "DEGRADED"
    return "OK"


def degraded_feeds(profile: DayProfile | None, data: TodayData | None = None) -> list[str]:
    """Human names of the feeds the status chip calls out (never hidden)."""
    feeds: list[str] = []
    if profile is not None:
        for health in (profile.component_statuses or {}).values():
            if normalize_status_code(health.status) != "OK":
                feeds.append(
                    f"{label(health.name, default=health.name)}: "
                    f"{status_label(health.status)}"
                )
    if data is not None:
        if data.radar is None:
            feeds.append(label("ui.terminal.feed_radar"))
        if data.wire is None:
            feeds.append(label("ui.terminal.feed_news"))
        if not data.session_bars:
            feeds.append(label("ui.terminal.feed_chart"))
    return feeds


def _status_tooltip(code: str, feeds: list[str]) -> str:
    if code == "NO_DATA":
        return label("ui.terminal.status_tooltip_no_data")
    if not feeds:
        return label("ui.terminal.status_tooltip_ok")
    joined = "; ".join(feeds)
    if code == "STALE":
        return label("ui.terminal.status_tooltip_stale", feeds=joined)
    return label("ui.terminal.status_tooltip_degraded", feeds=joined)


def _status_chip_html(code: str, feeds: list[str]) -> str:
    css = {
        "OK": "chip-ok",
        "DEGRADED": "chip-degraded",
        "STALE": "chip-degraded",
        "NO_DATA": "chip-error",
    }.get(code, "chip-degraded")
    tooltip = escape(_status_tooltip(code, feeds), quote=True)
    return (
        f'<span class="{css}" title="{tooltip}" aria-label="{tooltip}">'
        f"<b>{escape(status_label(code))}</b></span>"
    )


# ---------------------------------------------------------------------------
# Top bar
# ---------------------------------------------------------------------------


def render_top_bar(data: TodayData, source_health: list | None = None) -> bool:
    """One row: spot, status chip, kill-zone timer, next event, sources, Brief.

    Returns True on the run where the Brief button was clicked, so the dialog
    opens exactly once (dismissing it requires no extra session state).
    """
    profile = data.profile
    code = terminal_status_code(profile, data)
    feeds = degraded_feeds(profile, data)
    spot_text = (
        f"{profile.spot_nq:,.2f}"
        if profile.spot_nq is not None
        else status_label("NO_DATA")
    )
    window_text, _ = sections.trading_window_state(data.config, data.now_utc)
    algiers_time = data.now_utc.astimezone(sections.TZ_ALGIERS).strftime("%H:%M")
    event = tr_text(profile.next_tier1_event or "") or label("ui.today.no_event")
    countdown = tr_text(profile.next_tier1_countdown or "")
    risk = label(f"risk.{profile.event_risk_level}", profile.event_risk_level)
    event_meta = " · ".join(part for part in (countdown, risk) if part)

    strip = f"""
    <div class="terminal-topbar">
        <div class="tb-item">
            <div class="tb-label">{escape(label("ui.today.spot"))}</div>
            <div class="tb-value">{escape(spot_text)}</div>
            <div class="tb-meta">{escape(label("ui.today.algiers_time", time=algiers_time))}</div>
        </div>
        <div class="tb-item">
            <div class="tb-label">{escape(label("ui.today.freshness"))}</div>
            <div class="tb-value">{_status_chip_html(code, feeds)}</div>
            <div class="tb-meta">{escape(status_label(code))}</div>
        </div>
        <div class="tb-item tb-wide">
            <div class="tb-label">{escape(label("ui.today.window"))}</div>
            <div class="tb-value">{escape(window_text)}</div>
            <div class="tb-meta">{escape(label("ui.terminal.kill_zone_timer"))}</div>
        </div>
        <div class="tb-item tb-wide">
            <div class="tb-label">{escape(label("ui.today.next_event"))}</div>
            <div class="tb-value">{escape(event)}</div>
            <div class="tb-meta">{escape(event_meta)}</div>
        </div>
        <div class="tb-item">
            <div class="tb-label">{escape(label("ui.terminal.sources_health"))}</div>
            <div class="tb-value">{source_health_chip_html(source_health or [])}</div>
            <div class="tb-meta">{escape(t("sources événements", "event sources"))}</div>
        </div>
    </div>
    """
    bar_col, brief_col = st.columns([8.6, 1.4], gap="small", vertical_alignment="center")
    with bar_col:
        st.markdown(strip, unsafe_allow_html=True)
    with brief_col:
        clicked = st.button(
            label("ui.terminal.brief"),
            key="terminal_brief_button",
            use_container_width=True,
        )
    return bool(clicked)


def _render_brief_body() -> None:
    """Existing briefing page, embedded and read-only inside the dialog."""
    with st.container(height=560):
        render_briefing_page(embedded=True, show_title=False)


def maybe_render_brief_dialog(open_brief: bool) -> None:
    """Open the briefing in a dialog; fall back to an expander when unavailable."""
    if not open_brief:
        return
    title = label("ui.terminal.brief_title")
    if hasattr(st, "dialog"):
        try:
            st.dialog(title)(_render_brief_body)()
            return
        except StreamlitAPIException as exc:  # dialog unsupported in this context
            log.warning("Brief dialog unavailable, using expander: %s", exc)
        except Exception as exc:  # noqa: BLE001 - never break the terminal
            log.warning("Brief dialog failed, using expander: %s", exc)
    with st.expander(title, expanded=True):
        _render_brief_body()


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------


def render_distance_chips(profile: DayProfile | None) -> None:
    """Slim row under the chart: level value and signed distance from spot."""
    lines = sections.compact_levels(profile)
    chips = []
    for line in lines:
        value = (
            f"{line.value:,.2f}" if line.value is not None else status_label("NO_DATA")
        )
        distance = (
            f"{line.distance:+,.1f} pts"
            if line.distance is not None
            else status_label("NO_DATA")
        )
        chips.append(
            '<span class="distance-chip">'
            f"<b>{escape(label(f'ui.term.{line.term}'))}</b>"
            f"<span>{escape(value)}</span>"
            f"<span>{escape(distance)}</span></span>"
        )
    st.markdown(
        f'<div class="distance-chips">{"".join(chips)}</div>',
        unsafe_allow_html=True,
    )


def render_symbol_selector() -> str:
    """Compact TradingView symbol picker; defaults to the NQ proxy."""
    options = list(tv_widgets.NQ_SYMBOL_OPTIONS)
    default = tv_widgets.DEFAULT_NQ_SYMBOL
    stored = st.session_state.get(SYMBOL_STATE_KEY)
    if stored not in options:
        st.session_state[SYMBOL_STATE_KEY] = default
    symbol = st.selectbox(
        label("ui.terminal.symbol"),
        options=options,
        key=SYMBOL_STATE_KEY,
    )
    return str(symbol)


def render_chart_column(data: TodayData) -> None:
    """TradingView advanced chart plus the key-level pills, left column."""
    symbol = render_symbol_selector()
    timezone = getattr(data.config.timezones, "display", None) or "Africa/Algiers"
    tv_widgets.render_widget(
        tv_widgets.advanced_chart_html(
            symbol,
            locale=get_lang().lower(),
            timezone=timezone,
            height=CHART_HEIGHT,
        ),
        CHART_HEIGHT,
    )
    render_distance_chips(data.profile)


def render_event_panel(profile: DayProfile | None) -> None:
    """Next high-impact event + event risk, from existing profile fields only."""
    if profile is None:
        st.markdown(
            f'<div class="terminal-empty">{escape(label("ui.terminal.events_empty"))}'
            "</div>",
            unsafe_allow_html=True,
        )
        return
    event = tr_text(profile.next_tier1_event or "") or label("ui.today.no_event")
    countdown = tr_text(profile.next_tier1_countdown or "")
    risk = label(f"risk.{profile.event_risk_level}", profile.event_risk_level)
    reason = tr_text(profile.event_risk_reason or "")
    health = (profile.component_statuses or {}).get("events")
    component = (
        f"{escape(label(health.name, default=health.name))}: "
        f"{badge_html(health.status)}"
        if health is not None
        else f"{escape(label('ui.terminal.feed_events'))}: {badge_html('NO_DATA')}"
    )
    rows = [
        (
            label("ui.terminal.events_next"),
            f"{event} · {countdown}" if countdown else event,
        ),
        (label("ui.terminal.events_risk"), risk),
        (label("ui.terminal.events_reason"), reason or label("status.NO_DATA")),
    ]
    body = "".join(
        '<div class="event-row">'
        f'<span class="event-name">{escape(name)}</span>'
        f'<span class="event-meta">{escape(value)}</span>'
        "</div>"
        for name, value in rows
    )
    st.markdown(body, unsafe_allow_html=True)
    st.markdown(component, unsafe_allow_html=True)
    st.caption(label("ui.terminal.events_note"))


def render_side_panel(data: TodayData) -> None:
    """Radar | News | Events | Coach, each in a fixed-height scroll container."""
    tabs = st.tabs(
        [
            label("ui.terminal.tab_radar"),
            label("ui.terminal.tab_news"),
            label("ui.terminal.tab_events"),
            label("ui.terminal.tab_coach"),
        ]
    )
    with tabs[0]:
        with st.container(height=RIGHT_PANEL_HEIGHT, border=False):
            if data.radar is not None:
                sections.render_radar_cards(data.radar.as_list())
            else:
                st.info(label("ui.terminal.no_radar"))
    with tabs[1]:
        with st.container(height=RIGHT_PANEL_HEIGHT, border=False):
            sections.render_news_wire(data.wire)
    with tabs[2]:
        with st.container(height=RIGHT_PANEL_HEIGHT, border=False):
            render_event_panel(data.profile)
    with tabs[3]:
        with st.container(height=RIGHT_PANEL_HEIGHT, border=False):
            render_coaching_summary()


# ---------------------------------------------------------------------------
# Bottom strip
# ---------------------------------------------------------------------------


def session_state_snapshot(data: TodayData) -> DisciplineSessionState | None:
    """Existing discipline state (trades today, active kill zone), read-only."""
    try:
        conn = get_ui_db(str(data.config.data.db_path))
        trades = load_trades(conn)
        return evaluate_session_state(trades, data.now_utc, data.config)
    except Exception as exc:  # noqa: BLE001 - a missing journal never breaks the terminal
        log.warning("Discipline state unavailable on Terminal: %s", exc)
        return None


def render_bottom_strip(data: TodayData) -> None:
    """One row: trades today X/2, kill-zone state and gamma regime label."""
    state = session_state_snapshot(data)
    if state is None:
        trades_text = status_label("NO_DATA")
        kill_text = status_label("NO_DATA")
    else:
        trades_text = label(
            "ui.terminal.trades_today",
            taken=state.trades_taken_today,
            max=state.max_trades_allowed,
        )
        if state.current_window_name:
            window = next(
                (
                    win
                    for win in data.config.trading_windows_algiers
                    if win.name == state.current_window_name
                ),
                None,
            )
            kill_text = (
                label(
                    "ui.terminal.kill_zone_active",
                    name=window.name,
                    start=window.start,
                    end=window.end,
                )
                if window is not None
                else state.current_window_name
            )
        else:
            kill_text = label("ui.terminal.kill_zone_outside")
    gamma_text = label(
        f"gamma.{data.profile.gamma_regime}",
        default=tr_text(data.profile.gamma_regime),
    )
    st.markdown(
        f"""
        <div class="terminal-bottom">
            <span><b>{escape(label("ui.terminal.trades_label"))}</b>
                <span class="tb-value">{escape(trades_text)}</span></span>
            <span><b>{escape(label("ui.terminal.kill_zone_label"))}</b>
                <span class="tb-value">{escape(kill_text)}</span></span>
            <span><b>{escape(label("ui.terminal.gamma_label"))}</b>
                <span class="tb-value">{escape(gamma_text)}</span></span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render_terminal(data: TodayData | None = None) -> None:
    """Render the whole Terminal page; every feed degrades independently."""
    if data is None:
        with st.spinner(t("Chargement du terminal…", "Loading the terminal…")):
            data = load_today_data()

    sections.inject_ui_css()
    st.markdown(TERMINAL_CSS, unsafe_allow_html=True)

    source_health = load_latest_event_source_health()
    brief_clicked = render_top_bar(data, source_health)
    maybe_render_brief_dialog(brief_clicked)

    if source_health:
        with st.expander(label("ui.terminal.sources_health"), expanded=False):
            render_source_health(source_health)

    chart_col, panel_col = st.columns([7, 3], gap="medium")
    with chart_col:
        render_chart_column(data)
    with panel_col:
        render_side_panel(data)

    render_bottom_strip(data)


__all__ = [
    "SYMBOL_STATE_KEY",
    "degraded_feeds",
    "maybe_render_brief_dialog",
    "render_bottom_strip",
    "render_chart_column",
    "render_distance_chips",
    "render_event_panel",
    "render_side_panel",
    "render_symbol_selector",
    "render_terminal",
    "render_top_bar",
    "session_state_snapshot",
    "terminal_status_code",
]
