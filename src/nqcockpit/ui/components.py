"""Composants UI partagés et Design System NQ Cockpit.

Fournit des composants réutilisables à fort contraste pour l'interface multipage :
- Badges de statut (OK, DÉGRADÉ, BLOQUÉ, NO-TRADE)
- Métriques au format terminal
- Bannières d'avertissement de santé des sources
"""

from __future__ import annotations

import streamlit as st

STATUS_COLORS = {
    "OK": "#3fb950",
    "DEGRADED": "#d29922",
    "DÉGRADÉ": "#d29922",
    "BLOCKED": "#f85149",
    "BLOQUÉ": "#f85149",
    "NO_TRADE": "#a371f7",
    "NO-TRADE": "#a371f7",
}


def render_status_badge(status: str, label: str = "") -> None:
    """Affiche un badge de statut haute visibilité avec couleur sémantique."""
    norm_status = status.upper().strip()
    color = STATUS_COLORS.get(norm_status, "#8b949e")

    html = f"""
    <div style="
        display: inline-block;
        background-color: {color}22;
        border: 2px solid {color};
        color: {color};
        border-radius: 6px;
        padding: 6px 14px;
        font-family: monospace;
        font-weight: bold;
        font-size: 1.1rem;
        text-align: center;
        margin-bottom: 8px;
    ">
        {f'<b>{label}</b> : ' if label else ''}{norm_status}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_degraded_banner(warnings: list[str]) -> None:
    """Affiche un bandeau visible DÉGRADÉ en cas de source manquante ou périmée.

    Garantit que le statut dégradé n'est jamais masqué ni atténué par le thème.
    """
    if not warnings:
        return

    warn_html = "".join([f"<li>{w}</li>" for w in warnings])
    html = f"""
    <div style="
        background-color: #d2992222;
        border: 2px solid #d29922;
        color: #f0883e;
        border-radius: 8px;
        padding: 12px 18px;
        margin: 10px 0 18px 0;
        font-family: monospace;
    ">
        <div style="font-size: 1.1rem; font-weight: bold; margin-bottom: 4px;">
            ⚠️ STATUT DÉGRADÉ — SOURCE(S) MANQUANTE(S) OU DÉFAILLANTE(S)
        </div>
        <ul style="margin: 4px 0 0 18px; padding: 0;">
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
    """Affiche une carte métrique typée terminal de trading."""
    color_map = {
        "ok": "#3fb950",
        "warn": "#d29922",
        "error": "#f85149",
        "neutral": "#e6edf3",
        "insufficient": "#8b949e",
    }
    val_color = color_map.get(status_kind, "#e6edf3")

    html = f"""
    <div style="
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 4px 0;
        font-family: monospace;
    ">
        <div style="font-size: 0.8rem; color: #8b949e; text-transform: uppercase;">
            {label}
        </div>
        <div style="font-size: 1.4rem; font-weight: bold; color: {val_color}; margin: 4px 0;">
            {value}
        </div>
        {f'<div style="font-size: 0.8rem; color: #8b949e;">{subtext}</div>' if subtext else ''}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
