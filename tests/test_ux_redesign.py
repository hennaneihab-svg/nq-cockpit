"""Tests for the UX redesign — plain-language navigation and the Today page.

Covers the explicit acceptance criteria:
- the six destinations and their one-line descriptions exist in English + French;
- the Today page renders headless with data and with an empty database, showing
  explicit "No data" states instead of invented numbers;
- no layout file nests Streamlit columns beyond two levels;
- every technical term has a one-sentence help tooltip in both languages.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from html import unescape
from pathlib import Path

from streamlit.testing.v1 import AppTest

from nqcockpit.config import load_config
from nqcockpit.macro.news_radar import (
    MacroNewsRadar,
    MacroRadarCard,
    NewsWireItem,
    NewsWireReport,
)
from nqcockpit.profile.models import (
    ComponentHealth,
    DayProfile,
    NoTradeAssessment,
)
from nqcockpit.ui.cockpit_page import TodayData
from nqcockpit.ui.i18n import LABELS
from nqcockpit.ui.nav import (
    DEFAULT_PAGE,
    PAGES,
    page_keys,
    resolve_page,
)

NOW_UTC = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)

HELP_TERMS = ("call_wall", "gamma_flip", "put_support", "expected_move", "leveraged_funds")

LAYOUT_MODULES = (
    "cockpit_page",
    "levels_page",
    "macro_page",
    "settings_page",
    "journal_discipline_page",
    "nav",
    "sections",
)


def _radar() -> MacroNewsRadar:
    card = MacroRadarCard(
        category="RATES & YIELDS",
        title="US 10Y & 2Y Yields",
        main_value="10Y: 4.25% | 2Y: 3.95%",
        sub_value="Spread: +30 bps",
        source="FRED",
        timestamp_utc=NOW_UTC,
        observation_date="2026-10-28",
        age_str="2 min",
        status="OK",
        is_ok=True,
    )
    return MacroNewsRadar(
        rates=card,
        inflation=card,
        mega_caps=card,
        fed=card,
        oil=card,
        dollar=card,
    )


def _wire() -> NewsWireReport:
    return NewsWireReport(
        items=[
            NewsWireItem(
                title="Federal Reserve issues FOMC statement",
                link="https://example.com/fomc",
                source="Federal Reserve",
                tag="FED / RATES",
                tag_color="#38BDF8",
                timestamp_utc=NOW_UTC,
                timestamp_algiers_str="29/10/2026 14:00 (Alger)",
                timestamp_et_str="29/10/2026 09:00 ET",
                age_str="5 min",
                is_ok=True,
                status="OK",
            )
        ],
        degraded_sources=[],
        is_ok=True,
    )


def _profile_with_data() -> DayProfile:
    return DayProfile(
        as_of_utc=NOW_UTC.isoformat(),
        as_of_algiers="29/10/2026 14:00 (Alger)",
        as_of_et="29/10/2026 09:00 ET",
        target_date="2026-10-29",
        spot_nq=20000.0,
        event_risk_level="GREEN",
        event_risk_reason="Aucun événement critique",
        next_tier1_event="FOMC",
        next_tier1_countdown="2h 30m",
        volatility_regime="VOLATILITÉ NORMALE",
        vix_level=15.2,
        vxn_level=16.4,
        overnight_range_pts=65.0,
        gamma_regime="POSITIVE_GAMMA",
        net_gex_dollars=1.5e8,
        distance_to_flip_pts=50.0,
        base_expected_move_pts=150.0,
        em_consumption_pct=43.3,
        probable_day_type="TYPICAL",
        day_type_reasons=["Volatilité normale", "Gamma positif"],
        key_levels=[],
        scenarios=[],
        component_statuses={
            "gamma": ComponentHealth(name="component.gamma", status="OK"),
            "macro": ComponentHealth(name="component.macro", status="OK"),
        },
        no_trade=NoTradeAssessment(
            is_trading_allowed=True,
            overall_status="AUTORISÉ (sous conditions)",
            active_flags_count=0,
        ),
        gamma_flip_nq=19950.0,
        call_wall_nq=20120.0,
        put_support_nq=19840.0,
    )


def _empty_profile() -> DayProfile:
    """Same shape as a profile built on a fresh/empty database: no numbers."""
    return DayProfile(
        as_of_utc=NOW_UTC.isoformat(),
        as_of_algiers="29/10/2026 14:00 (Alger)",
        as_of_et="29/10/2026 09:00 ET",
        target_date="2026-10-29",
        spot_nq=None,
        event_risk_level="GREEN",
        event_risk_reason="Calendar unavailable",
        next_tier1_event=None,
        next_tier1_countdown=None,
        volatility_regime="VOLATILITÉ NORMALE",
        vix_level=None,
        vxn_level=None,
        overnight_range_pts=None,
        gamma_regime="INDISPONIBLE",
        net_gex_dollars=None,
        distance_to_flip_pts=None,
        base_expected_move_pts=None,
        em_consumption_pct=None,
        probable_day_type="range",
        day_type_reasons=["Données indisponibles"],
        key_levels=[],
        scenarios=[],
        component_statuses={
            "gamma": ComponentHealth(name="component.gamma", status="NO_DATA"),
            "macro": ComponentHealth(name="component.macro", status="NO_DATA"),
            "events": ComponentHealth(name="component.events", status="NO_DATA"),
            "overnight": ComponentHealth(name="component.overnight", status="NO_DATA"),
        },
        no_trade=NoTradeAssessment(
            is_trading_allowed=True,
            overall_status="AUTORISÉ",
            active_flags_count=0,
        ),
        status="DEGRADED",
    )


def _today_data(profile: DayProfile, with_feeds: bool) -> TodayData:
    return TodayData(
        profile=profile,
        config=load_config(),
        now_utc=NOW_UTC,
        radar=_radar() if with_feeds else None,
        wire=_wire() if with_feeds else None,
        session_bars=[],
        last_bar_utc=None,
    )


def _render_today_script(data):
    """Self-contained script used by AppTest.from_function."""
    from nqcockpit.ui.cockpit_page import render_today

    render_today(data)


# ---------------------------------------------------------------------------
# 1. Page list and descriptions, EN + FR
# ---------------------------------------------------------------------------


def test_six_pages_have_names_and_descriptions_in_en_and_fr() -> None:
    """Every destination has a plain name and one-line description in both languages."""
    assert page_keys() == [
        "today",
        "levels",
        "macro",
        "journal",
        "coaching",
        "settings",
    ]
    assert DEFAULT_PAGE == "today"
    for page in PAGES:
        for key in (page.name_key, page.desc_key):
            assert key in LABELS, f"missing i18n key {key}"
            for lang in ("en", "fr"):
                assert LABELS[key][lang].strip(), f"{key} missing {lang}"
        assert LABELS[page.desc_key]["en"] != LABELS[page.name_key]["en"]
        assert LABELS[page.desc_key]["fr"] != LABELS[page.name_key]["fr"]
    english_names = {LABELS[page.name_key]["en"] for page in PAGES}
    french_names = {LABELS[page.name_key]["fr"] for page in PAGES}
    assert len(english_names) == len(PAGES)
    assert len(french_names) == len(PAGES)


def test_legacy_links_resolve_to_the_new_pages() -> None:
    """Old section numbers and names still land on a valid destination."""
    assert resolve_page(None) == "today"
    assert resolve_page("1") == "today"
    assert resolve_page("cockpit") == "today"
    assert resolve_page("2") == "journal"
    assert resolve_page("discipline") == "journal"
    assert resolve_page("5") == "settings"
    assert resolve_page("briefing") == "settings"
    assert resolve_page("levels") == "levels"
    assert resolve_page("unknown-value") == "today"


def test_technical_terms_have_plain_help_in_en_and_fr() -> None:
    """Call Wall, Gamma Flip, Put Support, Expected Move, Leveraged Funds each get a help line."""
    for term in HELP_TERMS:
        term_key = f"ui.term.{term}"
        help_key = f"ui.help.{term}"
        assert term_key in LABELS
        assert help_key in LABELS
        for lang in ("en", "fr"):
            assert LABELS[term_key][lang].strip()
            assert len(LABELS[help_key][lang].strip()) > 20
    for lang in ("en", "fr"):
        hint = LABELS["ui.hint.click_details"][lang].lower()
        assert "click" in hint or "cliquez" in hint


# ---------------------------------------------------------------------------
# 2. Today page renders headless, with data and with an empty database
# ---------------------------------------------------------------------------


def test_today_renders_with_data() -> None:
    """With a full profile the page renders four blocks and no exception."""
    data = _today_data(_profile_with_data(), with_feeds=True)
    app = AppTest.from_function(_render_today_script, args=(data,), default_timeout=30)
    app.run()

    assert not app.exception, app.exception
    markdown = unescape(" ".join(element.value for element in app.markdown))
    assert "Today's read" in markdown
    assert "20,000.00" in markdown
    assert "Call Wall" in markdown
    assert "Gamma Flip" in markdown
    assert "Expected Move" in markdown
    assert "Watch next" in markdown


def test_today_renders_with_empty_database_and_shows_no_data() -> None:
    """Empty DB: the page still renders, with explicit 'No data' states only."""
    data = _today_data(_empty_profile(), with_feeds=False)
    app = AppTest.from_function(_render_today_script, args=(data,), default_timeout=30)
    app.run()

    assert not app.exception, app.exception
    markdown = unescape(" ".join(element.value for element in app.markdown))
    assert "No data" in markdown
    assert "Watch next" in markdown


# ---------------------------------------------------------------------------
# 3. Layout depth: no nested columns beyond two levels
# ---------------------------------------------------------------------------


def _is_st_columns(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "columns"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
    )


def _max_columns_depth(tree: ast.AST) -> int:
    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0
            self.max_depth = 0

        def visit_With(self, node: ast.With) -> None:
            opens_columns = any(_is_st_columns(item.context_expr) for item in node.items)
            if opens_columns:
                self.depth += 1
                self.max_depth = max(self.max_depth, self.depth)
            self.generic_visit(node)
            if opens_columns:
                self.depth -= 1

    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.max_depth


def test_new_layout_files_never_nest_columns_beyond_two_levels() -> None:
    """Every redesigned layout file stays within two column levels."""
    import importlib

    for module_name in LAYOUT_MODULES:
        module = importlib.import_module(f"nqcockpit.ui.{module_name}")
        source = Path(module.__file__).read_text(encoding="utf-8")
        depth = _max_columns_depth(ast.parse(source))
        assert depth <= 2, f"{module_name}.py nests columns on {depth} levels"
