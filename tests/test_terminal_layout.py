"""Tests for the single-screen Terminal layout.

Acceptance criteria covered here:
- the top navigation exposes five destinations (EN + FR) and keeps
  legacy deep links working;
- the Terminal renders on one screen with normal data, degraded feeds and no
  data at all (friendly states, no traceback);
- the status chip is the only global status indicator and its tooltip lists
  every degraded feed;
- the chart layer toggles are gone: the chart is the TradingView widget;
- every page still renders headless through Streamlit's AppTest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import unescape
from pathlib import Path

from streamlit.testing.v1 import AppTest

from nqcockpit.config import load_config
from nqcockpit.data.models import Bar
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
    NoTradeFlag,
    NoTradeFlagCode,
)
from nqcockpit.ui import tv_widgets
from nqcockpit.ui.chart import build_session_chart
from nqcockpit.ui.cockpit_page import TodayData
from nqcockpit.ui.i18n import LABELS
from nqcockpit.ui.nav import DEFAULT_PAGE, NAV_CSS, TOP_NAV_CSS, page_keys, resolve_page
from nqcockpit.ui.terminal_page import degraded_feeds, terminal_status_code

NOW_UTC = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)


def _bar(offset_minutes: int, price: float = 20000.0) -> Bar:
    return Bar(
        timestamp_utc=datetime(2026, 10, 29, 13, offset_minutes, tzinfo=UTC),
        open=price,
        high=price + 8,
        low=price - 8,
        close=price + 3,
        volume=120.0,
    )


def _bars() -> list[Bar]:
    return [_bar(0), _bar(1, 20010.0), _bar(2, 20020.0)]


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


def _profile(
    *,
    spot: float | None = 20000.0,
    gamma_status: str = "OK",
    macro_status: str = "OK",
    status: str = "OK",
    stale_flag: bool = False,
) -> DayProfile:
    profile = DayProfile(
        as_of_utc=NOW_UTC.isoformat(),
        as_of_algiers="29/10/2026 14:00 (Alger)",
        as_of_et="29/10/2026 09:00 ET",
        target_date="2026-10-29",
        spot_nq=spot,
        event_risk_level="GREEN",
        event_risk_reason="No critical event",
        next_tier1_event="FOMC",
        next_tier1_countdown="2h 30m",
        volatility_regime="VOLATILITÉ NORMALE",
        vix_level=15.2,
        vxn_level=16.4,
        overnight_range_pts=65.0,
        gamma_regime="POSITIVE_GAMMA" if spot is not None else "INDISPONIBLE",
        net_gex_dollars=1.5e8,
        distance_to_flip_pts=50.0,
        base_expected_move_pts=150.0,
        em_consumption_pct=43.3,
        probable_day_type="TYPICAL",
        day_type_reasons=["Volatility normal"],
        component_statuses={
            "gamma": ComponentHealth(name="component.gamma", status=gamma_status),
            "macro": ComponentHealth(name="component.macro", status=macro_status),
            "events": ComponentHealth(
                name="component.events", status="OK" if spot is not None else "NO_DATA"
            ),
        },
        no_trade=NoTradeAssessment(
            is_trading_allowed=True,
            overall_status="ALLOWED",
            active_flags_count=0,
            all_flags=(
                [
                    NoTradeFlag(
                        code=NoTradeFlagCode.STALE_DATA,
                        title="Stale data",
                        triggered=True,
                        status="ACTIVE",
                        reason="snapshot older than threshold",
                        severity="BLOCKING",
                        source_module="test",
                    )
                ]
                if stale_flag
                else []
            ),
        ),
        gamma_flip_nq=19950.0 if spot is not None else None,
        call_wall_nq=20120.0 if spot is not None else None,
        put_support_nq=19840.0 if spot is not None else None,
        status=status,
    )
    return profile


def _data(
    profile: DayProfile,
    *,
    with_feeds: bool = True,
    with_bars: bool = True,
) -> TodayData:
    return TodayData(
        profile=profile,
        config=load_config(),
        now_utc=NOW_UTC,
        radar=_radar() if with_feeds else None,
        wire=_wire() if with_feeds else None,
        session_bars=_bars() if with_bars else [],
        last_bar_utc=NOW_UTC if with_bars else None,
    )


def _terminal_script(data):
    from nqcockpit.ui.terminal_page import render_terminal

    render_terminal(data)


def _journal_script() -> None:
    from nqcockpit.ui.journal_discipline_page import render_journal_discipline_page

    render_journal_discipline_page()


def _coaching_script() -> None:
    from nqcockpit.ui.coaching_page import render_coaching_app

    render_coaching_app()


def _settings_script() -> None:
    from nqcockpit.ui.settings_page import render_settings_page

    render_settings_page()


def _markdown(app: AppTest) -> str:
    return unescape(" ".join(element.value for element in app.markdown))


# ---------------------------------------------------------------------------
# 1. Navigation: four destinations, legacy links, compact horizontal control
# ---------------------------------------------------------------------------


def test_terminal_navigation_has_five_destinations_in_en_and_fr() -> None:
    assert page_keys() == ["terminal", "journal", "coaching", "market_map", "settings"]
    assert DEFAULT_PAGE == "terminal"
    assert LABELS["ui.nav.terminal.name"] == {"en": "Terminal", "fr": "Terminal"}
    for key in (
        "ui.nav.terminal.name",
        "ui.nav.journal.name",
        "ui.nav.coaching.name",
        "ui.nav.market_map.name",
    ):
        assert key in LABELS
        for lang in ("en", "fr"):
            assert LABELS[key][lang].strip()


def test_legacy_links_land_on_existing_panels() -> None:
    for legacy in ("", "1", "today", "cockpit", "levels", "macro", "news", "briefing"):
        assert resolve_page(legacy) == "terminal"
    assert resolve_page("2") == "journal"
    assert resolve_page("discipline") == "journal"
    assert resolve_page("4") == "coaching"
    assert resolve_page("5") == "settings"
    assert resolve_page("unknown") == "terminal"


def test_top_nav_is_a_compact_horizontal_control() -> None:
    assert 'div[data-testid="stRadio"]' in TOP_NAV_CSS
    assert "flex-direction: row" in TOP_NAV_CSS
    assert "stSidebar" not in TOP_NAV_CSS
    assert NAV_CSS == TOP_NAV_CSS


# ---------------------------------------------------------------------------
# 2. One status chip: OK / Degraded / Stale / No data
# ---------------------------------------------------------------------------


def test_status_chip_is_tri_state() -> None:
    healthy = _data(_profile(), with_bars=True)
    assert terminal_status_code(healthy.profile, healthy) == "OK"

    degraded = _data(_profile(macro_status="DEGRADED", status="DEGRADED"))
    assert terminal_status_code(degraded.profile, degraded) == "DEGRADED"

    stale = _data(_profile(gamma_status="STALE", status="DEGRADED"))
    assert terminal_status_code(stale.profile, stale) == "STALE"

    no_data = _data(_profile(spot=None, gamma_status="NO_DATA"), with_feeds=False)
    assert terminal_status_code(no_data.profile, no_data) == "NO_DATA"


def test_status_chip_tooltip_lists_degraded_feeds() -> None:
    profile = _profile(macro_status="DEGRADED", status="DEGRADED")
    feeds = degraded_feeds(profile, _data(profile, with_feeds=False, with_bars=False))
    joined = " | ".join(feeds)
    assert "Macro" in joined  # component.macro
    assert "Macro radar" in joined
    assert "News wire" in joined
    assert "Chart bars" in joined
    assert not degraded_feeds(_profile(), _data(_profile(), with_bars=True))


# ---------------------------------------------------------------------------
# 3. Chart builder options stay display-only (kept for the Levels page)
# ---------------------------------------------------------------------------


def test_chart_layer_options_only_change_the_display() -> None:
    bars = _bars()
    with_levels = build_session_chart(
        bars, gamma_flip=19950.0, call_wall=20120.0, put_support=19840.0
    )
    assert len(with_levels.figure.layout.shapes) == 3
    assert with_levels.figure.layout.annotations

    no_levels = build_session_chart(
        bars,
        gamma_flip=19950.0,
        call_wall=20120.0,
        put_support=19840.0,
        show_levels=False,
    )
    assert len(no_levels.figure.layout.shapes) == 0

    no_labels = build_session_chart(
        bars,
        gamma_flip=19950.0,
        call_wall=20120.0,
        put_support=19840.0,
        show_labels=False,
    )
    assert len(no_labels.figure.layout.shapes) == 3
    assert not no_labels.figure.layout.annotations


# ---------------------------------------------------------------------------
# 4. Terminal renders with data, degraded feeds and no data
# ---------------------------------------------------------------------------


def test_terminal_renders_with_normal_data() -> None:
    data = _data(_profile())
    app = AppTest.from_function(_terminal_script, args=(data,), default_timeout=60)
    app.run()

    assert not app.exception, app.exception
    markdown = _markdown(app)
    assert "NQ spot" in markdown
    assert "20,000.00" in markdown
    assert "Call Wall" in markdown
    assert "Gamma Flip" in markdown
    assert "Put Support" in markdown
    assert "Trades today" in markdown
    assert "Gamma regime" in markdown
    assert [tab.label for tab in app.tabs] == ["Radar", "News", "Events", "Coach"]
    assert [button.label for button in app.button] == ["Brief"]
    assert "All tracked feeds are fresh." in markdown


def test_terminal_renders_with_degraded_data() -> None:
    profile = _profile(macro_status="DEGRADED", status="DEGRADED")
    data = _data(profile, with_feeds=False, with_bars=False)
    app = AppTest.from_function(_terminal_script, args=(data,), default_timeout=60)
    app.run()

    assert not app.exception, app.exception
    markdown = _markdown(app)
    assert "Degraded" in markdown
    assert "Degraded feeds:" in markdown
    assert "Macro radar" in markdown
    # The TradingView widget renders even without stored bars, so the old
    # "No chart data" placeholder is gone; the symbol picker stays usable.
    info = unescape(" ".join(el.value for el in app.info))
    assert "No chart data" not in info
    assert any(box.label == "Symbol" for box in app.selectbox)


def test_terminal_renders_without_data() -> None:
    profile = _profile(spot=None, gamma_status="NO_DATA", status="DEGRADED")
    data = _data(profile, with_feeds=False, with_bars=False)
    app = AppTest.from_function(_terminal_script, args=(data,), default_timeout=60)
    app.run()

    assert not app.exception, app.exception
    markdown = _markdown(app)
    assert "No data" in markdown
    assert "No upcoming" not in markdown


def _terminal_script_with_sources(data):
    from nqcockpit.ui.terminal_page import render_terminal

    render_terminal(data)


def test_terminal_source_health_chip_and_panel(monkeypatch) -> None:
    """Le chip « N/M sources OK » et le panneau DÉGRADÉ/STALE s'affichent."""
    from datetime import datetime, timezone

    import nqcockpit.ui.terminal_page as tp
    from nqcockpit.events.models import DataStatus, SourceHealth

    source_health = [
        SourceHealth(source="fed", status=DataStatus.OK, events_count=3,
                     last_success_utc=datetime.now(timezone.utc)),
        SourceHealth(source="ecb", status=DataStatus.DEGRADED, events_count=0,
                     error_msg="flux vide", stale=True),
    ]
    monkeypatch.setattr(tp, "load_latest_event_source_health", lambda: source_health)

    data = _data(_profile())
    app = AppTest.from_function(_terminal_script_with_sources, args=(data,), default_timeout=60)
    app.run()

    assert not app.exception, app.exception
    markdown = _markdown(app)
    assert "1/2 sources OK" in markdown
    assert "Event sources" in markdown
    assert "DEGRADED" in markdown
    assert "STALE" in markdown
    assert "flux vide" in markdown
    assert "fed" in markdown


def test_terminal_chart_symbol_picker_lists_verified_options() -> None:
    data = _data(_profile())
    app = AppTest.from_function(_terminal_script, args=(data,), default_timeout=60)
    app.run()

    assert not app.exception, app.exception
    assert not app.toggle, "the layer toggles must be gone from the Terminal"
    labels = [box.label for box in app.selectbox]
    assert "Symbol" in labels
    box = next(box for box in app.selectbox if box.label == "Symbol")
    assert list(box.options) == list(tv_widgets.NQ_SYMBOL_OPTIONS)
    assert box.value == tv_widgets.DEFAULT_NQ_SYMBOL
    assert "CME_MINI:NQ1!" not in list(box.options)
    # The widget embeds a real TradingView script URL.
    from nqcockpit.ui import terminal_page

    source = Path(terminal_page.__file__).read_text(encoding="utf-8")
    assert "advanced_chart_html" in source
    assert "tv_widgets.render_widget" in source
    assert "components.html" not in source


def test_terminal_renders_in_en_and_fr_with_no_raw_keys() -> None:
    data = _data(_profile())
    texts: dict[str, str] = {}
    for lang in ("EN", "FR"):
        app = AppTest.from_function(_terminal_script, args=(data,), default_timeout=60)
        app.session_state["lang"] = lang
        app.run()
        assert not app.exception, (lang, app.exception)

        parts = [element.value for element in app.markdown]
        parts += [element.value for element in app.caption]
        parts += [element.value for element in app.info]
        parts += [element.value for element in app.warning]
        parts += [box.label for box in app.selectbox]
        parts += [str(option) for box in app.selectbox for option in box.options]
        parts += [tab.label for tab in app.tabs]
        parts += [button.label for button in app.button]
        joined = " ".join(parts)
        assert "ui." not in joined, (lang, joined)
        texts[lang] = joined

    assert "Symbol" in texts["EN"]
    assert "Symbole" in texts["FR"]


def test_terminal_brief_button_opens_without_error() -> None:
    data = _data(_profile())
    app = AppTest.from_function(_terminal_script, args=(data,), default_timeout=60)
    app.run()
    app.button[0].click()
    app.run()
    assert not app.exception, app.exception
    # Dialog or expander fallback: the briefing content must be reachable.
    text = " ".join(
        unescape(element.value)
        for element in list(app.markdown) + list(app.warning) + list(app.info)
    )
    assert "briefing" in text.lower() or "briefing" in " ".join(
        expander.label.lower() for expander in app.expander
    )


# ---------------------------------------------------------------------------
# 5. Every page renders headless
# ---------------------------------------------------------------------------


def test_journal_discipline_page_renders_headless() -> None:
    app = AppTest.from_function(_journal_script, default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    assert [tab.label for tab in app.tabs] == ["Trade journal", "Discipline gate"]


def test_coaching_page_renders_headless() -> None:
    app = AppTest.from_function(_coaching_script, default_timeout=120)
    app.run()
    assert not app.exception, app.exception


def test_settings_page_renders_headless() -> None:
    app = AppTest.from_function(_settings_script, default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    assert any("English" in button.label for button in app.button)


# ---------------------------------------------------------------------------
# 6. The stacked detail blocks are gone from the Terminal
# ---------------------------------------------------------------------------


def test_terminal_has_no_stacked_expanders_or_click_suffixes() -> None:
    from nqcockpit.ui import terminal_page

    source = Path(terminal_page.__file__).read_text(encoding="utf-8")
    # Two expanders: the Brief dialog fallback + the event source-health panel.
    assert source.count("st.expander") == 2
    assert "ui.expander." not in source
    assert "click_details" not in source
    assert "render_health(" not in source
    assert "ui.terminal.tab_radar" in source


def test_terminal_labels_exist_in_both_languages() -> None:
    for key in (
        "ui.terminal.brief",
        "ui.terminal.brief_title",
        "ui.terminal.symbol",
        "ui.terminal.tab_radar",
        "ui.terminal.tab_news",
        "ui.terminal.tab_events",
        "ui.terminal.tab_coach",
        "ui.terminal.trades_today",
        "ui.terminal.kill_zone_label",
        "ui.terminal.kill_zone_active",
        "ui.terminal.kill_zone_outside",
        "ui.terminal.gamma_label",
        "ui.terminal.status_tooltip_ok",
        "ui.terminal.status_tooltip_degraded",
        "ui.terminal.status_tooltip_stale",
        "ui.terminal.status_tooltip_no_data",
        "ui.terminal.events_next",
        "ui.terminal.events_risk",
        "ui.terminal.no_radar",
        "ui.terminal.events_empty",
    ):
        assert key in LABELS, key
        for lang in ("en", "fr"):
            assert LABELS[key][lang].strip(), f"{key} missing {lang}"
