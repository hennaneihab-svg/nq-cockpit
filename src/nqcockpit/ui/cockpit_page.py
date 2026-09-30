"""Page principale Streamlit NQ Cockpit (P08).

Caractéristiques :
- Lisible en 5 secondes (vue globale immédiate)
- Thème sombre à fort contraste
- Feux tricolores de STATUT (jamais de direction)
- Compte à rebours événement Tier 1
- Bandeau d'état de santé des sources décomposé
- Tableau des niveaux clés et export CSV
- Carte de scénarios "Si... Alors..." strictement non-directionnelle
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from nqcockpit.config import load_config
from nqcockpit.profile.engine import build_day_profile, export_levels_to_csv

TZ_ALGIERS = ZoneInfo("Africa/Algiers")
TZ_ET = ZoneInfo("America/New_York")


def render_cockpit():
    """Rendu complet de la page Cockpit."""
    st.set_page_config(
        page_title="NQ Cockpit — Profil de Séance",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Injection CSS Thème Sombre & Typographie Professionnelle
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #0b0f17;
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         Roboto, Helvetica, Arial, sans-serif;
        }
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 95%;
        }
        .status-banner-allowed {
            background: linear-gradient(
                90deg, rgba(16, 185, 129, 0.15) 0%, rgba(16, 185, 129, 0.05) 100%
            );
            border: 2px solid #10b981;
            border-radius: 8px;
            padding: 14px 20px;
            margin-bottom: 20px;
        }
        .status-banner-notrade {
            background: linear-gradient(
                90deg, rgba(239, 68, 68, 0.2) 0%, rgba(239, 68, 68, 0.05) 100%
            );
            border: 2px solid #ef4444;
            border-radius: 8px;
            padding: 14px 20px;
            margin-bottom: 20px;
        }
        .kpi-card {
            background-color: #141b27;
            border: 1px solid #222f44;
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 12px;
        }
        .kpi-title {
            color: #94a3b8;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }
        .kpi-value {
            font-size: 1.4rem;
            font-weight: 700;
            color: #f8fafc;
        }
        .kpi-sub {
            font-size: 0.8rem;
            color: #64748b;
            margin-top: 4px;
        }
        .chip-ok {
            background-color: #064e3b;
            color: #34d399;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            display: inline-block;
            margin-right: 6px;
        }
        .chip-degraded {
            background-color: #78350f;
            color: #fbbf24;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            display: inline-block;
            margin-right: 6px;
        }
        .scenario-box {
            background-color: #141b27;
            border-left: 3px solid #38bdf8;
            padding: 10px 14px;
            margin-bottom: 10px;
            border-radius: 0 6px 6px 0;
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
        st.markdown("## ⚡ NQ Cockpit — Profil de Séance")
        st.caption("Aide à la décision non-directionnelle · Discipline & Cadre d'exécution")
    with col_t2:
        now_alg = now_utc.astimezone(TZ_ALGIERS).strftime("%H:%M:%S")
        now_et = now_utc.astimezone(TZ_ET).strftime("%H:%M:%S")
        st.markdown(
            f"<div style='text-align: right; font-size: 0.85rem; color: #94a3b8;'>"
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
                <span style="font-size: 1.3rem; font-weight: 800; color: #10b981;">
                    🟢 TRADING AUTORISÉ (SOUS CONDITIONS)
                </span><br>
                <span style="font-size: 0.9rem; color: #d1fae5;">
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
                <span style="font-size: 1.3rem; font-weight: 800; color: #ef4444;">
                    🛑 DRAPEAU NO-TRADE ACTIF ({cnt})
                </span><br>
                <span style="font-size: 0.9rem; color: #fecaca;">
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
            color_ev = "#10b981"
        elif profile.event_risk_level == "AMBER":
            color_ev = "#f59e0b"
        else:
            color_ev = "#ef4444"
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
        g_color = "#38bdf8" if profile.gamma_regime == "POSITIVE_GAMMA" else "#f97316"
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
                <div class="kpi-sub">Consommé par l'Overnight : <b>{em_cons}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------------
    # 3. BANDEAU DE SANTÉ DÉCOMPOSÉ DES SOURCES (AUCUN MASQUAGE)
    # -----------------------------------------------------------------------
    st.markdown("##### Santé des Composants Sources")
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
        st.markdown("### 🎯 Niveaux Clés en Points NQ")
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
                label="📥 Exporter les Niveaux (CSV TradingView / ATAS)",
                data=csv_str,
                file_name=f"nq_levels_{profile.target_date}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.warning("Aucun niveau clé disponible.")

    with c_right:
        st.markdown("### 🗺️ Carte de Scénarios « Si… Alors… »")
        st.caption("Conditions objectives de structure de carnet sans prédiction de direction.")

        if profile.scenarios:
            for sc in profile.scenarios:
                header = f"📍 {sc.level_name} ({sc.level_price:.1f}) — {sc.level_type}"
                with st.expander(header, expanded=True):
                    st.markdown(
                        f"""
                        <div class="scenario-box">
                            <b>Condition :</b> {sc.if_condition}<br>
                            <b>Plan / Action :</b> {sc.then_plan}<br>
                            <small style="color: #94a3b8;">
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
        "NQ Cockpit P08 · Strict respect des principes nq-principles : "
        "zéro biais directionnel, probabilités objectives."
    )


if __name__ == "__main__":
    render_cockpit()
