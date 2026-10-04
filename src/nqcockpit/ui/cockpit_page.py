"""Page principale Streamlit NQ Cockpit (P08 / P13 / Dashboard).

Design System calme, dense et mat :
- Vue globale synoptique lisible sans éblouissement (Slate-950 / Zinc-800).
- Strictement non-directionnel : gestion du risque, régimes de volatilité, expected moves.
- Animations courtes et discrètes : entrée échelonnée 280ms, pulse LIVE sobre 2,4s si OK,
  flash de rafraîchissement 600ms, survol 150ms.
- Radar Macro 6 fenêtres (Taux US, Inflation, Mega-Caps, Fed, Pétrole, Dollar).
- Aucune donnée inventée : statut DÉGRADÉ affiché explicitement avec son âge.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.config import load_config
from nqcockpit.macro.news_radar import (
    MacroRadarCard,
    NewsWireItem,
    fetch_live_news_wire,
    fetch_macro_news_radar,
)
from nqcockpit.profile.engine import build_day_profile, export_levels_to_csv

log = logging.getLogger(__name__)

TZ_ALGIERS = ZoneInfo("Africa/Algiers")
TZ_ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def _render_wire_item_html(item: NewsWireItem, delay_idx: int) -> str:
    """Génère le fragment HTML d'une dépêche d'actualité en direct."""
    dot_html = '<span class="live-dot" title="Dépêche récente"></span>'
    return (
        f'<div class="news-wire-card animate-enter delay-{delay_idx}">'
        f'<div class="news-wire-header">'
        f'<span class="wire-tag" style="color: {item.tag_color};">{item.tag}</span>'
        f'<span class="wire-source">{dot_html}{item.source}</span>'
        f'</div>'
        f'<div class="wire-title">'
        f'<a href="{item.link}" target="_blank" rel="noopener noreferrer">{item.title}</a>'
        f'</div>'
        f'<div class="wire-footer">'
        f'<span>Alger : {item.timestamp_algiers_str} | NY : {item.timestamp_et_str}</span>'
        f'<span>Âge : <b>{item.age_str}</b></span>'
        f'</div>'
        f'</div>'
    )


def _render_radar_card_html(card: MacroRadarCard, delay_idx: int) -> str:
    """Génère le fragment HTML d'une carte macro avec ses animations et statuts."""
    if card.is_ok:
        status_pill_cls = "pill-ok"
        dot_html = '<span class="live-dot" title="Donnée active en direct"></span>'
        deg_card_cls = ""
        alert_html = ""
    else:
        status_pill_cls = "pill-deg"
        dot_html = '<span class="deg-dot" title="Flux dégradé ou clôture différée"></span>'
        deg_card_cls = "degraded"
        reason = card.degraded_reason or "Source indisponible ou marché fermé"
        alert_html = (
            f'<div class="news-alert">'
            f"<b>[DÉGRADÉ]</b> {reason}"
            f"</div>"
        )

    return (
        f'<div class="news-card animate-enter delay-{delay_idx} {deg_card_cls}">'
        f'<div class="news-card-header">'
        f'<span class="news-card-title">{card.category} · {card.title}</span>'
        f'<span class="news-pill {status_pill_cls}">{dot_html}{card.status}</span>'
        f'</div>'
        f'<div class="news-body">'
        f'<div class="news-kpi refresh-flash">{card.main_value}</div>'
        f'<div class="news-desc">{card.sub_value}</div>'
        f'</div>'
        f'<div class="news-footer">'
        f'<div><b>Source :</b> {card.source}</div>'
        f'<div><b>Horodatages :</b> {card.timestamp_algiers_str} | {card.timestamp_et_str}</div>'
        f'<div><b>Âge :</b> {card.age_str}</div>'
        f'{alert_html}'
        f'</div>'
        f'</div>'
    )


def render_cockpit():
    """Rendu complet de la page Cockpit."""
    try:
        st.set_page_config(
            page_title="NQ Cockpit — Profil de Séance & Radar Macro",
            layout="wide",
            initial_sidebar_state="collapsed",
        )
    except StreamlitAPIException:
        pass

    # Injection CSS : Thème mat Slate-950 / Zinc-800 & Animations validées
    st.markdown(
        """
        <style>
        :root {
            --bg-canvas: #090D16;
            --bg-surface: #111827;
            --bg-surface-elevated: #161F30;
            --border-subtle: #1E293B;
            --border-focus: #334155;
            --text-primary: #E2E8F0;
            --text-secondary: #94A3B8;
            --text-muted: #8091A5;
            --status-ok-bg: rgba(6, 78, 59, 0.25);
            --status-ok-border: #065F46;
            --status-ok-text: #10B981;
            --status-deg-bg: rgba(69, 26, 3, 0.35);
            --status-deg-border: #78350F;
            --status-deg-text: #D97706;
            --status-notrade-bg: rgba(69, 10, 10, 0.35);
            --status-notrade-border: #7F1D1D;
            --status-notrade-text: #EF4444;
        }

        .stApp {
            background-color: var(--bg-canvas);
            color: var(--text-primary);
            font-family: -apple-system, system-ui, BlinkMacSystemFont,
                "Segoe UI", Roboto, sans-serif;
        }
        .block-container {
            padding-top: 1.25rem;
            padding-bottom: 2rem;
            max-width: 98%;
        }

        /* Animations spécifiées */
        @keyframes cardFadeSlideUp {
            from {
                opacity: 0;
                transform: translateY(8px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes livePulseGlow {
            0% {
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.55);
                transform: scale(1);
            }
            50% {
                box-shadow: 0 0 0 4px rgba(16, 185, 129, 0);
                transform: scale(1.08);
            }
            100% {
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
                transform: scale(1);
            }
        }

        @keyframes valueRefreshFlash {
            0% {
                background-color: rgba(59, 130, 246, 0.3);
                color: #93C5FD;
            }
            100% {
                background-color: transparent;
            }
        }

        .animate-enter {
            animation: cardFadeSlideUp 280ms cubic-bezier(0.16, 1, 0.3, 1) both;
        }
        .delay-0  { animation-delay: 0ms; }
        .delay-1  { animation-delay: 40ms; }
        .delay-2  { animation-delay: 80ms; }
        .delay-3  { animation-delay: 120ms; }
        .delay-4  { animation-delay: 160ms; }
        .delay-5  { animation-delay: 200ms; }
        .delay-6  { animation-delay: 240ms; }
        .delay-7  { animation-delay: 280ms; }
        .delay-8  { animation-delay: 320ms; }
        .delay-9  { animation-delay: 360ms; }
        .delay-10 { animation-delay: 400ms; }
        .delay-11 { animation-delay: 440ms; }

        .live-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--status-ok-text);
            animation: livePulseGlow 2400ms ease-in-out infinite;
            margin-right: 6px;
            vertical-align: middle;
        }

        .deg-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--status-deg-text);
            margin-right: 6px;
            vertical-align: middle;
        }

        .refresh-flash {
            display: inline-block;
            padding: 0 4px;
            border-radius: 3px;
            animation: valueRefreshFlash 600ms ease-out both;
        }

        /* Cartes KPIs */
        .kpi-card {
            background-color: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            padding: 12px 14px;
            margin-bottom: 10px;
            transition: transform 150ms ease-out, border-color 150ms ease-out;
        }
        .kpi-card:hover {
            transform: translateY(-1px);
            border-color: var(--border-focus);
        }
        .kpi-title {
            color: var(--text-muted);
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }
        .kpi-value {
            font-family: ui-monospace, SFMono-Regular, "JetBrains Mono", Consolas, monospace;
            font-size: 1.45rem;
            font-weight: 700;
            color: var(--text-primary);
        }
        .kpi-sub {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 4px;
        }

        /* Bandeau de statut */
        .status-banner-allowed {
            background-color: var(--status-ok-bg);
            border: 1px solid var(--status-ok-border);
            border-radius: 6px;
            padding: 12px 16px;
            margin-bottom: 16px;
            color: var(--text-primary);
        }
        .status-banner-notrade {
            background-color: var(--status-notrade-bg);
            border: 1px solid var(--status-notrade-border);
            border-radius: 6px;
            padding: 12px 16px;
            margin-bottom: 16px;
            color: var(--text-primary);
        }

        /* Puces de santé */
        .chip-ok {
            background-color: var(--status-ok-bg);
            border: 1px solid var(--status-ok-border);
            color: var(--status-ok-text);
            padding: 2px 8px;
            border-radius: 4px;
            font-family: ui-monospace, monospace;
            font-size: 0.75rem;
            font-weight: 600;
            display: inline-block;
            margin-right: 6px;
            margin-bottom: 4px;
        }
        .chip-degraded {
            background-color: var(--status-deg-bg);
            border: 1px solid var(--status-deg-border);
            color: var(--status-deg-text);
            padding: 2px 8px;
            border-radius: 4px;
            font-family: ui-monospace, monospace;
            font-size: 0.75rem;
            font-weight: 600;
            display: inline-block;
            margin-right: 6px;
            margin-bottom: 4px;
        }

        /* Scénarios */
        .scenario-box {
            background-color: var(--bg-surface-elevated);
            border: 1px solid var(--border-subtle);
            border-left: 3px solid #6366F1;
            padding: 12px 16px;
            margin-bottom: 10px;
            border-radius: 0 6px 6px 0;
            font-size: 0.82rem;
            color: var(--text-primary);
        }
        .section-header {
            color: var(--text-primary);
            font-size: 0.95rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
        }

        /* Radar Macro (6 fenêtres) */
        .news-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            padding: 12px 14px;
            margin-bottom: 12px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            min-height: 148px;
            transition: transform 150ms ease-out, border-color 150ms ease-out;
        }
        .news-card:hover {
            transform: translateY(-1px);
            border-color: var(--border-focus);
        }
        .news-card.degraded {
            border-color: var(--status-deg-border);
            background: linear-gradient(180deg, var(--bg-surface) 0%, rgba(69, 26, 3, 0.22) 100%);
        }
        .news-card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
        }
        .news-card-title {
            font-size: 0.72rem;
            font-weight: 700;
            color: var(--text-primary);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .news-pill {
            font-family: ui-monospace, monospace;
            font-size: 0.68rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
            text-transform: uppercase;
            display: inline-flex;
            align-items: center;
        }
        .pill-ok {
            background: var(--status-ok-bg);
            color: var(--status-ok-text);
            border: 1px solid var(--status-ok-border);
        }
        .pill-deg {
            background: var(--status-deg-bg);
            color: var(--status-deg-text);
            border: 1px solid var(--status-deg-border);
        }
        .news-body {
            margin-bottom: 8px;
        }
        .news-kpi {
            font-family: ui-monospace, monospace;
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 3px;
        }
        .news-desc {
            font-size: 0.75rem;
            color: var(--text-secondary);
            line-height: 1.35;
        }
        .news-footer {
            font-family: ui-monospace, monospace;
            font-size: 0.65rem;
            color: var(--text-muted);
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            padding-top: 6px;
            line-height: 1.45;
        }
        .news-footer b {
            color: var(--text-secondary);
        }
        .news-alert {
            margin-top: 4px;
            padding: 3px 6px;
            background: rgba(69, 26, 3, 0.4);
            border-radius: 3px;
            color: var(--status-deg-text);
            font-size: 0.65rem;
        }

        /* Fil d'actualités direct */
        .news-wire-card {
            background-color: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 8px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            transition: transform 150ms ease-out, border-color 150ms ease-out;
        }
        .news-wire-card:hover {
            transform: translateY(-1px);
            border-color: var(--border-focus);
        }
        .news-wire-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .wire-tag {
            font-size: 0.68rem;
            font-weight: 700;
            background: rgba(255, 255, 255, 0.05);
            padding: 2px 6px;
            border-radius: 3px;
            font-family: ui-monospace, monospace;
            text-transform: uppercase;
        }
        .wire-source {
            font-size: 0.72rem;
            color: var(--text-secondary);
            display: inline-flex;
            align-items: center;
        }
        .wire-title {
            font-size: 0.84rem;
            font-weight: 600;
            line-height: 1.35;
        }
        .wire-title a {
            color: var(--text-primary);
            text-decoration: none;
            transition: color 150ms ease;
        }
        .wire-title a:hover {
            color: #93C5FD;
            text-decoration: underline;
        }
        .wire-footer {
            font-family: ui-monospace, monospace;
            font-size: 0.66rem;
            color: var(--text-muted);
            display: flex;
            justify-content: space-between;
            border-top: 1px solid rgba(255, 255, 255, 0.04);
            padding-top: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Chargement de la configuration et des données de profil
    cfg = load_config()
    db_path = Path(cfg.data.db_path)
    conn = None
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

    now_utc = datetime.now(timezone.utc)
    profile = build_day_profile(conn=conn, config=cfg, now_utc=now_utc)
    if conn:
        conn.close()

    # En-tête : Titre & Horodatages multi-fuseaux sans décalage codé en dur
    col_t1, col_t2 = st.columns([2, 1])
    with col_t1:
        st.markdown(
            '<div class="section-header">NQ COCKPIT // PROFIL DE SÉANCE & RADAR MACRO</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Aide à la décision non-directionnelle · Risque événementiel · Cadre d'exécution"
        )
    with col_t2:
        now_alg = now_utc.astimezone(TZ_ALGIERS).strftime("%H:%M:%S")
        now_et = now_utc.astimezone(TZ_ET).strftime("%H:%M:%S")
        st.markdown(
            f"<div class='header-clock' style='text-align: right; font-family: monospace; "
            f"font-size: 0.82rem; line-height: 1.45; padding-top: 4px; "
            f"color: var(--text-secondary);'>"
            f"<b>Alger :</b> {now_alg} | <b>New York :</b> {now_et} ET<br>"
            f"Séance cible : <b>{profile.target_date}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------------
    # 1. BANDEAU DE STATUT EN 5 SECONDES : AUTORISÉ OU NO-TRADE
    # -----------------------------------------------------------------------
    if profile.no_trade.is_trading_allowed:
        st.markdown(
            """
            <div class="status-banner-allowed animate-enter delay-0">
                <span style="font-family: monospace; font-weight: 700; color: #10B981;">
                    SYSTEM // TRADING AUTORISÉ (SOUS CONDITIONS)
                </span><br>
                <span style="font-size: 0.82rem; color: #94A3B8;">
                    Aucun drapeau bloquant actif. Respecter impérativement les Kill Zones d'Alger
                    (15h30–17h00 / 17h00–18h30) et la règle de max 2 trades/jour.
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        reasons_list = [
            f"<li><b>{f.code.value}</b> : {f.reason}</li>"
            for f in profile.no_trade.blocking_flags
        ]
        reasons_html = "".join(reasons_list)
        cnt = profile.no_trade.active_flags_count
        st.markdown(
            f"""
            <div class="status-banner-notrade animate-enter delay-0">
                <span style="font-family: monospace; font-weight: 700; color: #EF4444;">
                    SYSTEM // DRAPEAU NO-TRADE ACTIF ({cnt})
                </span><br>
                <span style="font-size: 0.82rem; color: #94A3B8;">
                    <b>Trading strictement suspendu :</b>
                    <ul style="margin: 4px 0 0 0; padding-left: 20px;">{reasons_html}</ul>
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------------
    # 2. CARTES KPIS EN 4 COLONNES
    # -----------------------------------------------------------------------
    k1, k2, k3, k4 = st.columns(4)

    with k1:
        cd_text = profile.next_tier1_countdown or "Aucun"
        ev_title = profile.next_tier1_event or "Aucun Tier 1 imminent"
        if profile.event_risk_level == "GREEN":
            color_ev = "#10B981"
        elif profile.event_risk_level == "AMBER":
            color_ev = "#D97706"
        else:
            color_ev = "#EF4444"
        st.markdown(
            f"""
            <div class="kpi-card animate-enter delay-1">
                <div class="kpi-title">Prochain Événement Tier 1</div>
                <div class="kpi-value refresh-flash" style="color: {color_ev};">{cd_text}</div>
                <div class="kpi-sub">{ev_title} (Risque {profile.event_risk_level})</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with k2:
        g_color = "#10B981" if profile.gamma_regime == "POSITIVE_GAMMA" else "#EF4444"
        dist_f = (
            f"{profile.distance_to_flip_pts:+.1f} pts"
            if profile.distance_to_flip_pts is not None
            else "N/A"
        )
        st.markdown(
            f"""
            <div class="kpi-card animate-enter delay-2">
                <div class="kpi-title">Régime Gamma (P04)</div>
                <div class="kpi-value refresh-flash" style="color: {g_color};">
                    {profile.gamma_regime}
                </div>
                <div class="kpi-sub">Distance au Flip : <b>{dist_f}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with k3:
        vix_str = f"{profile.vix_level:.2f}" if profile.vix_level else "N/A"
        vxn_str = f"{profile.vxn_level:.2f}" if profile.vxn_level else "N/A"
        st.markdown(
            f"""
            <div class="kpi-card animate-enter delay-3">
                <div class="kpi-title">Régime de Volatilité (P07)</div>
                <div class="kpi-value refresh-flash">{profile.volatility_regime}</div>
                <div class="kpi-sub">VIX : <b>{vix_str}</b> | VXN : <b>{vxn_str}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with k4:
        em_pts = f"{profile.base_expected_move_pts:.1f} pts"
        em_cons = (
            f"{profile.em_consumption_pct:.1f} %"
            if profile.em_consumption_pct is not None
            else "N/A"
        )
        st.markdown(
            f"""
            <div class="kpi-card animate-enter delay-4">
                <div class="kpi-title">Expected Move Journalier</div>
                <div class="kpi-value refresh-flash">{em_pts}</div>
                <div class="kpi-sub">Consommé Overnight : <b>{em_cons}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------------
    # 3. BANDEAU DE SANTÉ DÉCOMPOSÉ DES SOURCES (AUCUN MASQUAGE)
    # -----------------------------------------------------------------------
    st.markdown(
        "<div style='font-size: 0.85rem; font-weight: 700; color: #94A3B8; margin-top: 10px; "
        "text-transform: uppercase; letter-spacing: 0.05em;'>"
        "SANTÉ DES COMPOSANTS SOURCES</div>",
        unsafe_allow_html=True,
    )
    chips_html = []
    for _c_key, c_val in profile.component_statuses.items():
        is_deg = "DÉGRADÉ" in c_val.status
        cls = "chip-degraded" if is_deg else "chip-ok"
        chips_html.append(f"<span class='{cls}'>{c_val.name} : {c_val.status}</span>")
    st.markdown("".join(chips_html), unsafe_allow_html=True)
    st.write("")

    # -----------------------------------------------------------------------
    # 4. RADAR MACRO & ACTUALITÉS INFLUENÇANT LE NASDAQ (6 FENÊTRES - TÂCHE 5)
    # -----------------------------------------------------------------------
    st.markdown(
        '<div class="section-header">RADAR MACRO & ACTUALITÉS INFLUENÇANT LE NASDAQ</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Indicateurs clés influençant le Nasdaq 100 : Taux, Inflation, Résultats Tech, "
        "Fed, Pétrole, Dollar. Données horodatées avec traçabilité et statut honnête."
    )

    try:
        macro_radar = fetch_macro_news_radar()
        cards = macro_radar.as_list()

        # Rangée 1 (3 fenêtres)
        r1_c1, r1_c2, r1_c3 = st.columns(3)
        with r1_c1:
            st.markdown(_render_radar_card_html(cards[0], delay_idx=5), unsafe_allow_html=True)
        with r1_c2:
            st.markdown(_render_radar_card_html(cards[1], delay_idx=6), unsafe_allow_html=True)
        with r1_c3:
            st.markdown(_render_radar_card_html(cards[2], delay_idx=7), unsafe_allow_html=True)

        # Rangée 2 (3 fenêtres)
        r2_c1, r2_c2, r2_c3 = st.columns(3)
        with r2_c1:
            st.markdown(_render_radar_card_html(cards[3], delay_idx=8), unsafe_allow_html=True)
        with r2_c2:
            st.markdown(_render_radar_card_html(cards[4], delay_idx=9), unsafe_allow_html=True)
        with r2_c3:
            st.markdown(_render_radar_card_html(cards[5], delay_idx=10), unsafe_allow_html=True)

    except Exception as exc:
        log.warning("Échec affichage radar macro: %s", exc)
        st.markdown(
            f'<div class="chip-degraded">[DÉGRADÉ] Radar macro inaccessible : {exc}</div>',
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------------
    # 4B. FIL EN DIRECT DES ACTUALITÉS & COMMUNIQUÉS OFFICIELS (LIVE WIRE)
    # -----------------------------------------------------------------------
    st.write("")
    st.markdown(
        '<div class="section-header" style="font-size: 0.88rem;">'
        'FIL D\'ACTUALITÉS EN DIRECT & COMMUNIQUÉS OFFICIELS (LIVE WIRE)'
        '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Veille d'actualité en direct influençant le Nasdaq (Conseil des Gouverneurs Fed & presse "
        "financière). Chaque dépêche affiche sa source, son horodatage Alger et NY, et son âge."
    )

    try:
        wire_report = fetch_live_news_wire(max_items_per_source=4)
        if wire_report.degraded_sources:
            deg_reasons_html = " · ".join(wire_report.degraded_sources)
            st.markdown(
                f'<div class="news-alert" style="margin-bottom: 10px;">'
                f'<b>[DÉGRADÉ]</b> Sources dégradées dans le fil : {deg_reasons_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

        if wire_report.items:
            w_col1, w_col2 = st.columns(2)
            for idx, item in enumerate(wire_report.items[:8]):
                with (w_col1 if idx % 2 == 0 else w_col2):
                    st.markdown(
                        _render_wire_item_html(item, delay_idx=idx % 4),
                        unsafe_allow_html=True,
                    )
        else:
            st.markdown(
                '<div class="chip-degraded">'
                '[DÉGRADÉ] Aucun communiqué reçu (flux RSS Fed & Google News inaccessibles).'
                '</div>',
                unsafe_allow_html=True,
            )
    except Exception as exc:
        log.warning("Échec affichage fil d'actualités: %s", exc)
        st.markdown(
            f'<div class="chip-degraded">[DÉGRADÉ] Fil d\'actualités indisponible : {exc}</div>',
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------------
    # 5. DEUX COLONNES : NIVEAUX CLÉS & CARTE DE SCÉNARIOS
    # -----------------------------------------------------------------------
    st.write("")
    c_left, c_right = st.columns([1, 1], gap="medium")

    with c_left:
        st.markdown(
            '<div class="section-header">NIVEAUX CLÉS EN POINTS NQ</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"Spot NQ de référence : <b>{profile.spot_nq:.2f} pts</b>",
            unsafe_allow_html=True,
        )

        if profile.key_levels:
            table_data = []
            for lvl in profile.key_levels:
                table_data.append({
                    "Niveau": lvl.name,
                    "Prix NQ": f"{lvl.price:.2f}",
                    "Distance (pts)": f"{lvl.distance_pts:+.1f}",
                    "Écart %": f"{lvl.distance_pct:+.2f}%",
                    "Type": lvl.level_type,
                    "Source": lvl.source,
                })
            st.dataframe(table_data, use_container_width=True, hide_index=True)

            csv_str = export_levels_to_csv(profile.key_levels)
            st.download_button(
                label="Exporter les Niveaux (CSV TradingView / ATAS)",
                data=csv_str,
                file_name=f"nq_levels_{profile.target_date}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.warning("Aucun niveau clé disponible.")

    with c_right:
        st.markdown(
            '<div class="section-header">CARTE DE SCÉNARIOS « SI… ALORS… »</div>',
            unsafe_allow_html=True,
        )
        st.caption("Conditions objectives de structure de carnet sans prédiction de direction.")

        if profile.scenarios:
            for sc in profile.scenarios:
                header = f"{sc.level_name} ({sc.level_price:.1f}) — {sc.level_type}"
                with st.expander(header, expanded=True):
                    st.markdown(
                        f"""
                        <div class="scenario-box">
                            <b>Condition :</b> {sc.if_condition}<br>
                            <b>Plan / Action :</b> {sc.then_plan}<br>
                            <small style="color: var(--text-muted);">
                                <b>Contexte :</b> {sc.context_notes}
                            </small>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.info("Aucun scénario généré pour la séance.")

    st.divider()
    st.caption(
        "NQ Cockpit P08 / P13 / Tâche 5 · Thème sombre mat Slate-950 · "
        "Strictement non-directionnel."
    )


if __name__ == "__main__":
    render_cockpit()
