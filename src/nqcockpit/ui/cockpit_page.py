"""Page principale Streamlit NQ Cockpit (P08 / P13).

Design System Bloomberg x TradingView :
- Vue globale synoptique lisible en 5 secondes
- Conteneurs Slate #131722, bordures 1px #2A2E39, accents marque #FA7900
- Statuts sémantiques en contours 1px ([OK], [DÉGRADÉ], [BLOQUÉ], [NO-TRADE])
- Strictement non-directionnel
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.config import load_config
from nqcockpit.profile.engine import build_day_profile, export_levels_to_csv

TZ_ALGIERS = ZoneInfo("Africa/Algiers")
TZ_ET = ZoneInfo("America/New_York")


def render_cockpit():
    """Rendu complet de la page Cockpit."""
    try:
        st.set_page_config(
            page_title="NQ Cockpit — Profil de Séance",
            layout="wide",
            initial_sidebar_state="collapsed",
        )
    except StreamlitAPIException:
        pass

    # CSS Bloomberg x TradingView Desk
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #020617;
            color: #F8FAFC;
            font-family: -apple-system, system-ui, BlinkMacSystemFont,
                "Segoe UI", Roboto, sans-serif;
        }
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 98%;
        }
        .status-banner-allowed {
            background-color: rgba(16, 185, 129, 0.08);
            border: 1px solid rgba(16, 185, 129, 0.25);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 16px;
            color: #6EE7B7;
        }
        .status-banner-notrade {
            background-color: rgba(248, 113, 113, 0.08);
            border: 1px solid rgba(248, 113, 113, 0.25);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 16px;
            color: #FCA5A5;
        }
        .kpi-card {
            background-color: #0F172A;
            border: 1px solid rgba(51, 65, 85, 0.6);
            border-radius: 8px;
            padding: 14px 16px;
            margin-bottom: 10px;
        }
        .kpi-title {
            color: #94A3B8;
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
            color: #F8FAFC;
        }
        .kpi-sub {
            font-family: -apple-system, sans-serif;
            font-size: 0.75rem;
            color: #94A3B8;
            margin-top: 4px;
        }
        .chip-ok {
            background-color: rgba(16, 185, 129, 0.10);
            border: 1px solid rgba(16, 185, 129, 0.25);
            color: #6EE7B7;
            padding: 2px 8px;
            border-radius: 6px;
            font-family: ui-monospace, monospace;
            font-size: 0.75rem;
            font-weight: 600;
            display: inline-block;
            margin-right: 6px;
            margin-bottom: 4px;
        }
        .chip-degraded {
            background-color: rgba(251, 191, 36, 0.10);
            border: 1px solid rgba(251, 191, 36, 0.25);
            color: #FCD34D;
            padding: 2px 8px;
            border-radius: 6px;
            font-family: ui-monospace, monospace;
            font-size: 0.75rem;
            font-weight: 600;
            display: inline-block;
            margin-right: 6px;
            margin-bottom: 4px;
        }
        .scenario-box {
            background-color: #0F172A;
            border: 1px solid rgba(51, 65, 85, 0.6);
            border-left: 3px solid #818CF8;
            padding: 12px 16px;
            margin-bottom: 10px;
            border-radius: 0 8px 8px 0;
            font-size: 0.82rem;
        }
        .section-header {
            font-family: -apple-system, system-ui, sans-serif;
            color: #F8FAFC;
            font-size: 1.05rem;
            font-weight: 600;
            letter-spacing: -0.01em;
            margin-bottom: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Chargement de la configuration et des données
    cfg = load_config()
    db_path = Path("data/cockpit.db")
    conn = None
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

    now_utc = datetime.now(timezone.utc)
    profile = build_day_profile(conn=conn, config=cfg, now_utc=now_utc)
    if conn:
        conn.close()

    # En-tête : Titre & Horodatages multi-fuseaux
    col_t1, col_t2 = st.columns([2, 1])
    with col_t1:
        st.markdown(
            '<div class="section-header">NQ COCKPIT // PROFIL DE SÉANCE LIVE</div>',
            unsafe_allow_html=True,
        )
        st.caption("Aide à la décision non-directionnelle · Discipline & Cadre d'exécution")
    with col_t2:
        now_alg = now_utc.astimezone(TZ_ALGIERS).strftime("%H:%M:%S")
        now_et = now_utc.astimezone(TZ_ET).strftime("%H:%M:%S")
        st.markdown(
            f"<div class='header-clock' style='text-align: right; font-family: monospace; "
            f"font-size: 0.82rem; line-height: 1.45; padding-top: 4px;'>"
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
            <div class="status-banner-allowed">
                <span style="font-family: monospace; font-weight: 700; color: #089981;">
                    SYSTEM // TRADING AUTORISÉ (SOUS CONDITIONS)
                </span><br>
                <span style="font-size: 0.82rem; color: #D1D4DC;">
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
            <div class="status-banner-notrade">
                <span style="font-family: monospace; font-weight: 700; color: #F23645;">
                    SYSTEM // DRAPEAU NO-TRADE ACTIF ({cnt})
                </span><br>
                <span style="font-size: 0.82rem; color: #D1D4DC;">
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
            color_ev = "#089981"
        elif profile.event_risk_level == "AMBER":
            color_ev = "#D29922"
        else:
            color_ev = "#F23645"
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-title">Prochain Événement Tier 1</div>
                <div class="kpi-value" style="color: {color_ev};">{cd_text}</div>
                <div class="kpi-sub">{ev_title} (Risque {profile.event_risk_level})</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with k2:
        g_color = "#089981" if profile.gamma_regime == "POSITIVE_GAMMA" else "#F23645"
        dist_f = (
            f"{profile.distance_to_flip_pts:+.1f} pts"
            if profile.distance_to_flip_pts is not None
            else "N/A"
        )
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-title">Régime Gamma (P04)</div>
                <div class="kpi-value" style="color: {g_color};">{profile.gamma_regime}</div>
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
            <div class="kpi-card">
                <div class="kpi-title">Régime de Volatilité (P07)</div>
                <div class="kpi-value">{profile.volatility_regime}</div>
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
            <div class="kpi-card">
                <div class="kpi-title">Expected Move Journalier</div>
                <div class="kpi-value">{em_pts}</div>
                <div class="kpi-sub">Consommé Overnight : <b>{em_cons}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------------
    # 3. BANDEAU DE SANTÉ DÉCOMPOSÉ DES SOURCES (AUCUN MASQUAGE)
    # -----------------------------------------------------------------------
    st.markdown(
        "<div style='font-size: 0.9rem; font-weight: 700; color: #FA7900; margin-top: 10px;'>"
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
    # 4. DEUX COLONNES : NIVEAUX CLÉS & CARTE DE SCÉNARIOS
    # -----------------------------------------------------------------------
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
            # Construction d'un tableau propre
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

            # Export CSV
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
                            <small style="color: #787B86;">
                                <b>Contexte :</b> {sc.context_notes}
                            </small>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.info("Aucun scénario généré pour la séance.")

    # -----------------------------------------------------------------------
    # 5. FIL DE PRESSE MACRO & ACTUALITÉS FONDAMENTALES (EN DIRECT)
    # -----------------------------------------------------------------------
    st.divider()
    st.markdown(
        '<div class="section-header">FIL D\'ACTUALITÉS FONDAMENTALES & MACRO (LIVE WIRE)</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Veille d'information macroéconomique & déclarations officielles en direct "
        "(Fed Press Releases, Google News Macro/Nasdaq). Données factuelles sans biais."
    )

    try:
        import urllib.request
        import xml.etree.ElementTree as ET

        @st.cache_data(ttl=300)
        def _get_live_news() -> list[dict[str, str]]:
            items: list[dict[str, str]] = []
            # 1. Federal Reserve Press Releases
            url_fed = "https://www.federalreserve.gov/feeds/press_all.xml"
            try:
                req = urllib.request.Request(
                    url_fed,
                    headers={"User-Agent": "NQCockpit/1.0 (contact@nqcockpit.local)"},
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    root = ET.fromstring(r.read())
                    for it in list(root.iter("item"))[:5]:
                        items.append({
                            "title": it.findtext("title") or "",
                            "date": it.findtext("pubDate") or "",
                            "source": "Federal Reserve (Officiel)",
                            "link": it.findtext("link") or "",
                            "tag": "FED / TAUX",
                            "tag_color": "#818CF8",
                        })
            except Exception:
                pass

            # 2. Google News US Macro & Nasdaq
            url_gnews = (
                "https://news.google.com/rss/search?"
                "q=(Nasdaq+OR+FOMC+OR+\"Federal+Reserve\"+OR+CPI+OR+inflation)+when:2d"
                "&hl=en-US&gl=US&ceid=US:en"
            )
            try:
                req = urllib.request.Request(url_gnews, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    root = ET.fromstring(r.read())
                    for it in list(root.iter("item"))[:12]:
                        s_elem = it.find("source")
                        s_name = s_elem.text if s_elem is not None else "Presse financière"
                        items.append({
                            "title": it.findtext("title") or "",
                            "date": it.findtext("pubDate") or "",
                            "source": s_name,
                            "link": it.findtext("link") or "",
                            "tag": "ACTU MARCHÉ",
                            "tag_color": "#38BDF8",
                        })
            except Exception:
                pass

            return items

        wire_items = _get_live_news()
        if wire_items:
            wire_cols = st.columns(2)
            for idx, n in enumerate(wire_items[:8]):
                with wire_cols[idx % 2]:
                    st.markdown(
                        f"""
                        <div style="
                            background-color: #0F172A;
                            border: 1px solid rgba(51, 65, 85, 0.6);
                            border-radius: 8px;
                            padding: 12px 14px;
                            margin-bottom: 8px;
                            display: flex;
                            flex-direction: column;
                            gap: 4px;
                        ">
                            <div style="display:flex; justify-content:space-between;">
                                <span style="
                                    font-size: 0.68rem;
                                    font-weight: 700;
                                    color: {n['tag_color']};
                                    background: rgba(51, 65, 85, 0.4);
                                    padding: 2px 6px;
                                    border-radius: 4px;
                                    font-family: ui-monospace, monospace;
                                ">
                                    {n['tag']}
                                </span>
                                <span style="font-size: 0.72rem; color: #64748B;">
                                    {n['source']}
                                </span>
                            </div>
                            <div style="font-size: 0.85rem; font-weight: 600; line-height: 1.35;">
                                <a href="{n['link']}" target="_blank"
                                   rel="noopener noreferrer"
                                   style="color: #F8FAFC; text-decoration: none;">
                                    {n['title']}
                                </a>
                            </div>
                            <div style="font-size: 0.68rem; color: #94A3B8;">
                                {n['date']}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.info("[DÉGRADÉ] Flux d'actualités temporairement inaccessible depuis ce réseau.")
    except Exception as exc:
        st.caption(f"Flux d'actualités indisponible : {exc}")

    st.divider()
    st.caption(
        "NQ Cockpit P08 / P13 · Design System Swetrix · "
        "Strictement non-directionnel."
    )


if __name__ == "__main__":
    render_cockpit()
