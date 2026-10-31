"""Tests unitaires pour les helpers de calcul de la page Coaching.

Couvre les fonctions pures de ``nqcockpit.coaching.analytics`` :
drawdown, heatmap, table de segments, coût des violations, insights
(gestion des faibles échantillons) et état vide. Aucun accès DB ni Streamlit.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nqcockpit.coaching.analytics import (
    MIN_SEGMENT_SAMPLES,
    NY_HOURS,
    aggregate_heatmap,
    compute_drawdown_series,
    compute_insights,
    compute_loss_streaks,
    compute_max_drawdown,
    compute_rule_break_cost,
    current_loss_streak,
    heatmap_grid,
    segment_table_rows,
    sort_trades_chronologically,
)
from nqcockpit.journal.engine import segment_performance
from nqcockpit.journal.models import (
    GammaRegime,
    TradeDirection,
    TradeEntry,
    TradeOutcome,
    VolRegime,
)


def _trade(
    trade_id: str,
    r: float,
    *,
    outcome: TradeOutcome | None = None,
    entry_time_ny: datetime | None = None,
    recorded_at: datetime | None = None,
    setup_tag: str = "SETUP_A",
    gamma_regime: GammaRegime = GammaRegime.POSITIVE,
    vol_regime: VolRegime = VolRegime.NORMAL,
    sl_moved: bool = False,
    early_exit: bool = False,
    event_risk_label: str = "",
) -> TradeEntry:
    if outcome is None:
        outcome = TradeOutcome.WIN if r > 0 else TradeOutcome.LOSS
    base = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    return TradeEntry(
        trade_id=trade_id,
        recorded_at=recorded_at or base,
        session_date=(entry_time_ny or base).strftime("%Y-%m-%d"),
        instrument="MNQ",
        direction=TradeDirection.LONG,
        entry_price=20000.0,
        stop_price=19980.0,
        exit_price=20000.0 + r * 20.0,
        r_realized=r,
        outcome=outcome,
        entry_time_ny=entry_time_ny,
        setup_tag=setup_tag,
        gamma_regime=gamma_regime,
        vol_regime=vol_regime,
        day_of_week=0,
        sl_moved=sl_moved,
        early_exit=early_exit,
        event_risk_label=event_risk_label,
    )


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


def test_drawdown_series_cumulative_and_underwater():
    trades = [
        _trade("t1", 1.0),
        _trade("t2", -0.5),
        _trade("t3", 2.0),
        _trade("t4", -3.0),
    ]
    points = compute_drawdown_series(trades)
    assert [p.cum_r for p in points] == [1.0, 0.5, 2.5, -0.5]
    assert [p.peak_r for p in points] == [1.0, 1.0, 2.5, 2.5]
    assert [p.underwater_r for p in points] == [0.0, 0.5, 0.0, 3.0]


def test_max_drawdown_returns_trough_index():
    trades = [
        _trade("t1", 1.0),
        _trade("t2", -2.0),
        _trade("t3", 1.0),
    ]
    max_dd, trough_index = compute_max_drawdown(trades)
    assert max_dd == 2.0
    assert trough_index == 1  # deepest point is t2 (cum = -1.0, peak = 1.0)


def test_max_drawdown_empty():
    assert compute_max_drawdown([]) == (0.0, -1)


def test_current_loss_streak_counts_tail_losses():
    trades = [
        _trade("t1", 1.0, outcome=TradeOutcome.WIN),
        _trade("t2", -1.0, outcome=TradeOutcome.LOSS),
        _trade("t3", -1.0, outcome=TradeOutcome.LOSS),
    ]
    assert current_loss_streak(trades) == 2


def test_sort_trades_chronologically_uses_entry_time():
    trades = [
        _trade("late", 1.0, entry_time_ny=datetime(2026, 9, 2, 10, 0)),
        _trade("early", 1.0, entry_time_ny=datetime(2026, 9, 1, 10, 0)),
    ]
    ordered = sort_trades_chronologically(trades)
    assert [t.trade_id for t in ordered] == ["early", "late"]


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------


def test_aggregate_heatmap_buckets_by_hour_and_weekday():
    mon_10 = datetime(2026, 9, 7, 10, 30)  # Monday
    mon_11 = datetime(2026, 9, 7, 11, 15)  # Monday
    tue_10 = datetime(2026, 9, 8, 10, 0)   # Tuesday
    trades = [
        _trade("t1", 1.0, entry_time_ny=mon_10),
        _trade("t2", -0.5, entry_time_ny=mon_10),
        _trade("t3", 2.0, entry_time_ny=mon_11),
        _trade("t4", 0.5, entry_time_ny=tue_10),
    ]
    cells = aggregate_heatmap(trades)
    assert cells[(10, 0)].n == 2  # Monday 10:00 -> 2 trades
    assert round(cells[(10, 0)].total_r, 4) == 0.5
    assert cells[(11, 0)].n == 1
    assert cells[(10, 1)].n == 1


def test_heatmap_grid_shape_and_values():
    mon_10 = datetime(2026, 9, 7, 10, 0)
    trades = [_trade("t1", 1.5, entry_time_ny=mon_10)]
    hours, z_exp, z_n, z_total = heatmap_grid(trades)
    assert hours == NY_HOURS
    assert len(z_exp) == 5  # 5 weekdays
    assert len(z_exp[0]) == len(NY_HOURS)
    hour_index = NY_HOURS.index(10)
    assert z_n[0][hour_index] == 1
    assert round(z_exp[0][hour_index], 3) == 1.5


# ---------------------------------------------------------------------------
# Segment table
# ---------------------------------------------------------------------------


def test_segment_table_rows_sorts_and_flags_low_sample():
    trades = (
        [_trade(f"a{i}", 1.0, setup_tag="BIG") for i in range(15)]
        + [_trade(f"b{i}", -0.5, setup_tag="SMALL") for i in range(3)]
    )
    segments = segment_performance(trades, by="setup_tag", min_samples=MIN_SEGMENT_SAMPLES)
    rows = segment_table_rows(segments)
    assert [r.label for r in rows] == ["BIG", "SMALL"]
    assert rows[0].n == 15
    assert rows[0].low_sample is False
    assert rows[1].n == 3
    assert rows[1].low_sample is True
    assert rows[0].expectancy_r > rows[1].expectancy_r


def test_segment_table_rows_empty():
    assert segment_table_rows({}) == []


# ---------------------------------------------------------------------------
# Cost of breaking rules
# ---------------------------------------------------------------------------


def test_rule_break_cost_gap_and_effects():
    trades = [
        _trade("c1", 1.0),
        _trade("c2", 1.0),
        _trade("c3", 1.0),
        _trade("nc1", -1.0, sl_moved=True),
        _trade("nc2", -1.0, sl_moved=True),
    ]
    cost = compute_rule_break_cost(trades, config=None)
    assert cost.n_compliant == 3
    assert cost.n_noncompliant == 2
    assert round(cost.expectancy_compliant, 4) == 1.0
    assert round(cost.expectancy_noncompliant, 4) == -1.0
    assert round(cost.gap_per_trade_r, 4) == 2.0
    assert round(cost.total_r_noncompliant, 4) == -2.0
    assert round(cost.sl_moved_avg_r, 4) == -1.0
    assert round(cost.no_sl_moved_avg_r, 4) == 1.0


# ---------------------------------------------------------------------------
# Loss streaks
# ---------------------------------------------------------------------------


def test_compute_loss_streaks():
    trades = [
        _trade("t1", 1.0, outcome=TradeOutcome.WIN),
        _trade("t2", -1.0, outcome=TradeOutcome.LOSS),
        _trade("t3", -1.0, outcome=TradeOutcome.LOSS),
        _trade("t4", 1.0, outcome=TradeOutcome.WIN),
        _trade("t5", -1.0, outcome=TradeOutcome.LOSS),
    ]
    streaks = compute_loss_streaks(trades)
    assert len(streaks) == 1
    assert streaks[0].length == 2


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


def test_insights_empty_state():
    assert compute_insights([]) == []


def test_insights_best_worst_setup_and_confidence():
    trades = (
        [_trade(f"w{i}", 1.0, setup_tag="WINNER") for i in range(12)]
        + [_trade(f"l{i}", -0.5, setup_tag="LOSER") for i in range(8)]
        + [_trade("nc", -1.0, sl_moved=True, setup_tag="WINNER")]
    )
    insights = compute_insights(trades, config=None)
    kinds = {i.kind for i in insights}
    assert "best_setup" in kinds
    assert "worst_setup" in kinds

    best = next(i for i in insights if i.kind == "best_setup")
    worst = next(i for i in insights if i.kind == "worst_setup")
    assert best.label == "WINNER"
    assert best.value > 0
    assert best.confidence == "medium"  # 13 trades >= 12
    assert worst.label == "LOSER"
    assert worst.value < 0
    assert worst.confidence == "low"  # 8 trades < 12

    # A non-compliant trade triggers a rule-break finding.
    assert any(i.kind == "rule_break" for i in insights)


def test_insights_confidence_high_at_sixty():
    trades = [_trade(f"t{i}", 1.0, setup_tag="BIG") for i in range(60)]
    insights = compute_insights(trades, config=None)
    best = next(i for i in insights if i.kind == "best_setup")
    assert best.confidence == "high"


@pytest.mark.parametrize("n", [0, 1, 3])
def test_helpers_never_raise_on_small_samples(n):
    trades = [_trade(f"t{i}", 1.0 if i % 2 == 0 else -1.0) for i in range(n)]
    # All of these must return without raising on 0/1/3 trades.
    compute_drawdown_series(trades)
    compute_max_drawdown(trades)
    aggregate_heatmap(trades)
    heatmap_grid(trades)
    segment_table_rows(segment_performance(trades, by="setup_tag"))
    compute_rule_break_cost(trades, config=None)
    compute_insights(trades, config=None)
    compute_loss_streaks(trades)
    current_loss_streak(trades)
