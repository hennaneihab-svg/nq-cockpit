"""Market Map : carte de chaleur Nasdaq-100 et widgets TradingView de contexte.

Quatre widgets publics TradingView (aucune clé) : la carte de chaleur du
Nasdaq-100 en pleine largeur, puis calendrier économique, jauge technique du
symbole choisi sur le Terminal et cotations multi-actifs. Aucun chiffre n'est
calculé ici : tout vient des widgets ou du choix de l'utilisateur, et la page
peut défiler.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from nqcockpit.ui import sections, tv_widgets
from nqcockpit.ui.i18n import get_lang, label
from nqcockpit.ui.terminal_page import SYMBOL_STATE_KEY

HEATMAP_HEIGHT = 660
PANEL_HEIGHT = 380


def _section_title(key: str) -> None:
    """Titre de section localisé, même style que les autres pages."""
    st.markdown(
        f'<div class="section-title">{escape(label(key))}</div>',
        unsafe_allow_html=True,
    )


def technical_symbol() -> str:
    """Symbole choisi sur le Terminal, sinon le proxy NQ par défaut."""
    symbol = st.session_state.get(SYMBOL_STATE_KEY, tv_widgets.DEFAULT_NQ_SYMBOL)
    if symbol not in tv_widgets.NQ_SYMBOL_OPTIONS:
        return tv_widgets.DEFAULT_NQ_SYMBOL
    return str(symbol)


def render_market_map_page() -> None:
    """Rend la Market Map : carte de chaleur puis trois colonnes de contexte."""
    sections.inject_ui_css()
    sections.render_page_heading("ui.market_map.title", "ui.market_map.desc")
    locale = get_lang().lower()

    _section_title("ui.market_map.heatmap")
    st.caption(label("ui.market_map.heatmap_note"))
    heatmap = tv_widgets.stock_heatmap_html(locale=locale, height=HEATMAP_HEIGHT)
    tv_widgets.render_widget(heatmap, HEATMAP_HEIGHT)

    symbol = technical_symbol()
    calendar_col, technical_col, quotes_col = st.columns(3, gap="medium")
    with calendar_col:
        _section_title("ui.market_map.calendar")
        calendar = tv_widgets.economic_calendar_html(
            locale=locale, height=PANEL_HEIGHT
        )
        tv_widgets.render_widget(calendar, PANEL_HEIGHT)
    with technical_col:
        _section_title("ui.market_map.technical")
        st.caption(label("ui.market_map.symbol_note", symbol=symbol))
        gauge = tv_widgets.technical_analysis_html(
            symbol, locale=locale, height=PANEL_HEIGHT
        )
        tv_widgets.render_widget(gauge, PANEL_HEIGHT)
    with quotes_col:
        _section_title("ui.market_map.quotes")
        quotes = tv_widgets.market_quotes_html(locale=locale, height=PANEL_HEIGHT)
        tv_widgets.render_widget(quotes, PANEL_HEIGHT)

    st.caption(label("ui.market_map.delayed_note"))


__all__ = ["HEATMAP_HEIGHT", "PANEL_HEIGHT", "render_market_map_page", "technical_symbol"]
