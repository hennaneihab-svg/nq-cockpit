"""Composants UI partagés et Design System NQ Cockpit (Tokens Swetrix).

Fournit des composants réutilisables basés sur le design system Swetrix :
- Badges de statut Swetrix Badge.tsx (OK, DÉGRADÉ, BLOQUÉ, NO-TRADE) à anneau fin
- Bandeau d'alerte DÉGRADÉ haute lisibilité sans emoji
- Cartes métriques type SaaS/Dashboard avec typographie soignée et alignement net
"""

from __future__ import annotations

import streamlit as st

from nqcockpit.ui.i18n import t, tr_text

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
        {label_part}SYSTEM // {tr_text(norm_status)}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_degraded_banner(warnings: list[str]) -> None:
    """Affiche un bandeau d'avertissement DÉGRADÉ style Swetrix Alert sans emoji."""
    if not warnings:
        return

    warn_html = "".join(
        [f"<li style='margin-bottom: 2px;'>{tr_text(w)}</li>" for w in warnings]
    )
    banner_title = t(
        "[AVERTISSEMENT DE SANTÉ DES SOURCES — STATUT DÉGRADÉ]",
        "[SOURCE HEALTH WARNING — DEGRADED STATUS]",
    )
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
            {banner_title}
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

