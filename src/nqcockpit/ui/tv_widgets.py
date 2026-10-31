"""Widgets TradingView gratuits intégrés dans le cockpit.

Chaque fonction retourne une chaîne HTML autonome destinée à
``st.components.v1.html``. Les widgets utilisent les scripts d'embed public de
TradingView (aucune clé, aucun service payant) et le thème sombre du cockpit.
"""

from __future__ import annotations

import json
from typing import Any

# Couleur de fond sombre du cockpit (voir ``sections.py`` / ``chart.py``).
WIDGET_BACKGROUND = "#0B1220"

_EMBED_BASE_URL = "https://s3.tradingview.com/external-embedding/"

NQ_SYMBOL_OPTIONS = ("NASDAQ:NDX", "CAPITALCOM:US100", "CME_MINI:NQ1!")
DEFAULT_NQ_SYMBOL = "NASDAQ:NDX"


def build_widget_html(script_name: str, config: dict[str, Any], height: int) -> str:
    """Construit le markup standard d'un widget d'embed TradingView.

    Args:
        script_name: Nom du script d'embed, par exemple
            ``"embed-widget-advanced-chart.js"``.
        config: Configuration du widget, sérialisée en JSON dans le corps du
            script.
        height: Hauteur du conteneur en pixels.

    Returns:
        Le HTML complet du widget, prêt pour ``st.components.v1.html``.
    """
    body = json.dumps(config, ensure_ascii=False)
    return (
        "<style>"
        f"html,body{{margin:0;padding:0;background:{WIDGET_BACKGROUND};}}"
        "</style>"
        '<div class="tradingview-widget-container" '
        f'style="height:{height}px;width:100%;background:{WIDGET_BACKGROUND};">'
        '<div class="tradingview-widget-container__widget" '
        'style="height:100%;width:100%;"></div>'
        '<script type="text/javascript" '
        f'src="{_EMBED_BASE_URL}{script_name}" async>'
        f"{body}"
        "</script>"
        "</div>"
    )


def advanced_chart_html(
    symbol: str,
    interval: str = "1",
    timezone: str = "Africa/Algiers",
    locale: str = "en",
    height: int = 620,
) -> str:
    """Graphique avancé TradingView pour ``symbol``.

    Args:
        symbol: Symbole TradingView (par exemple ``NASDAQ:NDX``).
        interval: Intervalle de bougies (``"1"`` = 1 minute).
        timezone: Fuseau d'affichage du graphique.
        locale: Langue de l'interface du widget.
        height: Hauteur du conteneur en pixels.

    Returns:
        Le HTML du widget.
    """
    config: dict[str, Any] = {
        "autosize": True,
        "symbol": symbol,
        "interval": interval,
        "timezone": timezone,
        "theme": "dark",
        "style": "1",
        "locale": locale,
        "width": "100%",
        "allow_symbol_change": True,
        "hide_side_toolbar": False,
        "support_host": "https://www.tradingview.com",
    }
    return build_widget_html("embed-widget-advanced-chart.js", config, height)


def stock_heatmap_html(locale: str = "en", height: int = 700) -> str:
    """Carte de chaleur des actions du NASDAQ 100.

    Args:
        locale: Langue de l'interface du widget.
        height: Hauteur du conteneur en pixels.

    Returns:
        Le HTML du widget.
    """
    config: dict[str, Any] = {
        "exchanges": [],
        "dataSource": "NASDAQ100",
        "grouping": "sector",
        "blockSize": "market_cap_basic",
        "blockColor": "change",
        "colorTheme": "dark",
        "hasTopBar": False,
        "isDatasetEnabled": True,
        "isZoomEnabled": True,
        "hasSymbolTooltip": True,
        "locale": locale,
        "width": "100%",
    }
    return build_widget_html("embed-widget-stock-heatmap.js", config, height)


def economic_calendar_html(locale: str = "en", height: int = 500) -> str:
    """Calendrier économique TradingView (événements US importants).

    Args:
        locale: Langue de l'interface du widget.
        height: Hauteur du conteneur en pixels.

    Returns:
        Le HTML du widget.
    """
    config: dict[str, Any] = {
        "colorTheme": "dark",
        "isTransparent": False,
        "width": "100%",
        "height": height,
        "locale": locale,
        "importanceFilter": "0,1",
        "countryFilter": "us",
    }
    return build_widget_html("embed-widget-events.js", config, height)


def technical_analysis_html(
    symbol: str,
    locale: str = "en",
    height: int = 450,
) -> str:
    """Analyse technique TradingView pour ``symbol``.

    Args:
        symbol: Symbole TradingView (par exemple ``NASDAQ:NDX``).
        locale: Langue de l'interface du widget.
        height: Hauteur du conteneur en pixels.

    Returns:
        Le HTML du widget.
    """
    config: dict[str, Any] = {
        "interval": "15m",
        "width": "100%",
        "isTransparent": True,
        "height": height,
        "symbol": symbol,
        "showIntervalTabs": True,
        "colorTheme": "dark",
        "locale": locale,
    }
    return build_widget_html("embed-widget-technical-analysis.js", config, height)


def market_quotes_html(locale: str = "en", height: int = 420) -> str:
    """Bandeau de cotations des références macro du cockpit.

    Args:
        locale: Langue de l'interface du widget.
        height: Hauteur du conteneur en pixels.

    Returns:
        Le HTML du widget.
    """
    config: dict[str, Any] = {
        "width": "100%",
        "height": height,
        "symbolsGroups": [
            {
                "name": "Références",
                "originalName": "Références",
                "symbols": [
                    {"name": "NASDAQ:NDX", "displayName": "NDX"},
                    {"name": "CME_MINI:ES1!", "displayName": "ES1!"},
                    {"name": "CBOE:VIX", "displayName": "VIX"},
                    {"name": "TVC:DXY", "displayName": "DXY"},
                    {"name": "TVC:US10Y", "displayName": "US10Y"},
                ],
            }
        ],
        "colorTheme": "dark",
        "locale": locale,
    }
    return build_widget_html("embed-widget-market-quotes.js", config, height)
