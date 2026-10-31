"""Tests des helpers de widgets TradingView (aucun appel réseau)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from nqcockpit.ui import tv_widgets

_SCRIPT_RE = re.compile(
    r'<script[^>]*src="(?P<src>[^"]+)"[^>]*>(?P<body>.*?)</script>',
    re.DOTALL,
)


def _parse(html: str) -> tuple[str, dict[str, Any]]:
    match = _SCRIPT_RE.search(html)
    assert match is not None, "le HTML doit contenir un <script src=...>"
    return match.group("src"), json.loads(match.group("body"))


def test_default_symbol_is_an_option() -> None:
    assert tv_widgets.DEFAULT_NQ_SYMBOL in tv_widgets.NQ_SYMBOL_OPTIONS
    assert len(tv_widgets.NQ_SYMBOL_OPTIONS) >= 2
    assert all(":" in symbol for symbol in tv_widgets.NQ_SYMBOL_OPTIONS)


def test_advanced_chart_html() -> None:
    html = tv_widgets.advanced_chart_html(
        tv_widgets.DEFAULT_NQ_SYMBOL,
        interval="5",
        timezone="America/New_York",
        locale="fr",
        height=500,
    )
    src, config = _parse(html)
    assert src.endswith("embed-widget-advanced-chart.js")
    assert src.startswith("https://s3.tradingview.com/external-embedding/")
    assert config["symbol"] == tv_widgets.DEFAULT_NQ_SYMBOL
    assert config["theme"] == "dark"
    assert config["interval"] == "5"
    assert config["timezone"] == "America/New_York"
    assert config["locale"] == "fr"
    assert config["style"] == "1"
    assert config["allow_symbol_change"] is True
    assert config["hide_side_toolbar"] is False
    assert config["support_host"] == "https://www.tradingview.com"
    assert config["width"] == "100%"
    assert config["height"] == 500
    assert config["autosize"] is False
    assert "height:500px" in html
    assert "tradingview-widget-container__widget" in html
    assert tv_widgets.WIDGET_BACKGROUND in html


def test_advanced_chart_defaults() -> None:
    _, config = _parse(tv_widgets.advanced_chart_html("CAPITALCOM:US100"))
    assert config["symbol"] == "CAPITALCOM:US100"
    assert config["interval"] == "1"
    assert config["timezone"] == "Africa/Algiers"
    assert config["locale"] == "en"


def test_stock_heatmap_html() -> None:
    html = tv_widgets.stock_heatmap_html(locale="fr", height=600)
    src, config = _parse(html)
    assert src.endswith("embed-widget-stock-heatmap.js")
    assert config["colorTheme"] == "dark"
    assert config["locale"] == "fr"
    assert config["dataSource"] == "NASDAQ100"
    assert config["grouping"] == "sector"
    assert config["exchanges"] == []
    assert config["blockSize"] == "market_cap_basic"
    assert config["blockColor"] == "change"
    assert config["hasTopBar"] is False
    assert config["isDatasetEnabled"] is True
    assert config["isZoomEnabled"] is True
    assert config["hasSymbolTooltip"] is True
    assert config["width"] == "100%"


def test_economic_calendar_html() -> None:
    html = tv_widgets.economic_calendar_html(locale="fr", height=480)
    src, config = _parse(html)
    assert src.endswith("embed-widget-events.js")
    assert config["colorTheme"] == "dark"
    assert config["locale"] == "fr"
    assert config["importanceFilter"] == "0,1"
    assert config["countryFilter"] == "us"
    assert "height:480px" in html


def test_technical_analysis_html() -> None:
    html = tv_widgets.technical_analysis_html("CME_MINI:NQ1!", locale="fr", height=400)
    src, config = _parse(html)
    assert src.endswith("embed-widget-technical-analysis.js")
    assert config["symbol"] == "CME_MINI:NQ1!"
    assert config["colorTheme"] == "dark"
    assert config["interval"] == "15m"
    assert config["locale"] == "fr"
    assert config["showIntervalTabs"] is True
    assert config["isTransparent"] is True
    assert config["width"] == "100%"
    assert "height:400px" in html


def test_market_quotes_html() -> None:
    html = tv_widgets.market_quotes_html(locale="fr", height=380)
    src, config = _parse(html)
    assert src.endswith("embed-widget-market-quotes.js")
    assert config["colorTheme"] == "dark"
    assert config["locale"] == "fr"
    assert config["width"] == "100%"
    symbols = [item["name"] for group in config["symbolsGroups"] for item in group["symbols"]]
    assert symbols == [item["name"] for item in tv_widgets.QUOTE_SYMBOLS]
    assert symbols
    assert all(":" in symbol for symbol in symbols)
    assert all(
        item["displayName"].strip()
        for group in config["symbolsGroups"]
        for item in group["symbols"]
    )
    assert "height:380px" in html


def test_build_widget_html_generic() -> None:
    html = tv_widgets.build_widget_html(
        "embed-widget-symbol-overview.js",
        {"symbols": [["NASDAQ:NDX|1D"]], "colorTheme": "dark", "locale": "en"},
        300,
    )
    src, config = _parse(html)
    assert src == "https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js"
    assert config["symbols"] == [["NASDAQ:NDX|1D"]]
    assert config["colorTheme"] == "dark"
    assert config["locale"] == "en"
    assert "height:300px" in html
    assert html.count("height:300px") >= 2
    assert "height:100%;width:100%" not in html
    assert 'class="tradingview-widget-container__widget"' in html


def test_background_is_dark() -> None:
    html = tv_widgets.advanced_chart_html(tv_widgets.DEFAULT_NQ_SYMBOL)
    assert tv_widgets.WIDGET_BACKGROUND == "#0B1220"
    assert f"background:{tv_widgets.WIDGET_BACKGROUND}" in html


def test_every_widget_returns_parsable_html() -> None:
    widgets = [
        tv_widgets.advanced_chart_html(tv_widgets.DEFAULT_NQ_SYMBOL),
        tv_widgets.stock_heatmap_html(),
        tv_widgets.economic_calendar_html(),
        tv_widgets.technical_analysis_html(tv_widgets.DEFAULT_NQ_SYMBOL),
        tv_widgets.market_quotes_html(),
    ]
    for html in widgets:
        assert isinstance(html, str)
        assert "tradingview-widget-container" in html
        src, config = _parse(html)
        assert src.startswith("https://s3.tradingview.com/external-embedding/embed-widget-")
        assert config["locale"] == "en"
        assert config.get("colorTheme", config.get("theme")) == "dark"


def _widget_script() -> None:
    from nqcockpit.ui import tv_widgets

    tv_widgets.render_widget(
        tv_widgets.advanced_chart_html(tv_widgets.DEFAULT_NQ_SYMBOL, height=200),
        200,
    )


def test_render_widget_uses_supported_streamlit_api() -> None:
    import inspect

    source = inspect.getsource(tv_widgets.render_widget)
    assert "st.iframe(" in source
    assert "height=height" in source
    assert 'width="stretch"' in source
    assert "components.html" not in source


def test_render_widget_renders_in_apptest() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_function(_widget_script, default_timeout=30)
    app.run()
    assert not app.exception, app.exception
    assert len(app.get("iframe")) == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
