"""Regression tests for the two bugs found by the 1920x1080 visual tester.

1. The brand ("NQ COCKPIT" + DESK) and the horizontal navigation were clipped
   under Streamlit's fixed top toolbar: the main block container now reserves
   3.5rem of top padding on every page, and the Terminal gives that height back
   by shrinking its fixed chart / right-panel containers.
2. The Journal & Discipline page leaked raw French enum values in English mode
   (`inconnu`, `faible`, `élevée`, `hors_fenêtre`...). Display labels are now
   localized while the stored value stays untouched.
"""

from __future__ import annotations

from html import unescape
from pathlib import Path

from streamlit.testing.v1 import AppTest

from nqcockpit.ui import sections, terminal_page
from nqcockpit.ui.i18n import set_lang
from nqcockpit.ui.journal_page import (
    default_period_label,
    direction_label,
    gamma_regime_label,
    journal_segment_label,
    segment_by_label,
    violation_type_label,
    vol_regime_label,
    window_name_label,
)

UI_DIR = Path(__file__).resolve().parents[1] / "src" / "nqcockpit" / "ui"
TOP_PADDING = "4rem"
# Streamlit 1.66 renders a fixed header 3.75rem tall.
STREAMLIT_HEADER = 3.75


def _render_journal(lang: str) -> None:
    """AppTest entry point: render the Journal page in a forced language."""
    from nqcockpit.ui.i18n import set_lang as _set_lang
    from nqcockpit.ui.journal_discipline_page import render_journal_discipline_page

    _set_lang(lang)
    render_journal_discipline_page()


def _run_journal(lang: str) -> AppTest:
    app = AppTest.from_function(_render_journal, args=(lang,), default_timeout=120)
    app.run()
    assert not app.exception, app.exception
    return app


def _render_coaching(lang: str) -> None:
    """AppTest entry point: render the Coaching page in a forced language."""
    from nqcockpit.ui.coaching_page import render_coaching_app
    from nqcockpit.ui.i18n import set_lang as _set_lang

    _set_lang(lang)
    render_coaching_app()


def _run_coaching(lang: str) -> AppTest:
    app = AppTest.from_function(_render_coaching, args=(lang,), default_timeout=120)
    app.run()
    assert not app.exception, app.exception
    return app


def _widget_options(app: AppTest) -> list[tuple[str, str]]:
    """(label, option) pairs for every selectbox / radio on the page."""
    pairs: list[tuple[str, str]] = []
    for widget in list(app.selectbox) + list(app.radio):
        pairs.extend((widget.label, str(option)) for option in widget.options)
    return pairs


def _assert_no_tokens(pairs: list[tuple[str, str]], tokens: tuple[str, ...]) -> None:
    haystack = " | ".join(f"{label} :: {option}" for label, option in pairs).lower()
    for token in tokens:
        assert token not in haystack, f"unexpected option label {token!r}: {haystack}"


def _selectbox_by_label(app: AppTest, wanted: str):
    for box in app.selectbox:
        if box.label == wanted:
            return box
    labels = [box.label for box in app.selectbox]
    raise AssertionError(f"selectbox {wanted!r} not found in {labels}")


def _page_text(app: AppTest) -> str:
    """Every string an operator can read: markdown, boxes and widget options."""
    parts = [unescape(element.value) for element in app.markdown]
    parts += [unescape(element.value) for element in list(app.info) + list(app.warning)]
    for box in app.selectbox:
        parts.append(box.label)
        # AppTest stores the formatted options: exactly what the UI displays.
        parts.extend(str(option) for option in box.options)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 1. Fixed toolbar: padding on every page, compensated on the Terminal
# ---------------------------------------------------------------------------


def test_every_page_clears_the_fixed_streamlit_toolbar() -> None:
    app_source = (UI_DIR / "app.py").read_text(encoding="utf-8")
    assert f"padding-top: {TOP_PADDING} !important" in app_source
    assert f"padding-top: {TOP_PADDING}" in sections.UI_CSS
    assert f"padding-top: {TOP_PADDING} !important" in terminal_page.TERMINAL_CSS
    # 4rem = 64px > the 3.75rem (60px) fixed header of Streamlit 1.66.
    assert float(TOP_PADDING.removesuffix("rem")) > STREAMLIT_HEADER


def test_terminal_heights_compensate_the_extra_top_padding() -> None:
    # 0.4rem -> 4rem costs 57.6px at 16px/rem; the two containers absorb it
    # together (chart 640->600, right panel 690->630).
    extra_px = (4.0 - 0.4) * 16
    assert terminal_page.CHART_HEIGHT == 600
    assert terminal_page.RIGHT_PANEL_HEIGHT == 630
    compensation = (640 - terminal_page.CHART_HEIGHT) + (
        690 - terminal_page.RIGHT_PANEL_HEIGHT
    )
    assert compensation >= extra_px


# ---------------------------------------------------------------------------
# 2. Journal enum values: localized display, unchanged stored value
# ---------------------------------------------------------------------------


def test_journal_value_labels_are_localized() -> None:
    set_lang("EN")
    try:
        assert gamma_regime_label("inconnu") == "Unknown"
        assert gamma_regime_label("GEX+") == "GEX+"
        assert vol_regime_label("élevée") == "High"
        assert vol_regime_label("faible") == "Low"
        assert journal_segment_label("inconnu") == "Unknown"
        assert journal_segment_label("(sans tag)") == "(no tag)"
        assert journal_segment_label("Lun") == "Mon"
        assert violation_type_label("hors_fenêtre") == "Out of window"
        assert violation_type_label("sl_déplacé") == "Stop-loss moved"
        assert segment_by_label("gamma_regime") == "Gamma regime"
        assert direction_label("NONE") == "None"
        assert window_name_label("trade1") == "Trade 1"
        assert window_name_label("") == "—"
    finally:
        set_lang("EN")

    set_lang("FR")
    try:
        assert gamma_regime_label("inconnu") == "Inconnu"
        assert vol_regime_label("élevée") == "Élevée"
        assert violation_type_label("hors_fenêtre") == "Hors fenêtre"
        assert segment_by_label("day_of_week") == "Jour de semaine"
        assert direction_label("NONE") == "Aucune"
        assert window_name_label("trade2") == "Trade 2"
    finally:
        set_lang("EN")


def test_journal_page_in_english_never_shows_french_option_labels() -> None:
    app = _run_journal("EN")

    gamma = _selectbox_by_label(app, "Gamma Regime")
    # Display is English, but the option handed to the engine is unchanged.
    assert gamma.value == "inconnu"
    assert gamma.options == ["GEX+", "GEX-", "Unknown"]

    vol = _selectbox_by_label(app, "Volatility Regime")
    assert vol.value == "élevée"
    assert vol.options == ["Low", "Normal", "High", "Unknown"]

    window = _selectbox_by_label(app, "Window")
    assert window.value == "trade1"
    assert window.options[:3] == ["Trade 1", "Trade 2", "—"]

    direction = _selectbox_by_label(app, "Direction")
    assert direction.value == "LONG"
    assert direction.options == ["LONG", "SHORT", "None"]

    pairs = _widget_options(app)
    # Exact option values, so English "Normal"/"High" do not false-positive.
    options = {option.strip().lower() for _, option in pairs}
    for leak in (
        "inconnu",
        "faible",
        "élevée",
        "normale",
        "hebdo",
        "mensuel",
        "manuel",
        "temps",
        "hors_fenêtre",
        "(sans tag)",
    ):
        assert leak not in options, f"raw French option leaked in EN mode: {leak}"

    text = _page_text(app).lower()
    for leak in ("inconnu", "faible", "élevée", "hors_fenêtre"):
        assert leak not in text, f"raw French value leaked in EN mode: {leak}"


def test_journal_page_in_french_shows_no_english_option_labels() -> None:
    app = _run_journal("FR")

    gamma = _selectbox_by_label(app, "Régime gamma")
    assert gamma.value == "inconnu"
    assert "Inconnu" in gamma.options
    vol = _selectbox_by_label(app, "Régime volatilité")
    assert "Élevée" in vol.options

    window = _selectbox_by_label(app, "Fenêtre")
    assert window.value == "trade1"
    assert "Trade 1" in window.options
    assert "trade1" not in window.options

    direction = _selectbox_by_label(app, "Direction")
    assert direction.value == "LONG"
    assert direction.options == ["LONG", "SHORT", "Aucune"]

    options = {option.strip().lower() for _, option in _widget_options(app)}
    for leak in (
        "unknown",
        "low",
        "high",
        "weekly",
        "monthly",
        "manual",
        "none",
        "setup_tag",
        "gamma_regime",
        "vol_regime",
        "day_of_week",
        "event_risk",
        "trade1",
        "trade2",
    ):
        assert leak not in options, f"raw English option leaked in FR mode: {leak}"


def test_coaching_page_option_labels_follow_the_language() -> None:
    english = _run_coaching("EN")
    english_options = {option.strip().lower() for _, option in _widget_options(english)}
    assert "all data" in english_options
    for leak in ("toutes les données", "cette semaine", "plage personnalisée"):
        assert leak not in english_options, f"French option leaked in EN: {leak}"

    french = _run_coaching("FR")
    french_options = {option.strip().lower() for _, option in _widget_options(french)}
    assert "toutes les données" in french_options
    assert "all data" not in french_options


def test_default_period_label_is_computed_from_today() -> None:
    """Le libellé par défaut du rapport suit la semaine ISO du jour (plus de S39 figé)."""
    from datetime import date

    iso_year, iso_week, _ = date(2026, 10, 31).isocalendar()
    assert iso_week == 44

    label = default_period_label(date(2026, 10, 31))
    assert label in (f"W{iso_week}-{iso_year}", f"S{iso_week}-{iso_year}")
    assert "39" not in label  # la semaine 39 est révolue et ne doit plus apparaître
