"""Tests de la page Market Map : quatre widgets TradingView, EN et FR."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from nqcockpit.ui import tv_widgets
from nqcockpit.ui.i18n import LABELS
from nqcockpit.ui.nav import page_keys, page_name
from nqcockpit.ui.terminal_page import SYMBOL_STATE_KEY

EXPECTED_EN = (
    "Market Map",
    "Nasdaq-100 heatmap",
    "US economic calendar",
    "Technical gauge",
    "Cross-asset quotes",
)
EXPECTED_FR = (
    "Carte du marché",
    "Carte de chaleur Nasdaq-100",
    "Calendrier économique US",
    "Jauge technique",
    "Cotations multi-actifs",
)


def _market_map_script() -> None:
    from nqcockpit.ui.market_map_page import render_market_map_page

    render_market_map_page()


def _visible_text(app: AppTest) -> str:
    parts = [element.value for element in app.markdown]
    parts += [element.value for element in app.caption]
    parts += [element.value for element in app.info]
    parts += [element.value for element in app.warning]
    return " ".join(str(part) for part in parts)


@pytest.mark.parametrize(("lang", "expected"), [("EN", EXPECTED_EN), ("FR", EXPECTED_FR)])
def test_market_map_renders_four_iframes_and_localized_text(
    lang: str, expected: tuple[str, ...]
) -> None:
    app = AppTest.from_function(_market_map_script, default_timeout=60)
    app.session_state["lang"] = lang
    app.run()

    assert not app.exception, app.exception
    assert len(app.get("iframe")) == 4
    text = _visible_text(app)
    assert "ui." not in text, text
    for fragment in expected:
        assert fragment in text, (lang, fragment, text)


def test_nav_lists_market_map_in_en_and_fr() -> None:
    assert "market_map" in page_keys()
    assert LABELS["ui.nav.market_map.name"] == {
        "en": "Market Map",
        "fr": "Carte du marché",
    }
    assert page_name("market_map") == "Market Map"


def _symbol_script() -> None:
    import streamlit as st

    from nqcockpit.ui.market_map_page import technical_symbol

    st.markdown(f"SYMBOL={technical_symbol()}")


def test_market_map_uses_terminal_symbol_then_falls_back() -> None:
    chosen = AppTest.from_function(_symbol_script, default_timeout=30)
    chosen.session_state[SYMBOL_STATE_KEY] = "CAPITALCOM:US100"
    chosen.run()
    assert not chosen.exception, chosen.exception
    assert chosen.markdown[0].value.endswith("CAPITALCOM:US100")

    fallback = AppTest.from_function(_symbol_script, default_timeout=30)
    fallback.session_state[SYMBOL_STATE_KEY] = "NOT_A_SYMBOL"
    fallback.run()
    assert not fallback.exception, fallback.exception
    assert fallback.markdown[0].value.endswith(tv_widgets.DEFAULT_NQ_SYMBOL)
