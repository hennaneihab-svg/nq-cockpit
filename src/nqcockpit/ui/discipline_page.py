"""Porte de discipline et gestionnaire de risque live (P09 / P13).

Design System Bloomberg x TradingView :
- Interrogable à tout instant
- AUCUN bouton pour forcer GO, AUCUNE exécution d'ordre
- Badges en contour 1px, typographie tabulaire pour métriques
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.config import load_config
from nqcockpit.discipline.engine import (
    evaluate_checklist,
    evaluate_session_state,
)
from nqcockpit.discipline.models import (
    ChecklistVerdict,
    PreTradeChecklist,
    SessionDisciplineStatus,
)
from nqcockpit.discipline.risk import compute_position_size
from nqcockpit.journal.store import load_trades
from nqcockpit.ui.components import render_terminal_metric
from nqcockpit.ui.db import get_ui_db


def render_discipline_page() -> None:
    """Rendu complet de la Porte de Discipline."""
    try:
        st.set_page_config(
            page_title="NQ Cockpit — Porte de Discipline",
            layout="wide",
        )
    except StreamlitAPIException:
        pass

    # Thème Bloomberg x TradingView Desk
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #020617;
            color: #F8FAFC;
            font-family: -apple-system, system-ui, BlinkMacSystemFont,
                "Segoe UI", Roboto, sans-serif;
        }
        .badge-go {
            background-color: rgba(16, 185, 129, 0.10);
            border: 1px solid rgba(16, 185, 129, 0.25);
            color: #6EE7B7;
            padding: 12px;
            border-radius: 6px;
            font-family: ui-monospace, SFMono-Regular, monospace;
            font-weight: 700;
            font-size: 1.1rem;
            text-align: center;
        }
        .badge-stop {
            background-color: rgba(248, 113, 113, 0.10);
            border: 1px solid rgba(248, 113, 113, 0.25);
            color: #FCA5A5;
            padding: 12px;
            border-radius: 6px;
            font-family: ui-monospace, SFMono-Regular, monospace;
            font-weight: 700;
            font-size: 1.1rem;
            text-align: center;
        }
        .badge-warn {
            background-color: rgba(251, 191, 36, 0.10);
            border: 1px solid rgba(251, 191, 36, 0.25);
            color: #FCD34D;
            padding: 12px;
            border-radius: 6px;
            font-family: ui-monospace, SFMono-Regular, monospace;
            font-weight: 700;
            font-size: 1.1rem;
            text-align: center;
        }
        .card {
            background-color: #0F172A;
            border: 1px solid rgba(51, 65, 85, 0.6);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 14px;
            box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        }
        .section-header {
            font-family: -apple-system, system-ui, sans-serif;
            color: #F8FAFC;
            font-size: 1.05rem;
            font-weight: 600;
            letter-spacing: -0.01em;
            margin-bottom: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    config = load_config()
    conn = get_ui_db(config.data.db_path)
    trades = load_trades(conn)

    now_utc = datetime.now(timezone.utc)
    state = evaluate_session_state(trades, now_utc, config)

    st.markdown(
        '<div class="section-header">PORTE DE DISCIPLINE & GESTION DU RISQUE LIVE</div>',
        unsafe_allow_html=True,
    )

    # ---------------------------------------------------------------------------
    # Section 1 : État vivant de la séance
    # ---------------------------------------------------------------------------
    st.markdown("### 1. État Vivant de la Séance")

    tz_algiers = ZoneInfo(config.timezones.display)
    time_algiers_str = now_utc.astimezone(tz_algiers).strftime("%H:%M:%S")

    col_state, col_info = st.columns([1, 2])

    with col_state:
        if state.status == SessionDisciplineStatus.READY:
            st.markdown(
                '<div class="badge-go">MACHINE A ETATS : PRÊT (TRADING PERMIS)</div>',
                unsafe_allow_html=True,
            )
        elif state.status == SessionDisciplineStatus.COOLDOWN_ACTIVE:
            st.markdown(
                f'<div class="badge-warn">PAUSE OBLIGATOIRE POST-SL : '
                f'{state.cooldown_countdown_str} restante</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="badge-stop">SÉANCE VERROUILLÉE ({state.status.value})</div>',
                unsafe_allow_html=True,
            )

    with col_info:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            render_terminal_metric("Heure Alger", time_algiers_str)
        with c2:
            render_terminal_metric("Fenêtre active", state.current_window_name or "Aucune")
        with c3:
            rem_str = f"{state.trades_remaining} / {state.max_trades_allowed}"
            render_terminal_metric("Trades restants", rem_str)
        with c4:
            r_kind = "pos" if state.r_realized_today >= 0 else "neg"
            r_str = f"{state.r_realized_today:+.2f}R"
            render_terminal_metric("R cumulé jour", r_str, status_kind=r_kind)

    if state.lock_reasons:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.write("**Motifs de verrouillage actifs :**")
        for r in state.lock_reasons:
            st.markdown(f"- **[VERROU]** {r}")
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # ---------------------------------------------------------------------------
    # Section 2 : Calculateur de taille de position
    # ---------------------------------------------------------------------------
    st.markdown("### 2. Gestionnaire de Risque & Dimensionnement")

    c_inst, c_acc, c_risk, c_stop = st.columns(4)
    with c_inst:
        inst = st.selectbox(
            "Instrument",
            list(config.risk.point_values.keys()),
            index=0 if config.risk.instrument == "MNQ" else 1,
        )
    with c_acc:
        default_acc = (
            config.risk.account_size if config.risk.account_size > 0 else 50000.0
        )
        acc_size = st.number_input(
            "Capital compte ($)", value=float(default_acc), step=1000.0
        )
    with c_risk:
        risk_pct = st.number_input(
            "Risque max (%)",
            value=float(config.risk.risk_per_trade_pct),
            step=0.1,
        )
    with c_stop:
        stop_pts = st.number_input(
            "Distance Stop (points)", value=30.0, step=1.0, min_value=1.0
        )

    with st.expander("Contraintes Prop Firm (Optionnel)"):
        cp1, cp2 = st.columns(2)
        prop_max_loss = cp1.number_input(
            "Perte max journalière ($)", value=0.0, step=100.0
        )
        prop_dd = cp2.number_input(
            "Drawdown glissant max ($)", value=0.0, step=100.0
        )

    sizing_res = compute_position_size(
        account_size=acc_size,
        risk_pct=risk_pct,
        stop_points=stop_pts,
        instrument=inst,
        config=config,
        prop_max_daily_loss=prop_max_loss if prop_max_loss > 0 else None,
        prop_trailing_dd=prop_dd if prop_dd > 0 else None,
    )

    st.markdown('<div class="card">', unsafe_allow_html=True)
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        render_terminal_metric(
            "Contrats autorisés",
            f"{sizing_res.contracts}x {inst}",
            subtext="Math.floor floor",
            status_kind="ok",
        )
    with s2:
        render_terminal_metric("Budget risque", f"{sizing_res.risk_budget_dollars:.2f} $")
    with s3:
        act_sub = f"{sizing_res.actual_risk_pct:.2f}% capital"
        render_terminal_metric(
            "Risque réel",
            f"{sizing_res.actual_risk_dollars:.2f} $",
            subtext=act_sub,
        )
    with s4:
        render_terminal_metric("Valeur du point", f"{sizing_res.point_value:.1f} $/pt")

    if sizing_res.warning:
        st.warning(f"[AVERTISSEMENT] {sizing_res.warning}")
    if sizing_res.prop_firm_warning:
        st.error(f"[PROP FIRM VERROU] {sizing_res.prop_firm_warning}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # ---------------------------------------------------------------------------
    # Section 3 : Checklist Pré-Trade Interactive
    # ---------------------------------------------------------------------------
    st.markdown("### 3. Checklist Pré-Trade Interactive (Verdict GO / STOP)")

    chk_p08 = st.checkbox(
        "1. J'ai consulté et validé le profil P08 de la séance (niveaux, scénarios, EM).",
        value=False,
    )
    chk_red = st.checkbox(
        "2. Événement Tier 1 ROUGE imminent ou en cours dans les 5 prochaines minutes ?",
        value=False,
        help="Si cochée, le trading est immédiatement bloqué.",
    )
    plan_text = st.text_area(
        "3. Plan écrit de trade (au moins 10 caractères)",
        placeholder="Ex: Rejet propre sur VWAP avec entrée à 20850, stop sous le creux à 20820.",
    )

    checklist_data = PreTradeChecklist(
        p08_reviewed=chk_p08,
        trading_plan=plan_text,
        sizing_result=sizing_res,
        event_risk_tier1_red=chk_red,
    )

    chk_verdict = evaluate_checklist(checklist_data, state, config)

    st.markdown("#### Verdict Pré-Trade")
    if chk_verdict.verdict == ChecklistVerdict.GO:
        st.markdown(
            """
            <div class="badge-go">
                VERDICT : GO — TRADING AUTORISÉ<br>
                <span style="font-size: 0.82rem; font-weight: normal; color: #D1D4DC;">
                    Toutes les conditions de discipline et de risque sont satisfaites.
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="badge-stop">
                VERDICT : STOP — TRADING STRICTEMENT INTERDIT<br>
                <span style="font-size: 0.82rem; font-weight: normal; color: #D1D4DC;">
                    Ne prenez aucun ordre. Consultez les motifs bloquants ci-dessous.
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.write("**Motifs bloquants :**")
        for b in chk_verdict.blocking_reasons:
            st.markdown(f"- **[MOTIF BLOQUANT]** {b}")
        st.markdown("</div>", unsafe_allow_html=True)

    st.caption(
        "Note de sécurité : cette interface n'a aucun lien avec un courtier "
        "et ne permet aucune exécution d'ordre."
    )


if __name__ == "__main__":
    render_discipline_page()
