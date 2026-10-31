"""Shared, presentation-only building blocks for the redesigned cockpit UI.

This module owns the visual hierarchy (cards, status strips, levels table,
radar/news cards, help tooltips) so the pages stay short and consistent.

Hard rules kept here:
- no business calculation: every number comes from an existing engine/DB field;
- colour is used for status only (green OK / amber degraded / red no data);
- non-clickable cards never look like buttons; clickable elements say so;
- two body font sizes only (body + small meta), headings are separate.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

from nqcockpit.config import AppConfig
from nqcockpit.macro.news_radar import (
    MacroNewsRadar,
    MacroRadarCard,
    NewsWireItem,
    NewsWireReport,
)
from nqcockpit.profile.models import DayProfile
from nqcockpit.time import is_in_trading_window
from nqcockpit.ui.chart import build_session_chart
from nqcockpit.ui.components import badge_html, health_badge_html
from nqcockpit.ui.i18n import (
    label,
    normalize_status_code,
    status_label,
    t,
    tr_text,
)

log = logging.getLogger(__name__)

TZ_ALGIERS = ZoneInfo("Africa/Algiers")

UI_CSS = """
:root {
    --bg-canvas: #0B1220;
    --bg-surface: #111827;
    --border-subtle: #1F2937;
    --border-strong: #334155;
    --text-primary: #E2E8F0;
    --text-secondary: #94A3B8;
    --status-ok-text: #10B981;
    --status-ok-border: rgba(16, 185, 129, 0.35);
    --status-ok-bg: rgba(16, 185, 129, 0.10);
    --status-deg-text: #F59E0B;
    --status-deg-border: rgba(245, 158, 11, 0.35);
    --status-deg-bg: rgba(245, 158, 11, 0.10);
    --status-error-text: #EF4444;
    --status-error-border: rgba(239, 68, 68, 0.35);
    --status-error-bg: rgba(239, 68, 68, 0.10);
    --font-body: 0.95rem;
    --font-small: 0.80rem;
    --space-1: 6px;
    --space-2: 10px;
    --space-3: 16px;
    --space-4: 24px;
}

.stApp {
    background-color: var(--bg-canvas);
    color: var(--text-primary);
}

/* Clear Streamlit's fixed header (3.75rem tall, same budget as app.py). */
.block-container {
    padding-top: 4rem;
    padding-bottom: 2rem;
    max-width: 98%;
}

/* Two body sizes only: body and small meta. Headings are separate. */
.card,
.read-card,
.strip-item,
.news-card,
.news-wire-card,
.watch-card {
    font-size: var(--font-body);
    line-height: 1.5;
}

.page-heading {
    font-size: 1.20rem;
    font-weight: 700;
    margin: 0 0 var(--space-1) 0;
    color: var(--text-primary);
}

.page-desc {
    font-size: var(--font-small);
    color: var(--text-secondary);
    margin: 0 0 var(--space-3) 0;
}

/* Sidebar navigation heading */
.nav-title {
    font-size: var(--font-small);
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: var(--space-2) 0 var(--space-1) 0;
}

.section-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 var(--space-2) 0;
}

.card {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: var(--space-3);
    margin-bottom: var(--space-3);
}

/* Status strip: four cells, wraps on narrow windows. */
.strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-3);
    align-items: start;
}

.strip-item {
    min-width: 0;
    overflow-wrap: anywhere;
}

.strip-label {
    font-size: var(--font-small);
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: var(--space-1);
}

.strip-value {
    font-size: var(--font-body);
    font-weight: 700;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    overflow-wrap: anywhere;
}

.strip-meta {
    font-size: var(--font-small);
    color: var(--text-secondary);
    margin-top: var(--space-1);
}

.read-card {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: var(--space-3);
    margin-bottom: var(--space-3);
}

.read-card p {
    margin: 0 0 var(--space-1) 0;
    font-size: var(--font-body);
}

/* Help tooltip on technical terms: a small circled question mark. */
.term {
    white-space: normal;
    overflow-wrap: anywhere;
}

.help-q {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    margin-left: 4px;
    border: 1px solid var(--border-strong);
    border-radius: 50%;
    color: var(--text-secondary);
    font-size: 0.62rem;
    font-weight: 700;
    line-height: 1;
    cursor: help;
    vertical-align: super;
}

.help-q:hover,
.help-q:focus {
    color: var(--text-primary);
    border-color: var(--text-secondary);
    outline: none;
}

/* Compact levels table */
.levels-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--font-body);
}

.levels-table th {
    text-align: left;
    font-size: var(--font-small);
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: var(--space-1) var(--space-2) var(--space-2) 0;
    border-bottom: 1px solid var(--border-subtle);
}

.levels-table td {
    padding: var(--space-2) var(--space-2) var(--space-2) 0;
    border-bottom: 1px solid var(--border-subtle);
    vertical-align: top;
    overflow-wrap: anywhere;
}

.levels-table td.num {
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    white-space: nowrap;
}

.table-scroll {
    overflow-x: auto;
}

/* Buttons keep a neutral, clickable look: colour is reserved for status. */
.stButton > button,
.stDownloadButton > button {
    border-radius: 6px;
    font-size: var(--font-body);
    border: 1px solid var(--border-strong);
    background-color: transparent;
    color: var(--text-primary);
}

.stButton > button[kind="primary"] {
    background-color: var(--bg-surface);
    border-color: var(--text-secondary);
    color: var(--text-primary);
    font-weight: 700;
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    border-color: var(--text-secondary);
    color: #F8FAFC;
}

/* Expander headers are clickable: show the hint text on a normal body size. */
div[data-testid="stExpander"] summary {
    font-size: var(--font-body);
    color: var(--text-primary);
    cursor: pointer;
}

/* Watch next */
.watch-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: var(--space-3);
}

.watch-event {
    font-size: var(--font-body);
    font-weight: 700;
    margin-bottom: var(--space-1);
    overflow-wrap: anywhere;
}

.driver-row {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    align-items: flex-start;
    padding: var(--space-1) 0;
    border-bottom: 1px solid var(--border-subtle);
    font-size: var(--font-body);
}

.driver-row:last-child {
    border-bottom: none;
}

/* Label keeps a real column width: never squeezed to one character per line. */
.driver-name {
    flex: 0 1 auto;
    min-width: 12rem;
    color: var(--text-secondary);
    word-break: normal;
    overflow-wrap: normal;
    white-space: normal;
}

/* The earnings list wraps normally instead of forcing its own width. */
.driver-value {
    flex: 1 1 auto;
    min-width: 0;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    text-align: right;
    word-break: normal;
    overflow-wrap: anywhere;
    white-space: normal;
}

/* Macro radar: fluid grid, no fixed columns, no hover button look. */
.radar-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: var(--space-3);
    align-items: stretch;
    margin-bottom: var(--space-3);
}

.news-card {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-width: 0;
    overflow-wrap: anywhere;
}

.news-card.degraded {
    border-color: var(--status-deg-border);
}

.news-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: var(--font-small);
    font-weight: 700;
    white-space: nowrap;
}

.pill-ok {
    background: var(--status-ok-bg);
    border: 1px solid var(--status-ok-border);
    color: var(--status-ok-text);
}

.pill-deg {
    background: var(--status-deg-bg);
    border: 1px solid var(--status-deg-border);
    color: var(--status-deg-text);
}

.live-dot,
.deg-dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
}

.live-dot {
    background-color: var(--status-ok-text);
}

.deg-dot {
    background-color: var(--status-deg-text);
}

.news-card-header {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    align-items: flex-start;
    margin-bottom: var(--space-2);
}

.news-card-title {
    font-size: var(--font-small);
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    overflow-wrap: anywhere;
}

.news-kpi {
    font-size: var(--font-body);
    font-weight: 700;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    margin-bottom: var(--space-1);
    overflow-wrap: anywhere;
}

.news-desc,
.news-footer {
    font-size: var(--font-small);
    color: var(--text-secondary);
    overflow-wrap: anywhere;
}

.news-footer {
    border-top: 1px solid var(--border-subtle);
    padding-top: var(--space-1);
    margin-top: var(--space-2);
    line-height: 1.5;
}

.news-footer b {
    color: var(--text-primary);
    font-weight: 600;
}

.news-alert {
    margin-top: var(--space-1);
    padding: 4px 6px;
    border-radius: 4px;
    background: var(--status-deg-bg);
    border: 1px solid var(--status-deg-border);
    color: var(--status-deg-text);
    font-size: var(--font-small);
    overflow-wrap: anywhere;
}

/* News wire: one column, links clearly clickable. */
.news-wire-card {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: var(--space-2) var(--space-3);
    margin-bottom: var(--space-2);
}

.wire-header {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--font-small);
    color: var(--text-secondary);
    margin-bottom: var(--space-1);
}

.wire-tag {
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 700;
}

.wire-title {
    font-size: var(--font-body);
    line-height: 1.4;
    overflow-wrap: anywhere;
}

.wire-title a {
    color: var(--text-primary);
    text-decoration: underline;
    text-underline-offset: 2px;
}

.wire-title a:hover,
.wire-title a:focus {
    color: #F8FAFC;
}

.wire-footer {
    font-size: var(--font-small);
    color: var(--text-secondary);
    margin-top: var(--space-1);
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    flex-wrap: wrap;
}

/* COT card */
.cot-card {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: var(--space-3);
    margin-bottom: var(--space-2);
}

.cot-line {
    font-size: var(--font-body);
    line-height: 1.6;
    overflow-wrap: anywhere;
}

/* Scenarios: neutral card, not a button. */
.scenario-box {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: var(--space-2) var(--space-3);
    margin-bottom: var(--space-2);
    font-size: var(--font-body);
    line-height: 1.5;
    overflow-wrap: anywhere;
}

/* Status chips (green OK / amber stale-degraded / red no data). */
.chip-ok,
.chip-degraded,
.chip-error {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: var(--font-small);
    font-weight: 700;
    margin-right: var(--space-1);
    margin-bottom: 4px;
}

.chip-ok {
    background: var(--status-ok-bg);
    border: 1px solid var(--status-ok-border);
    color: var(--status-ok-text);
}

.chip-degraded {
    background: var(--status-deg-bg);
    border: 1px solid var(--status-deg-border);
    color: var(--status-deg-text);
}

.chip-error {
    background: var(--status-error-bg);
    border: 1px solid var(--status-error-border);
    color: var(--status-error-text);
}

.chip-name {
    font-size: var(--font-small);
    font-weight: 600;
    margin-right: 4px;
}

.chip-reason {
    font-size: var(--font-small);
    color: var(--text-secondary);
    overflow-wrap: anywhere;
}

/* Source health: one source per line, with breathing room around each row. */
.health-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
}

.health-row {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-2);
    padding: var(--space-1) 0;
    border-bottom: 1px solid var(--border-subtle);
    line-height: 1.5;
}

.health-row:last-child {
    border-bottom: none;
}

.health-row .chip-ok,
.health-row .chip-degraded,
.health-row .chip-error {
    margin-right: 0;
    margin-bottom: 0;
}

.health-row .chip-name {
    font-weight: 700;
    margin-right: 0;
}

.health-row .chip-reason {
    flex: 1 1 auto;
    min-width: 0;
}

@media (max-width: 900px) {
    .strip,
    .watch-grid,
    .radar-grid {
        grid-template-columns: 1fr;
    }
}
"""


def _e(value: object) -> str:
    """Escape any dynamic value before it enters an HTML fragment."""
    return escape(str(value), quote=True)


def inject_ui_css() -> None:
    """Inject the shared stylesheet once per page render."""
    st.markdown(f"<style>{UI_CSS}</style>", unsafe_allow_html=True)


def render_page_heading(title_key: str, desc_key: str) -> None:
    """Plain page title + one-line description, same spacing everywhere."""
    st.markdown(
        f'<div class="page-heading">{_e(label(title_key))}</div>'
        f'<div class="page-desc">{_e(label(desc_key))}</div>',
        unsafe_allow_html=True,
    )


def help_term(term_key: str) -> str:
    """Term + small « ? » tooltip carrying a one-sentence plain explanation."""
    name = label(f"ui.term.{term_key}")
    explanation = label(f"ui.help.{term_key}")
    return (
        f'<span class="term">{_e(name)}'
        f'<span class="help-q" title="{_e(explanation)}" '
        f'aria-label="{_e(explanation)}" tabindex="0">?</span></span>'
    )


def freshness_code(profile: DayProfile | None) -> str:
    """Tri-state freshness from existing profile/component status fields only."""
    if profile is None:
        return "NO_DATA"
    statuses = [
        normalize_status_code(health.status)
        for health in (profile.component_statuses or {}).values()
    ]
    if profile.spot_nq is None:
        return "NO_DATA"
    if statuses and all(code == "NO_DATA" for code in statuses):
        return "NO_DATA"
    if normalize_status_code(profile.status) != "OK" or any(
        code in ("DEGRADED", "STALE", "NO_DATA") for code in statuses
    ):
        return "DEGRADED"
    return "OK"


def trading_window_state(
    config: AppConfig, now_utc: datetime
) -> tuple[str, bool]:
    """Current/next configured window in Algiers time (no hard-coded offset)."""
    now_algiers = now_utc.astimezone(TZ_ALGIERS)
    is_open, active_name = is_in_trading_window(
        now_algiers, config.trading_windows_algiers
    )
    windows = list(config.trading_windows_algiers)
    if is_open:
        for window in windows:
            if window.name == active_name:
                return (
                    label(
                        "ui.today.window_open",
                        name=window.name,
                        start=window.start,
                        end=window.end,
                    ),
                    True,
                )
    current = now_algiers.time()
    for window in windows:
        start = datetime.strptime(window.start, "%H:%M").time()
        if start > current:
            return (
                label(
                    "ui.today.window_next",
                    name=window.name,
                    start=window.start,
                    end=window.end,
                ),
                False,
            )
    if windows:
        first = windows[0]
        return (
            label(
                "ui.today.window_next",
                name=first.name,
                start=first.start,
                end=first.end,
            ),
            False,
        )
    return label("ui.today.window_none"), False


def _side_word(distance: float) -> str:
    return label("ui.today.above") if distance >= 0 else label("ui.today.below")


def build_today_read(profile: DayProfile | None) -> list[str]:
    """One or two plain sentences built only from existing DayProfile fields."""
    if profile is None:
        missing_call_wall = label(
            "ui.today.read.clause_level_missing", name=label("ui.term.call_wall")
        )
        missing_put_support = label(
            "ui.today.read.clause_level_missing", name=label("ui.term.put_support")
        )
        return [
            label("ui.today.read.gamma_missing")
            + " "
            + label(
                "ui.today.read.levels",
                call_wall=missing_call_wall,
                put_support=missing_put_support,
                expected_move=label("ui.today.read.clause_em_missing"),
            )
        ]

    spot = profile.spot_nq
    flip = profile.gamma_flip_nq
    if spot is not None and flip is not None:
        distance = abs(spot - flip)
        key = (
            "ui.today.read.gamma_above"
            if spot >= flip
            else "ui.today.read.gamma_below"
        )
        first = label(
            key,
            dist=f"{distance:,.1f}",
            flip=f"{flip:,.1f}",
            regime=label(
                f"gamma.{profile.gamma_regime}",
                default=tr_text(profile.gamma_regime),
            ),
        )
    else:
        first = label("ui.today.read.gamma_missing")

    def level_clause(name: str, value: float | None) -> str:
        if spot is None or value is None:
            return label("ui.today.read.clause_level_missing", name=name)
        delta = value - spot
        return label(
            "ui.today.read.clause_level",
            name=label(f"ui.term.{name}"),
            value=f"{value:,.2f}",
            dist=f"{abs(delta):,.1f}",
            side=_side_word(delta),
        )

    if profile.base_expected_move_pts is not None:
        if profile.em_consumption_pct is not None:
            em_clause = label(
                "ui.today.read.clause_em",
                value=f"{profile.base_expected_move_pts:,.1f}",
                consumed=f"{profile.em_consumption_pct:.1f}",
            )
        else:
            em_clause = label(
                "ui.today.read.clause_em_no_consumed",
                value=f"{profile.base_expected_move_pts:,.1f}",
            )
    else:
        em_clause = label("ui.today.read.clause_em_missing")

    second = label(
        "ui.today.read.levels",
        call_wall=level_clause("call_wall", profile.call_wall_nq),
        put_support=level_clause("put_support", profile.put_support_nq),
        expected_move=em_clause,
    )
    return [first, second[0].upper() + second[1:] if second else second]


def render_header_strip(
    profile: DayProfile, config: AppConfig, now_utc: datetime
) -> None:
    """Block 1: spot, freshness badge, Algiers window, next high-impact event."""
    freshness = freshness_code(profile)
    spot_text = (
        f"{profile.spot_nq:,.2f}" if profile.spot_nq is not None else status_label("NO_DATA")
    )
    window_text, window_open = trading_window_state(config, now_utc)
    algiers_time = now_utc.astimezone(TZ_ALGIERS).strftime("%H:%M")
    event = tr_text(profile.next_tier1_event or "") or label("ui.today.no_event")
    countdown = tr_text(profile.next_tier1_countdown or "")
    risk = label(f"risk.{profile.event_risk_level}", profile.event_risk_level)
    event_meta = (
        f"{_e(countdown)} · {_e(label('ui.today.risk'))} {_e(risk)}"
        if countdown
        else f"{_e(label('ui.today.risk'))} {_e(risk)}"
    )
    window_chip = (
        f'<span class="chip-ok">{_e(label("status.OK"))}</span>'
        if window_open
        else ""
    )
    algiers_meta = label("ui.today.algiers_time", time=algiers_time)
    st.markdown(
        f"""
        <div class="card strip">
            <div class="strip-item">
                <div class="strip-label">{_e(label("ui.today.spot"))}</div>
                <div class="strip-value">{_e(spot_text)}</div>
                <div class="strip-meta">{_e(algiers_meta)}</div>
            </div>
            <div class="strip-item">
                <div class="strip-label">{_e(label("ui.today.freshness"))}</div>
                <div class="strip-value">{badge_html(freshness)}</div>
                <div class="strip-meta">{_e(status_label(freshness))}</div>
            </div>
            <div class="strip-item">
                <div class="strip-label">{_e(label("ui.today.window"))}</div>
                <div class="strip-value">{_e(window_text)}</div>
                <div class="strip-meta">{window_chip}</div>
            </div>
            <div class="strip-item">
                <div class="strip-label">{_e(label("ui.today.next_event"))}</div>
                <div class="strip-value">{_e(event)}</div>
                <div class="strip-meta">{event_meta}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_today_read(profile: DayProfile) -> None:
    """Block 2: the single plain-language read card."""
    sentences = build_today_read(profile)
    body = "".join(f"<p>{_e(sentence)}</p>" for sentence in sentences if sentence)
    st.markdown(
        f'<div class="read-card"><div class="section-title">'
        f'{_e(label("ui.today.read_title"))}</div>{body}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LevelLine:
    """One row of the compact key-levels table (presentation only)."""

    term: str
    value: float | None
    distance: float | None
    is_range: bool = False


def compact_levels(profile: DayProfile | None) -> list[LevelLine]:
    """Call Wall, Gamma Flip, Put Support, Expected Move with spot distances."""
    if profile is None:
        return [
            LevelLine("call_wall", None, None),
            LevelLine("gamma_flip", None, None),
            LevelLine("put_support", None, None),
            LevelLine("expected_move", None, None, True),
        ]
    spot = profile.spot_nq

    def distance(price: float | None) -> float | None:
        if price is None or spot is None:
            return None
        return round(price - spot, 1)

    return [
        LevelLine("call_wall", profile.call_wall_nq, distance(profile.call_wall_nq)),
        LevelLine("gamma_flip", profile.gamma_flip_nq, distance(profile.gamma_flip_nq)),
        LevelLine("put_support", profile.put_support_nq, distance(profile.put_support_nq)),
        LevelLine(
            "expected_move",
            profile.base_expected_move_pts,
            profile.base_expected_move_pts,
            True,
        ),
    ]


def _format_level_value(line: LevelLine) -> str:
    if line.value is None:
        return status_label("NO_DATA")
    if line.is_range:
        return f"±{line.value:,.1f}"
    return f"{line.value:,.2f}"


def _format_level_distance(line: LevelLine) -> str:
    if line.distance is None:
        return status_label("NO_DATA")
    if line.is_range:
        return f"±{line.distance:,.1f}"
    return f"{line.distance:+,.1f}"


def render_levels_table(profile: DayProfile | None, caption: bool = True) -> None:
    """Compact four-row levels table; missing values display an explicit status."""
    rows = "".join(
        "<tr>"
        f"<td>{help_term(line.term)}</td>"
        f'<td class="num">{_e(_format_level_value(line))}</td>'
        f'<td class="num">{_e(_format_level_distance(line))}</td>'
        "</tr>"
        for line in compact_levels(profile)
    )
    st.markdown(
        f"""
        <div class="card">
            <div class="section-title">{_e(label("ui.today.levels_title"))}</div>
            <div class="table-scroll">
                <table class="levels-table">
                    <thead><tr>
                        <th>{_e(label("ui.today.levels_title"))}</th>
                        <th>{_e(label("ui.levels.value"))}</th>
                        <th>{_e(label("ui.levels.distance"))}</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if caption:
        st.caption(label("ui.levels.reference"))


def render_chart_section(
    profile: DayProfile,
    session_bars: list,
    last_bar_utc: datetime | None,
    *,
    show_levels: bool = True,
    show_labels: bool = True,
    height: int = 520,
) -> None:
    """Existing NQ chart with the gamma lines; honest empty state otherwise."""
    try:
        chart = build_session_chart(
            session_bars,
            gamma_flip=profile.gamma_flip_nq,
            call_wall=profile.call_wall_nq,
            put_support=profile.put_support_nq,
            last_bar_utc=last_bar_utc,
            show_levels=show_levels,
            show_labels=show_labels,
            height=height,
        )
        if chart.figure is not None:
            st.plotly_chart(chart.figure, use_container_width=True)
        else:
            st.info(chart.message)
    except Exception as exc:  # noqa: BLE001 - a chart must never break the page
        log.warning("Chart unavailable: %s", exc)
        st.warning(label("ui.today.chart_missing", error=exc))


# ---------------------------------------------------------------------------
# Watch next / macro radar / news wire / COT / health / scenarios
# ---------------------------------------------------------------------------


def _radar_card_html(card: MacroRadarCard, delay_idx: int = 0) -> str:
    """Read-only macro card (no hover, never styled like a button).

    ``delay_idx`` is kept for backwards compatibility with older callers; the
    redesigned UI uses a single, calm layout without staggered animations.
    """
    if card.is_ok:
        live_hint = t("Donnée active en direct", "Active live data")
        status = (
            '<span class="news-pill pill-ok">'
            f'<span class="live-dot" title="{_e(live_hint)}"></span>'
            f"{_e(status_label('OK'))}</span>"
        )
        card_cls = ""
    else:
        deg_hint = t("Flux dégradé ou clôture différée", "Degraded feed or delayed close")
        status = (
            '<span class="news-pill pill-deg">'
            f'<span class="deg-dot" title="{_e(deg_hint)}"></span>'
            f"{_e(status_label('DEGRADED'))}</span>"
        )
        card_cls = " degraded"
    source = tr_text(card.source)
    age = tr_text(card.age_str)
    timestamp = tr_text(card.timestamp_algiers_str)
    reason_html = ""
    if not card.is_ok:
        reason = card.degraded_reason or label("status.DEGRADED")
        reason = re.sub(
            r"^(\[?DÉGRADÉ\]?\s*[:—\-]?\s*)+", "", str(reason), flags=re.IGNORECASE
        ).strip()
        reason_html = (
            f'<div class="news-alert">{badge_html("DEGRADED")} '
            f"{_e(tr_text(reason or label('status.DEGRADED')))}</div>"
        )
    return (
        f'<div class="news-card{card_cls}">'
        f'<div class="news-card-header">'
        f'<span class="news-card-title">{_e(tr_text(card.category))} · '
        f"{_e(tr_text(card.title))}</span>{status}</div>"
        f'<div><div class="news-kpi">{_e(tr_text(card.main_value))}</div>'
        f'<div class="news-desc">{_e(tr_text(card.sub_value))}</div></div>'
        f'<div class="news-footer">'
        f"<div><b>{_e(t('Source :', 'Source:'))}</b> {_e(source)}</div>"
        f"<div><b>{_e(t('Horodatages :', 'Timestamps:'))}</b> {_e(timestamp)}</div>"
        f"<div><b>{_e(t('Âge :', 'Age:'))}</b> {_e(age)}</div>"
        f"{reason_html}</div></div>"
    )


def render_radar_cards(cards: list[MacroRadarCard]) -> None:
    """Full macro radar in a fluid CSS grid (no fixed Streamlit columns)."""
    html = "".join(_radar_card_html(card) for card in cards)
    st.markdown(f'<div class="radar-grid">{html}</div>', unsafe_allow_html=True)


def _driver_row_html(card: MacroRadarCard) -> str:
    name = f"{tr_text(card.category)} · {tr_text(card.title)}"
    value = tr_text(card.main_value)
    return (
        f'<div class="driver-row"><span class="driver-name">{_e(name)}</span>'
        f'<span class="driver-value">{_e(value)}</span></div>'
    )


def render_watch_next(profile: DayProfile, radar: MacroNewsRadar | None) -> None:
    """Block 4: next high-impact event + the top three existing macro drivers."""
    event = tr_text(profile.next_tier1_event or "") or label("ui.today.no_event")
    countdown = tr_text(profile.next_tier1_countdown or "")
    risk = label(f"risk.{profile.event_risk_level}", profile.event_risk_level)
    meta = " · ".join(
        part
        for part in (
            countdown,
            f"{label('ui.today.risk')} {risk}",
        )
        if part
    )
    if radar is not None:
        drivers = "".join(_driver_row_html(card) for card in radar.as_list()[:3])
    else:
        drivers = (
            f'<div class="news-alert">{badge_html("DEGRADED")} '
            f"{_e(label('ui.today.no_drivers'))}</div>"
        )
    st.markdown(
        f"""
        <div class="card watch-card">
            <div class="section-title">{_e(label("ui.today.watch_title"))}</div>
            <div class="watch-grid">
                <div>
                    <div class="strip-label">{_e(label("ui.today.next_event"))}</div>
                    <div class="watch-event">{_e(event)}</div>
                    <div class="strip-meta">{_e(meta)}</div>
                </div>
                <div>
                    <div class="strip-label">{_e(label("ui.today.drivers_title"))}</div>
                    {drivers}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _wire_item_html(item: NewsWireItem) -> str:
    """One news item; the headline is a real link and looks like one."""
    hint = label("ui.hint.external")
    return (
        f'<div class="news-wire-card">'
        f'<div class="wire-header">'
        f'<span class="wire-tag">{_e(tr_text(item.tag))}</span>'
        f'<span>{_e(tr_text(item.source))}</span></div>'
        f'<div class="wire-title">'
        f'<a href="{_e(item.link)}" target="_blank" rel="noopener noreferrer" '
        f'title="{_e(hint)}">{_e(tr_text(item.title))} ↗</a></div>'
        f'<div class="wire-footer">'
        f'<span>{_e(t("Alger", "Algiers"))} : {_e(tr_text(item.timestamp_algiers_str))}'
        f" · NY : {_e(item.timestamp_et_str)}</span>"
        f"<span>{_e(t('Âge', 'Age'))} : {_e(tr_text(item.age_str))}</span>"
        f"</div></div>"
    )


def render_news_wire(wire_report: NewsWireReport | None) -> None:
    """Live news wire, one column, newest first as already delivered by the engine."""
    if wire_report is None:
        unavailable = t("Fil d'actualités indisponible.", "News wire unavailable.")
        st.markdown(
            f'<div class="news-alert">{badge_html("DEGRADED")} '
            f"{_e(unavailable)}</div>",
            unsafe_allow_html=True,
        )
        return
    if wire_report.degraded_sources:
        reasons = " · ".join(tr_text(source) for source in wire_report.degraded_sources)
        prefix = t("Sources dégradées : ", "Degraded sources: ")
        st.markdown(
            f'<div class="news-alert">{badge_html("DEGRADED")} '
            f"{_e(prefix)}{_e(reasons)}</div>",
            unsafe_allow_html=True,
        )
    if not wire_report.items:
        empty = t("Aucun communiqué reçu.", "No release received.")
        st.markdown(
            f'<div class="news-alert">{badge_html("DEGRADED")} '
            f"{_e(empty)}</div>",
            unsafe_allow_html=True,
        )
        return
    for item in wire_report.items[:8]:
        st.markdown(_wire_item_html(item), unsafe_allow_html=True)


def render_cot(cot: dict | None) -> None:
    """CFTC Leveraged Funds positioning, exactly as stored in the profile."""
    title = (
        f"{_e(label('ui.macro.cot_title'))} · {help_term('leveraged_funds')}"
    )
    if not cot or not cot.get("report_date"):
        st.markdown(
            f'<div class="cot-card"><div class="section-title">{title}</div>'
            f'{badge_html("NO_DATA")} <span class="cot-line">'
            f"{_e(label('cot.no_data'))}</span></div>",
            unsafe_allow_html=True,
        )
        st.caption(label("cot.note"))
        return

    def number(value: object) -> str:
        return f"{value:,}" if isinstance(value, int | float) else "N/A"

    lines = [
        label("cot.category"),
        label("cot.contract", contract=cot.get("contract_name") or "N/A"),
        label("cot.report_date", date=cot.get("report_date") or "N/A"),
        f"{label('cot.net', net=number(cot.get('net')))} · "
        + label(
            "cot.long_short",
            long=number(cot.get("long")),
            short=number(cot.get("short")),
        ),
    ]
    if cot.get("source_message"):
        lines.append(tr_text(str(cot["source_message"])))
    body = "<br>".join(_e(line) for line in lines)
    st.markdown(
        f'<div class="cot-card"><div class="section-title">{title}</div>'
        f'{badge_html(str(cot.get("status") or "NO_DATA"))} '
        f'<span class="cot-line">{body}</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(label("cot.note"))


def render_health(profile: DayProfile) -> None:
    """Existing per-component health badges, one source per line, never hidden."""
    rows = "".join(
        f'<div class="health-row">{health_badge_html(health)}</div>'
        for health in profile.component_statuses.values()
    )
    if not rows:
        rows = f'<div class="health-row">{badge_html("NO_DATA")}</div>'
    st.markdown(f'<div class="health-list">{rows}</div>', unsafe_allow_html=True)


def render_scenarios(profile: DayProfile) -> None:
    """Existing conditional scenario cards, neutral style (no accent colour)."""
    if not profile.scenarios:
        st.info(
            t(
                "Aucun scénario généré pour la séance.",
                "No scenarios generated for this session.",
            )
        )
        return
    cond_lbl = t("Condition :", "Condition:")
    plan_lbl = t("Plan / Action :", "Plan / Action:")
    ctx_lbl = t("Contexte :", "Context:")
    for scenario in profile.scenarios:
        header = (
            f"{tr_text(scenario.level_name)} ({scenario.level_price:.1f})"
            f" — {scenario.level_type}"
        )
        with st.expander(header, expanded=False):
            st.markdown(
                f"""
                <div class="scenario-box">
                    <b>{_e(cond_lbl)}</b> {_e(tr_text(scenario.if_condition))}<br>
                    <b>{_e(plan_lbl)}</b> {_e(tr_text(scenario.then_plan))}<br>
                    <b>{_e(ctx_lbl)}</b> {_e(tr_text(scenario.context_notes))}
                </div>
                """,
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Levels page: full table with CSV export
# ---------------------------------------------------------------------------


def render_full_levels_table(profile: DayProfile) -> None:
    """All existing key levels + distances + CSV export button."""
    if not profile.key_levels:
        st.markdown(badge_html("NO_DATA") + " " + _e(label("ui.levels.empty")),
                    unsafe_allow_html=True)
        return
    columns = [
        (t("Niveau", "Level"), lambda level: tr_text(level.name)),
        (t("Prix NQ", "NQ Price"), lambda level: f"{level.price:,.2f}"),
        (t("Distance (pts)", "Distance (pts)"), lambda level: f"{level.distance_pts:+,.1f}"),
        (t("Écart %", "Diff %"), lambda level: f"{level.distance_pct:+.2f}%"),
        (t("Type", "Type"), lambda level: level.level_type),
        (t("Source", "Source"), lambda level: level.source),
    ]
    header = "".join(f"<th>{_e(name)}</th>" for name, _ in columns)
    rows = "".join(
        "<tr>"
        + "".join(
            f'<td class="num">{_e(getter(level))}</td>' if index in (1, 2, 3)
            else f"<td>{_e(getter(level))}</td>"
            for index, (_, getter) in enumerate(columns)
        )
        + "</tr>"
        for level in profile.key_levels
    )
    st.markdown(
        f"""
        <div class="card">
            <div class="table-scroll">
                <table class="levels-table">
                    <thead><tr>{header}</tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

