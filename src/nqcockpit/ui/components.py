"""Composants UI partagés et Design System NQ Cockpit (Fusion Bloomberg x TradingView).

Fournit des composants réutilisables à haute visibilité et densité de desk :
- Badges de statut en contours 1px (OK, DÉGRADÉ, BLOQUÉ, NO-TRADE) sans fond saturé
- Bandeau d'avertissement DÉGRADÉ haute lisibilité sans emoji
- Cartes métriques type terminal avec typographie tabulaire
"""

from __future__ import annotations

import streamlit as st

# Palette sémantique Bloomberg x TradingView
STATUS_COLORS = {
    "OK": {"text": "#089981", "border": "#089981aa"},
    "GO": {"text": "#089981", "border": "#089981aa"},
    "READY": {"text": "#089981", "border": "#089981aa"},
    "DEGRADED": {"text": "#D29922", "border": "#D29922aa"},
    "DÉGRADÉ": {"text": "#D29922", "border": "#D29922aa"},
    "WARN": {"text": "#D29922", "border": "#D29922aa"},
    "BLOCKED": {"text": "#F23645", "border": "#F23645aa"},
    "BLOQUÉ": {"text": "#F23645", "border": "#F23645aa"},
    "STOP": {"text": "#F23645", "border": "#F23645aa"},
    "NO_TRADE": {"text": "#7E57C2", "border": "#7E57C2aa"},
    "NO-TRADE": {"text": "#7E57C2", "border": "#7E57C2aa"},
}


def render_status_badge(status: str, label: str = "") -> None:
    """Affiche un badge de statut en contour 1px désaturé sans bloc de couleur plein."""
    norm_status = status.upper().strip()
    cfg = STATUS_COLORS.get(norm_status, {"text": "#787B86", "border": "#2A2E39"})
    color_text = cfg["text"]
    color_border = cfg["border"]

    html = f"""
    <div style="
        display: inline-block;
        background-color: #131722;
        border: 1px solid {color_border};
        color: {color_text};
        border-radius: 3px;
        padding: 4px 10px;
        font-family: ui-monospace, SFMono-Regular, 'JetBrains Mono', Consolas, monospace;
        font-weight: 700;
        font-size: 0.8rem;
        letter-spacing: 0.5px;
        text-align: center;
        margin-bottom: 6px;
    ">
        {f'<span style="color: #787B86;">{label}: </span>' if label else ''}SYSTEM // {norm_status}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_degraded_banner(warnings: list[str]) -> None:
    """Affiche un bandeau visible DÉGRADÉ à fort contraste sans emoji ni saturation criarde."""
    if not warnings:
        return

    warn_html = "".join([f"<li>{w}</li>" for w in warnings])
    html = f"""
    <div style="
        background-color: #181512;
        border: 1px solid #D29922;
        color: #D29922;
        border-radius: 3px;
        padding: 10px 14px;
        margin: 10px 0 16px 0;
        font-family: ui-sans-serif, -apple-system, sans-serif;
        font-size: 0.82rem;
        line-height: 1.4;
    ">
        <div style="font-weight: 700; font-family: monospace; margin-bottom: 4px;">
            [AVERTISSEMENT DE SANTÉ DES SOURCES — STATUT DÉGRADÉ]
        </div>
        <ul style="margin: 4px 0 0 16px; padding: 0; font-family: ui-monospace, monospace;">
            {warn_html}
        </ul>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_terminal_metric(
    label: str,
    value: str,
    subtext: str = "",
    status_kind: str = "neutral",
) -> None:
    """Affiche une carte métrique typée terminal de trading avec typographie tabulaire."""
    color_map = {
        "ok": "#089981",
        "pos": "#089981",
        "warn": "#D29922",
        "deg": "#D29922",
        "error": "#F23645",
        "neg": "#F23645",
        "neutral": "#D1D4DC",
        "insufficient": "#787B86",
    }
    val_color = color_map.get(status_kind, "#D1D4DC")

    sub_html = (
        f'<div style="font-family: monospace; font-size: 0.72rem; color: #787B86;">'
        f'{subtext}</div>'
        if subtext
        else ''
    )
    html = f"""
    <div style="
        background-color: #131722;
        border: 1px solid #2A2E39;
        border-radius: 3px;
        padding: 10px 12px;
        margin: 4px 0;
    ">
        <div style="
            font-family: ui-sans-serif, -apple-system, sans-serif;
            font-size: 0.72rem;
            color: #787B86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        ">
            {label}
        </div>
        <div style="
            font-family: ui-monospace, SFMono-Regular, 'JetBrains Mono', Consolas, monospace;
            font-size: 1.3rem;
            font-weight: 700;
            color: {val_color};
            margin: 4px 0 2px 0;
        ">
            {value}
        </div>
        {sub_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def is_tradingview_reachable(
    host: str = "s3.tradingview.com",
    port: int = 443,
    timeout: float = 1.5,
) -> bool:
    """Vérifie la joignabilité réseau des serveurs du widget TradingView."""
    import socket
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


def render_tradingview_chart(
    symbol: str = "CME_MINI:NQ1!",
    height: int = 500,
    force_offline: bool = False,
) -> None:
    """Rendu du widget TradingView Advanced Chart avec dégradation gracieuse offline.

    - Gratuit, sans clé API ni dépendance externe payante.
    - Attribution 'Powered by TradingView' conservée.
    - Thème sombre aligné sur Bloomberg x TradingView (#131722).
    - Strictement visuel : aucune donnée du widget n'alimente la logique métier.
    """
    import streamlit.components.v1 as components

    if force_offline or not is_tradingview_reachable():
        st.markdown(
            """
            <div style="
                background-color: #181512;
                border: 1px solid #D29922;
                color: #D29922;
                border-radius: 3px;
                padding: 12px 16px;
                margin: 10px 0;
                font-family: ui-monospace, monospace;
                font-size: 0.85rem;
                font-weight: 600;
            ">
                [DÉGRADÉ] Graphique TradingView indisponible — vérifier la connexion internet
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    widget_html = f"""
    <div class="tradingview-widget-container" style="height:100%;width:100%;">
      <div id="tradingview_advanced_chart" style="height:calc(100% - 32px);width:100%;"></div>
      <div class="tradingview-widget-copyright" style="font-family: monospace; font-size: 11px;">
        <a href="https://fr.tradingview.com/" rel="noopener nofollow" target="_blank"
           style="color: #FA7900; text-decoration: none;">
          <span class="blue-text">Powered by TradingView</span>
        </a>
      </div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget(
      {{
        "autosize": true,
        "symbol": "{symbol}",
        "interval": "5",
        "timezone": "America/New_York",
        "theme": "dark",
        "style": "1",
        "locale": "fr",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_advanced_chart",
        "backgroundColor": "#131722",
        "gridColor": "#2A2E39"
      }}
      );
      </script>
    </div>
    """
    components.html(widget_html, height=height)

