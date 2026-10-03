"""Composants UI partagés et Design System NQ Cockpit (Tokens Swetrix).

Fournit des composants réutilisables basés sur le design system Swetrix :
- Badges de statut Swetrix Badge.tsx (OK, DÉGRADÉ, BLOQUÉ, NO-TRADE) à anneau fin
- Bandeau d'alerte DÉGRADÉ haute lisibilité sans emoji
- Cartes métriques type SaaS/Dashboard avec typographie soignée et alignement net
- Widget TradingView Advanced Chart plein écran (hauteur 880px, pleine largeur conteneur)
"""

from __future__ import annotations

import streamlit as st

# Palette sémantique extraite de Swetrix (Badge.tsx & Text.tsx en mode sombre)
STATUS_COLORS = {
    "OK": {
        "text": "#6EE7B7",
        "border": "rgba(16, 185, 129, 0.25)",
        "bg": "rgba(16, 185, 129, 0.10)",
    },
    "GO": {
        "text": "#6EE7B7",
        "border": "rgba(16, 185, 129, 0.25)",
        "bg": "rgba(16, 185, 129, 0.10)",
    },
    "READY": {
        "text": "#6EE7B7",
        "border": "rgba(16, 185, 129, 0.25)",
        "bg": "rgba(16, 185, 129, 0.10)",
    },
    "DEGRADED": {
        "text": "#FCD34D",
        "border": "rgba(251, 191, 36, 0.25)",
        "bg": "rgba(251, 191, 36, 0.10)",
    },
    "DÉGRADÉ": {
        "text": "#FCD34D",
        "border": "rgba(251, 191, 36, 0.25)",
        "bg": "rgba(251, 191, 36, 0.10)",
    },
    "WARN": {
        "text": "#FCD34D",
        "border": "rgba(251, 191, 36, 0.25)",
        "bg": "rgba(251, 191, 36, 0.10)",
    },
    "BLOCKED": {
        "text": "#FCA5A5",
        "border": "rgba(248, 113, 113, 0.25)",
        "bg": "rgba(248, 113, 113, 0.10)",
    },
    "BLOQUÉ": {
        "text": "#FCA5A5",
        "border": "rgba(248, 113, 113, 0.25)",
        "bg": "rgba(248, 113, 113, 0.10)",
    },
    "STOP": {
        "text": "#FCA5A5",
        "border": "rgba(248, 113, 113, 0.25)",
        "bg": "rgba(248, 113, 113, 0.10)",
    },
    "NO_TRADE": {
        "text": "#A5B4FC",
        "border": "rgba(129, 140, 248, 0.30)",
        "bg": "rgba(129, 140, 248, 0.10)",
    },
    "NO-TRADE": {
        "text": "#A5B4FC",
        "border": "rgba(129, 140, 248, 0.30)",
        "bg": "rgba(129, 140, 248, 0.10)",
    },
}


def render_status_badge(status: str, label: str = "") -> None:
    """Affiche un badge de statut au format Swetrix (rounded-md, ring-1, fond translucide)."""
    norm_status = status.upper().strip()
    cfg = STATUS_COLORS.get(
        norm_status,
        {
            "text": "#CBD5E1",
            "border": "rgba(148, 163, 184, 0.20)",
            "bg": "rgba(148, 163, 184, 0.10)",
        },
    )
    color_text = cfg["text"]
    color_border = cfg["border"]
    color_bg = cfg["bg"]

    label_part = (
        f'<span style="color: #94A3B8; margin-right: 4px;">{label}:</span>'
        if label
        else ""
    )

    html = f"""
    <div style="
        display: inline-flex;
        align-items: center;
        background-color: {color_bg};
        border: 1px solid {color_border};
        color: {color_text};
        border-radius: 6px;
        padding: 4px 10px;
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-weight: 600;
        font-size: 0.78rem;
        letter-spacing: 0.02em;
        margin-bottom: 6px;
    ">
        {label_part}SYSTEM // {norm_status}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_degraded_banner(warnings: list[str]) -> None:
    """Affiche un bandeau d'avertissement DÉGRADÉ style Swetrix Alert sans emoji."""
    if not warnings:
        return

    warn_html = "".join([f"<li style='margin-bottom: 2px;'>{w}</li>" for w in warnings])
    html = f"""
    <div style="
        background-color: rgba(251, 191, 36, 0.08);
        border: 1px solid rgba(251, 191, 36, 0.25);
        color: #FCD34D;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 10px 0 16px 0;
        font-family: -apple-system, system-ui, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 0.82rem;
        line-height: 1.45;
    ">
        <div style="font-weight: 600; font-family: ui-monospace, monospace; margin-bottom: 4px;">
            [AVERTISSEMENT DE SANTÉ DES SOURCES — STATUT DÉGRADÉ]
        </div>
        <ul style="margin: 4px 0 0 18px; padding: 0; font-family: ui-monospace, monospace;">
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
    """Affiche une carte métrique style Swetrix MetricCard (rounded-lg, bordure slate-800)."""
    color_map = {
        "ok": "#6EE7B7",
        "pos": "#6EE7B7",
        "warn": "#FCD34D",
        "deg": "#FCD34D",
        "error": "#FCA5A5",
        "neg": "#FCA5A5",
        "neutral": "#F8FAFC",
        "insufficient": "#94A3B8",
    }
    val_color = color_map.get(status_kind, "#F8FAFC")

    sub_html = (
        f'<div style="font-size: 0.75rem; color: #94A3B8; margin-top: 3px;'
        f' font-family: -apple-system, sans-serif;">{subtext}</div>'
        if subtext
        else ""
    )
    html = f"""
    <div style="
        background-color: #0F172A;
        border: 1px solid rgba(51, 65, 85, 0.6);
        border-radius: 8px;
        padding: 14px 16px;
        margin: 4px 0;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    ">
        <div style="
            font-size: 0.72rem;
            color: #94A3B8;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
            font-family: -apple-system, system-ui, sans-serif;
        ">
            {label}
        </div>
        <div style="
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 1.45rem;
            font-weight: 700;
            color: {val_color};
            line-height: 1.2;
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
    symbol: str = "CME:NQ1!",
    height: int = 880,
    force_offline: bool = False,
) -> None:
    """Rendu du widget TradingView Advanced Chart (Pleine largeur, Swetrix dark tokens).

    - Gratuit, sans clé API ni dépendance externe payante.
    - Hauteur portée à 880px pour confort d'analyse.
    - Pleine largeur du conteneur parent sans limitation de largeur fixe.
    - Dégradation gracieuse offline visible.
    - Strictement visuel : aucune donnée du widget n'alimente la logique métier.
    """
    import streamlit.components.v1 as components

    if force_offline or not is_tradingview_reachable():
        st.markdown(
            """
            <div style="
                background-color: rgba(251, 191, 36, 0.08);
                border: 1px solid rgba(251, 191, 36, 0.25);
                color: #FCD34D;
                border-radius: 8px;
                padding: 14px 18px;
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
    <!DOCTYPE html>
    <html lang="fr" style="height: 100%; width: 100%; margin: 0; padding: 0;">
    <head>
      <meta charset="utf-8">
      <style>
        * {{ box-sizing: border-box; }}
        html, body {{
          margin: 0 !important;
          padding: 0 !important;
          width: 100% !important;
          height: 100% !important;
          background-color: #0F172A !important;
          overflow: hidden !important;
        }}
        .tradingview-widget-container {{
          width: 100% !important;
          height: 100% !important;
          display: flex !important;
          flex-direction: column !important;
          border-radius: 8px;
          overflow: hidden;
        }}
        #tradingview_advanced_chart {{
          width: 100% !important;
          height: calc(100% - 28px) !important;
          flex: 1 1 auto !important;
        }}
        .tradingview-widget-copyright {{
          height: 28px !important;
          line-height: 28px !important;
          padding: 0 12px !important;
          font-family: ui-monospace, SFMono-Regular, monospace !important;
          font-size: 11px !important;
          background-color: #0F172A !important;
          border-top: 1px solid rgba(51, 65, 85, 0.4) !important;
        }}
      </style>
    </head>
    <body>
      <div class="tradingview-widget-container">
        <div id="tradingview_advanced_chart"></div>
        <div class="tradingview-widget-copyright">
          <a href="https://fr.tradingview.com/" rel="noopener nofollow" target="_blank"
             style="color: #6366F1; text-decoration: none; font-weight: 500;">
            <span class="blue-text">Powered by TradingView</span>
          </a>
        </div>
        <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
        <script type="text/javascript">
        new TradingView.widget(
        {{
          "autosize": true,
          "width": "100%",
          "height": "100%",
          "symbol": "{symbol}",
          "interval": "5",
          "timezone": "America/New_York",
          "theme": "dark",
          "style": "1",
          "locale": "fr",
          "enable_publishing": false,
          "allow_symbol_change": true,
          "container_id": "tradingview_advanced_chart",
          "backgroundColor": "#0F172A",
          "gridColor": "rgba(51, 65, 85, 0.3)"
        }}
        );
        </script>
      </div>
    </body>
    </html>
    """
    components.html(widget_html, height=height)
