"""Porte de discipline et gestionnaire de risque live (P09 réel UI Streamlit).

Page dédiée distincte du journal.
Interrogable à tout instant.
AUCUN bouton pour forcer GO.
AUCUNE exécution d'ordre.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st

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
from nqcockpit.journal.store import init_journal_db, load_trades

st.set_page_config(
    page_title="NQ Cockpit — Porte de Discipline",
    page_icon="🛡️",
    layout="wide",
)

# Thème sombre
st.markdown(
    """
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    .badge-go {
        background-color: #1f6feb22; border: 2px solid #238636;
        color: #3fb950; padding: 12px; border-radius: 8px;
        font-weight: bold; font-size: 1.2rem; text-align: center;
    }
    .badge-stop {
        background-color: #da363322; border: 2px solid #da3633;
        color: #f85149; padding: 12px; border-radius: 8px;
        font-weight: bold; font-size: 1.2rem; text-align: center;
    }
    .badge-warn {
        background-color: #d2992222; border: 2px solid #d29922;
        color: #e3b341; padding: 12px; border-radius: 8px;
        font-weight: bold; font-size: 1.2rem; text-align: center;
    }
    .card {
        background-color: #161b22; border: 1px solid #30363d;
        border-radius: 8px; padding: 16px; margin-bottom: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

config = load_config()
conn = init_journal_db(config.data.db_path)
trades = load_trades(conn)

now_utc = datetime.now(timezone.utc)
state = evaluate_session_state(trades, now_utc, config)

st.title("🛡️ NQ Cockpit — Porte de Discipline Live")

# ---------------------------------------------------------------------------
# Section 1 : État vivant de la séance
# ---------------------------------------------------------------------------
st.subheader("1. État Vivant de la Séance")

tz_algiers = ZoneInfo(config.timezones.display)
time_algiers_str = now_utc.astimezone(tz_algiers).strftime("%H:%M:%S")

col_state, col_info = st.columns([1, 2])

with col_state:
    if state.status == SessionDisciplineStatus.READY:
        st.markdown(
            '<div class="badge-go">✅ MACHINE À ÉTATS : PRÊT (TRADING PERMIS)</div>',
            unsafe_allow_html=True,
        )
    elif state.status == SessionDisciplineStatus.COOLDOWN_ACTIVE:
        st.markdown(
            f'<div class="badge-warn">⏳ PAUSE OBLIGATOIRE POST-SL : '
            f'{state.cooldown_countdown_str} restante</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="badge-stop">🛑 SÉANCE VERROUILLÉE ({state.status.value})</div>',
            unsafe_allow_html=True,
        )

with col_info:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Heure Alger", time_algiers_str)
    c2.metric("Fenêtre active", state.current_window_name or "Aucune")
    c3.metric(
        "Trades restants",
        f"{state.trades_remaining} / {state.max_trades_allowed}",
    )
    c4.metric("R cumulé aujourd'hui", f"{state.r_realized_today:+.2f}R")

if state.lock_reasons:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.write("**Motifs de verrouillage actifs :**")
    for r in state.lock_reasons:
        st.markdown(f"- ⚠️ {r}")
    st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ---------------------------------------------------------------------------
# Section 2 : Calculateur de taille de position
# ---------------------------------------------------------------------------
st.subheader("2. Gestionnaire de Risque & Dimensionnement")

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
s1.metric(
    "Contrats autorisés (floor)",
    f"{sizing_res.contracts} contrat(s)",
    help="Arrondi inférieur math.floor pour ne jamais dépasser le risque alloué.",
)
s2.metric("Risque budget", f"{sizing_res.risk_budget_dollars:.2f} $")
s3.metric(
    "Risque réel résultant",
    f"{sizing_res.actual_risk_dollars:.2f} $ ({sizing_res.actual_risk_pct:.2f}%)",
)
s4.metric("Valeur du point", f"{sizing_res.point_value:.1f} $/pt")

if sizing_res.warning:
    st.warning(f"⚠️ {sizing_res.warning}")
if sizing_res.prop_firm_warning:
    st.error(f"🛑 {sizing_res.prop_firm_warning}")
st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ---------------------------------------------------------------------------
# Section 3 : Checklist Pré-Trade Interactive
# ---------------------------------------------------------------------------
st.subheader("3. Checklist Pré-Trade Interactive (Verdict GO / STOP)")

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

st.markdown("### Verdict Pré-Trade")
if chk_verdict.verdict == ChecklistVerdict.GO:
    st.markdown(
        """
        <div class="badge-go">
            🟢 VERDICT : GO — TRADING AUTORISÉ<br>
            <span style="font-size: 0.9rem; font-weight: normal;">
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
            🔴 VERDICT : STOP — TRADING STRICTEMENT INTERDIT<br>
            <span style="font-size: 0.9rem; font-weight: normal;">
                Ne prenez aucun ordre. Consultez les motifs bloquants ci-dessous.
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.write("**Motifs bloquants :**")
    for b in chk_verdict.blocking_reasons:
        st.markdown(f"- ❌ {b}")
    st.markdown("</div>", unsafe_allow_html=True)

st.caption(
    "Note de sécurité : cette interface n'a aucun lien avec un courtier "
    "et ne permet aucune exécution d'ordre."
)
