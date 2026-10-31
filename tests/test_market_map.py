"""Tests de la page Market Map : quatre widgets TradingView, EN et FR."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from nqcockpit.ui import tv_widgets
from nqcockpit.ui.i18n import LABELS
from nqcockpit.ui.nav import page_keys, page_name

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


def test_market_map_gauge_uses_verified_ndx_symbol() -> None:
    from pathlib import Path

    from nqcockpit.ui import market_map_page

    assert tv_widgets.TECHNICAL_ANALYSIS_SYMBOL == "NASDAQ:NDX"
    source = Path(market_map_page.__file__).read_text(encoding="utf-8")
    assert "TECHNICAL_ANALYSIS_SYMBOL" in source
    assert "SYMBOL_STATE_KEY" not in source


def test_market_map_quotes_full_width_and_taller() -> None:
    """Le bandeau de cotations occupe sa propre ligne pleine largeur.

    Rangée 1 : calendrier + jauge (2 colonnes). Rangée 2 : cotations seules,
    assez hautes pour afficher les 8 lignes sans défilement interne.
    """
    from pathlib import Path

    from nqcockpit.ui import market_map_page

    assert 420 <= market_map_page.QUOTES_PANEL_HEIGHT <= 460

    source = Path(market_map_page.__file__).read_text(encoding="utf-8")
    # Plus aucune disposition à 3 colonnes : calendrier et jauge à deux.
    assert "st.columns(2" in source
    assert "st.columns(3" not in source
    # Le widget de cotations utilise sa hauteur dédiée (pleine largeur).
    assert "QUOTES_PANEL_HEIGHT" in source
    assert "quotes_col" not in source
