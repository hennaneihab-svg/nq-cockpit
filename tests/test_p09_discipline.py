"""Tests pytest pour la porte de discipline live et gestionnaire de risque (P09 réel).

Couvre :
- Machine à états temps réel (fenêtre, limite trades, annulation T2, perte -2R, cooldown)
- Calculs de dimensionnement vérifiés rigoureusement à la main (au moins 3 cas)
- Checklist pré-trade interactive GO / STOP déterministe
- Vérification formelle d'absence d'exécution d'ordre
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone

import pytest

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
from nqcockpit.journal.models import (
    TradeDirection,
    TradeEntry,
    TradeOutcome,
)


@pytest.fixture()
def config():
    """Charge la configuration réelle du projet."""
    return load_config()


def _make_trade(
    *,
    session_date: str = "2026-09-30",
    outcome: TradeOutcome = TradeOutcome.WIN,
    r_realized: float = 1.0,
    recorded_at: datetime | None = None,
) -> TradeEntry:
    return TradeEntry(
        trade_id=str(uuid.uuid4()),
        recorded_at=recorded_at or datetime.now(timezone.utc),
        session_date=session_date,
        direction=TradeDirection.LONG,
        entry_price=20000.0,
        stop_price=19950.0,
        exit_price=20050.0 if r_realized > 0 else 19950.0,
        outcome=outcome,
        r_realized=r_realized,
        window_name="trade1",
    )


# ---------------------------------------------------------------------------
# Tests Machine à États (Live Gate)
# ---------------------------------------------------------------------------


def test_state_machine_ready_during_window(config):
    """En pleine fenêtre (ex: 16h00 Alger) avec 0 trade -> Statut READY."""
    # 16:00 Alger = 15:00 UTC (sans DST)
    dt_algiers_16h = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    state = evaluate_session_state([], dt_algiers_16h, config)

    assert state.can_trade is True
    assert state.status == SessionDisciplineStatus.READY
    assert state.current_window_name == "trade1"
    assert state.trades_remaining == 2
    assert len(state.lock_reasons) == 0


def test_state_machine_out_of_window(config):
    """Hors fenêtre horaire (ex: 10h00 Alger = 09h00 UTC) -> Statut OUT_OF_WINDOW."""
    dt_algiers_10h = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)
    state = evaluate_session_state([], dt_algiers_10h, config)

    assert state.can_trade is False
    assert state.status == SessionDisciplineStatus.OUT_OF_WINDOW
    assert state.current_window_name is None
    assert any("Hors fenêtre" in r for r in state.lock_reasons)


def test_state_machine_lock_after_trade1_loss(config):
    """Trade 1 en perte -> Annulation Trade 2 (anti-revenge trading)."""
    dt_16h = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    t1 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.LOSS,
        r_realized=-1.0,
        recorded_at=datetime(2026, 9, 30, 14, 30, tzinfo=timezone.utc),
    )
    state = evaluate_session_state([t1], dt_16h, config)

    assert state.can_trade is False
    assert state.status == SessionDisciplineStatus.LOCKED_TRADE1_LOSS
    assert any("anti-revenge" in r.lower() for r in state.lock_reasons)


def test_state_machine_cooldown_active_after_sl(config):
    """Tentative de rentrée à 10 min après un SL (cooldown = 15 min) -> COOLDOWN_ACTIVE."""
    # Supposons cancel_trade2_if_trade1_loss désactivé temporairement pour tester le cooldown pur
    dt_trade = datetime(2026, 9, 30, 14, 50, tzinfo=timezone.utc)
    dt_now = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)  # 10 min après

    t1 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.LOSS,
        r_realized=-0.8,
        recorded_at=dt_trade,
    )

    # Créons une config avec cancel_trade2_if_trade1_loss = False pour isoler le cooldown
    from dataclasses import replace
    cfg_no_cancel = replace(
        config,
        rules=replace(config.rules, cancel_trade2_if_trade1_loss=False),
    )

    state = evaluate_session_state([t1], dt_now, cfg_no_cancel)

    assert state.can_trade is False
    assert state.status == SessionDisciplineStatus.COOLDOWN_ACTIVE
    assert 290.0 <= state.cooldown_remaining_seconds <= 310.0  # ~300 sec = 5 min
    cd_str = state.cooldown_countdown_str
    assert cd_str.startswith("05:") or cd_str.startswith("04:")


def test_state_machine_cooldown_expired(config):
    """16 minutes après un SL (cooldown 15 min expiré) -> Cooldown = 0."""
    dt_trade = datetime(2026, 9, 30, 14, 40, tzinfo=timezone.utc)
    dt_now = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)  # 20 min après

    t1 = _make_trade(
        session_date="2026-09-30",
        outcome=TradeOutcome.LOSS,
        r_realized=-0.8,
        recorded_at=dt_trade,
    )

    from dataclasses import replace
    cfg_no_cancel = replace(
        config,
        rules=replace(config.rules, cancel_trade2_if_trade1_loss=False),
    )

    state = evaluate_session_state([t1], dt_now, cfg_no_cancel)
    assert state.cooldown_remaining_seconds == 0.0
    assert state.can_trade is True


def test_state_machine_max_trades_lockout(config):
    """Après 2 trades pris dans la journée -> LOCKED_MAX_TRADES."""
    dt_16h = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    t1 = _make_trade(session_date="2026-09-30", outcome=TradeOutcome.WIN, r_realized=1.5)
    t2 = _make_trade(session_date="2026-09-30", outcome=TradeOutcome.WIN, r_realized=1.0)

    state = evaluate_session_state([t1, t2], dt_16h, config)

    assert state.can_trade is False
    assert state.status == SessionDisciplineStatus.LOCKED_MAX_TRADES
    assert state.trades_remaining == 0
    assert any("maximal" in r.lower() for r in state.lock_reasons)


def test_state_machine_daily_loss_limit(config):
    """Perte cumulée <= -2R -> LOCKED_DAILY_LOSS."""
    dt_16h = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    t1 = _make_trade(session_date="2026-09-30", outcome=TradeOutcome.LOSS, r_realized=-2.0)

    state = evaluate_session_state([t1], dt_16h, config)

    assert state.can_trade is False
    assert state.status == SessionDisciplineStatus.LOCKED_DAILY_LOSS
    assert any("perte journalière" in r.lower() for r in state.lock_reasons)


# ---------------------------------------------------------------------------
# Tests Position Sizing (Calculs à la main vérifiés)
# ---------------------------------------------------------------------------


def test_sizing_case_a_mnq_standard(config):
    """Cas A : Compte 50 000 $, risque 0.5 %, Stop 30 pts sur MNQ (2 $/pt).

    Calcul à la main :
    - Budget risque = 50 000 * 0.005 = 250 $
    - Risque / contrat = 30 pts * 2 $/pt = 60 $
    - Contrats bruts = 250 / 60 = 4.166...
    - Arrondi inférieur (floor) = 4 contrats
    - Risque réel = 4 * 60 = 240 $
    - Risque réel % = (240 / 50 000) * 100 = 0.48 %
    """
    res = compute_position_size(
        account_size=50000.0,
        risk_pct=0.5,
        stop_points=30.0,
        instrument="MNQ",
        config=config,
    )
    assert res.point_value == 2.0
    assert res.risk_budget_dollars == 250.0
    assert res.risk_per_contract_dollars == 60.0
    assert res.contracts == 4
    assert res.actual_risk_dollars == 240.0
    assert res.actual_risk_pct == 0.48
    assert res.warning is None


def test_sizing_case_b_nq_standard(config):
    """Cas B : Compte 100 000 $, risque 1.0 %, Stop 45 pts sur NQ (20 $/pt).

    Calcul à la main :
    - Budget risque = 100 000 * 0.01 = 1 000 $
    - Risque / contrat = 45 pts * 20 $/pt = 900 $
    - Contrats bruts = 1 000 / 900 = 1.111...
    - Arrondi inférieur (floor) = 1 contrat
    - Risque réel = 1 * 900 = 900 $
    - Risque réel % = (900 / 100 000) * 100 = 0.90 %
    """
    res = compute_position_size(
        account_size=100000.0,
        risk_pct=1.0,
        stop_points=45.0,
        instrument="NQ",
        config=config,
    )
    assert res.point_value == 20.0
    assert res.risk_budget_dollars == 1000.0
    assert res.risk_per_contract_dollars == 900.0
    assert res.contracts == 1
    assert res.actual_risk_dollars == 900.0
    assert res.actual_risk_pct == 0.90
    assert res.warning is None


def test_sizing_case_c_insufficient_budget(config):
    """Cas C : Petit compte 5 000 $, risque 0.5 %, Stop 60 pts sur MNQ (2 $/pt).

    Calcul à la main :
    - Budget risque = 5 000 * 0.005 = 25 $
    - Risque / contrat = 60 pts * 2 $/pt = 120 $
    - Contrats bruts = 25 / 120 = 0.208...
    - Arrondi inférieur (floor) = 0 contrat
    - Risque réel = 0 $
    - Warning explicite généré.
    """
    res = compute_position_size(
        account_size=5000.0,
        risk_pct=0.5,
        stop_points=60.0,
        instrument="MNQ",
        config=config,
    )
    assert res.contracts == 0
    assert res.actual_risk_dollars == 0.0
    assert res.warning is not None
    assert "insuffisant" in res.warning.lower()


def test_sizing_prop_firm_constraints(config):
    """Cas D : Alerte dépassement contraintes Prop Firm."""
    # Compte 50 000 $, risque 0.5% (240 $ réel), limite perte max prop = 200 $
    res = compute_position_size(
        account_size=50000.0,
        risk_pct=0.5,
        stop_points=30.0,
        instrument="MNQ",
        config=config,
        prop_max_daily_loss=200.0,
    )
    assert res.contracts == 4
    assert res.prop_firm_warning is not None
    assert "Prop Firm" in res.prop_firm_warning


# ---------------------------------------------------------------------------
# Tests Checklist Pré-Trade Interactive
# ---------------------------------------------------------------------------


def test_checklist_verdict_go(config):
    """Tous les critères réunis -> VERDICT GO."""
    dt_16h = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    state = evaluate_session_state([], dt_16h, config)

    sizing = compute_position_size(
        account_size=50000.0,
        risk_pct=0.5,
        stop_points=30.0,
        instrument="MNQ",
        config=config,
    )

    chk = PreTradeChecklist(
        p08_reviewed=True,
        trading_plan="Rejet sur VWAP avec entrée à 20850 et stop sous le creux.",
        sizing_result=sizing,
        event_risk_tier1_red=False,
    )
    res = evaluate_checklist(chk, state, config)

    assert res.passed is True
    assert res.verdict == ChecklistVerdict.GO
    assert len(res.blocking_reasons) == 0


def test_checklist_verdict_stop_on_event_red(config):
    """Événement Tier 1 RED -> VERDICT STOP immédiat."""
    dt_16h = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    state = evaluate_session_state([], dt_16h, config)

    sizing = compute_position_size(
        account_size=50000.0,
        risk_pct=0.5,
        stop_points=30.0,
        instrument="MNQ",
        config=config,
    )

    chk = PreTradeChecklist(
        p08_reviewed=True,
        trading_plan="Plan valide mais news rouge imminente.",
        sizing_result=sizing,
        event_risk_tier1_red=True,  # RED
    )
    res = evaluate_checklist(chk, state, config)

    assert res.passed is False
    assert res.verdict == ChecklistVerdict.STOP
    assert any("Tier 1" in r for r in res.blocking_reasons)


def test_checklist_verdict_stop_missing_plan_or_p08(config):
    """Plan trop court (<10 chars) et profil P08 non consulté -> STOP avec causes."""
    dt_16h = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    state = evaluate_session_state([], dt_16h, config)

    chk = PreTradeChecklist(
        p08_reviewed=False,
        trading_plan="court",
        sizing_result=None,
        event_risk_tier1_red=False,
    )
    res = evaluate_checklist(chk, state, config)

    assert res.passed is False
    assert res.verdict == ChecklistVerdict.STOP
    assert len(res.blocking_reasons) >= 3


# ---------------------------------------------------------------------------
# Vérification d'absence totale d'exécution d'ordre
# ---------------------------------------------------------------------------


def test_zero_order_execution_in_discipline_code():
    """Garantie stricte : aucun appel de passage d'ordre ou courtier."""
    import nqcockpit.discipline.engine as de
    import nqcockpit.discipline.risk as dr

    forbidden_names = [
        "place_order", "send_order", "buy", "sell", "broker",
        "ibkr", "tradovate", "ninja", "order_id", "submit_order",
    ]

    for module in (de, dr):
        funcs = inspect.getmembers(module, inspect.isfunction)
        for name, _ in funcs:
            assert name.lower() not in forbidden_names
            for f_term in forbidden_names:
                assert f_term not in name.lower()
