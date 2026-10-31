"""Regression tests for the browser UX polish fixes.

Each test targets one user-visible bug:
1. macro driver rows never collapse to one character per line;
2. every i18n key used by the UI exists in both dictionaries;
3. the briefing leaks no French wording in English mode;
4. GitHub alert tokens are rendered as native Streamlit boxes;
5. an empty conditional-scenarios section shows one muted line;
6. source health renders one source per line;
7. sidebar descriptions sit directly under their own button.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

from nqcockpit.profile.models import ComponentHealth, DayProfile
from nqcockpit.ui import i18n
from nqcockpit.ui.briefing_page import (
    ensure_empty_scenario_message,
    parse_briefing_blocks,
    prepare_briefing_markdown,
)
from nqcockpit.ui.i18n import LABELS, set_lang, tr_text
from nqcockpit.ui.nav import NAV_CSS, TOP_NAV_CSS
from nqcockpit.ui.sections import UI_CSS, render_health

UI_DIR = Path(i18n.__file__).resolve().parent


# ---------------------------------------------------------------------------
# 1. Macro driver rows: label keeps a real column, value wraps normally
# ---------------------------------------------------------------------------


def test_driver_row_css_prevents_vertical_text() -> None:
    assert ".driver-name" in UI_CSS
    assert "min-width: 12rem" in UI_CSS
    assert "word-break: normal" in UI_CSS
    driver_value = UI_CSS.split(".driver-value", 1)[1].split("}", 1)[0]
    assert "white-space: normal" in driver_value
    assert "white-space: nowrap" not in driver_value


# ---------------------------------------------------------------------------
# 2. i18n completeness: every label() key used by the UI exists in en + fr
# ---------------------------------------------------------------------------


def _used_label_keys() -> set[str]:
    keys: set[str] = set()
    for module_path in UI_DIR.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "label"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
    return keys


def test_every_ui_label_key_has_en_and_fr_strings() -> None:
    missing = sorted(key for key in _used_label_keys() if key not in LABELS)
    assert not missing, f"label() keys missing from LABELS: {missing}"
    for key in _used_label_keys():
        for lang in ("en", "fr"):
            assert LABELS[key][lang].strip(), f"{key} missing {lang}"


def test_scenarios_expander_has_both_languages() -> None:
    assert LABELS["ui.expander.scenarios"] == {
        "en": "Conditional scenarios",
        "fr": "Scénarios conditionnels",
    }


# ---------------------------------------------------------------------------
# 3. Briefing English display: no French words leak through
# ---------------------------------------------------------------------------

_BRIEFING_LEAK_SAMPLE = """
## 1. Session Profile & Conditional Scenarios (P08)

- **Gamma Regime:** `INDISPONIBLE`
- **Next Event:** Prochain : ISM Manufacturing dans 2j 22h 41m (Alger)
- **Factual Assessment:** Aucun événement significatif détecté.
"""


def test_briefing_english_has_no_french_words() -> None:
    set_lang("EN")
    try:
        text = prepare_briefing_markdown(_BRIEFING_LEAK_SAMPLE)
        lowered = text.lower()
        assert "unavailable" in lowered
        assert "in 2d 22h 41m" in lowered
        for word in ("indisponible", "aucun", "prochain", " dans "):
            assert word not in lowered
    finally:
        set_lang("EN")


def test_briefing_french_mode_keeps_french() -> None:
    set_lang("FR")
    try:
        assert "INDISPONIBLE" in tr_text("INDISPONIBLE")
        assert "dans 2j" in tr_text("dans 2j")
    finally:
        set_lang("EN")


# ---------------------------------------------------------------------------
# 4. GitHub alerts become native boxes, never raw tokens
# ---------------------------------------------------------------------------


def test_alert_blocks_are_parsed_without_tokens() -> None:
    markdown = (
        "## Section\n\n"
        "> [!WARNING]\n"
        "> Options positioning levels unavailable (DEGRADED Status).\n\n"
        "> [!NOTE]\n"
        "> A note body.\n\n"
        "> [!TIP]\n"
        "> A tip body.\n"
    )
    blocks = parse_briefing_blocks(markdown)
    kinds = [block.kind for block in blocks]
    assert kinds == ["markdown", "WARNING", "NOTE", "TIP"]
    assert "[!" not in " ".join(block.text for block in blocks)
    assert blocks[1].text.startswith("Options positioning")


def test_alert_directive_regex_is_case_insensitive() -> None:
    blocks = parse_briefing_blocks("> [!warning]\n> Danger.\n")
    assert blocks and blocks[0].kind == "WARNING"


# ---------------------------------------------------------------------------
# 5. Empty conditional scenarios: one muted line
# ---------------------------------------------------------------------------


def test_empty_scenarios_section_shows_english_message() -> None:
    markdown = "### Conditional Scenarios:\n\n---\n\n## Next section\n"
    out = ensure_empty_scenario_message(markdown, "EN")
    assert "No conditional scenarios for this session." in out
    assert "### Conditional Scenarios:" in out


def test_empty_scenarios_section_shows_french_message() -> None:
    markdown = "### Scénarios Conditionnels :\n\n---\n"
    out = ensure_empty_scenario_message(markdown, "FR")
    assert "Aucun scénario conditionnel pour cette séance." in out


def test_non_empty_scenarios_are_left_untouched() -> None:
    markdown = (
        "### Conditional Scenarios:\n\n"
        "- **[Call Wall @ 20100.00]** (RESISTANCE) :\n"
        "  - *Condition:* test\n"
    )
    assert ensure_empty_scenario_message(markdown, "EN") == markdown


# ---------------------------------------------------------------------------
# 6. Source health: one source per line
# ---------------------------------------------------------------------------


def _profile_with_health() -> DayProfile:
    return DayProfile(
        as_of_utc="2026-10-29T13:00:00+00:00",
        as_of_algiers="29/10/2026 14:00 (Alger)",
        as_of_et="29/10/2026 09:00 ET",
        target_date="2026-10-29",
        spot_nq=None,
        event_risk_level="GREEN",
        event_risk_reason="",
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
        day_type_reasons=[],
        component_statuses={
            "gamma": ComponentHealth(name="component.gamma", status="OK"),
            "macro": ComponentHealth(name="component.macro", status="NO_DATA"),
        },
    )


def test_source_health_renders_one_row_per_source() -> None:
    set_lang("EN")
    try:
        with patch("streamlit.markdown") as mock_markdown:
            render_health(_profile_with_health())
        html = mock_markdown.call_args[0][0]
        assert html.count('class="health-row"') == 2
        assert 'class="health-list"' in html
        assert "Events" not in html
    finally:
        set_lang("EN")


# ---------------------------------------------------------------------------
# 7. Top navigation: compact horizontal control, no sidebar block
# ---------------------------------------------------------------------------


def test_top_nav_css_keeps_one_compact_horizontal_row() -> None:
    assert 'div[data-testid="stRadio"]' in TOP_NAV_CSS
    assert "flex-direction: row" in TOP_NAV_CSS
    assert "flex-wrap: wrap" in TOP_NAV_CSS
    assert ".topnav-brand" in TOP_NAV_CSS
    assert NAV_CSS == TOP_NAV_CSS
