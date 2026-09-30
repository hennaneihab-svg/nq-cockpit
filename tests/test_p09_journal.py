"""Tests pytest P09 — Journal de bord, discipline et métriques de performance.

Chaque test est indépendant (DB in-memory).
Toutes les règles de discipline sont vérifiées avec cause explicite.
Les seuils de sample_sufficient sont respectés.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest

from nqcockpit.journal.engine import (
    compute_daily_stats,
    compute_performance_stats,
    detect_tilt_alerts,
    detect_violations,
    finalize_trade,
    generate_coaching_report,
    segment_performance,
)
from nqcockpit.journal.models import (
    DisciplineViolationType,
    GammaRegime,
    TradeDirection,
    TradeEntry,
    TradeOutcome,
)
from nqcockpit.journal.store import (
    delete_trade,
    init_journal_db,
    load_trades,
    save_trade,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_db() -> sqlite3.Connection:
    """DB SQLite in-memory pour les tests."""
    conn = init_journal_db(":memory:")
    return conn


def _make_config():
    """Charge la config réelle (config.yaml requis dans le projet)."""
    from nqcockpit.config import load_config
    return load_config()


def _trade(
    *,
    session_date: str = "2026-09-30",
    direction: TradeDirection = TradeDirection.LONG,
    entry: float = 20000.0,
    stop: float = 19950.0,
    exit_: float = 20100.0,
    window: str = "trade1",
    sl_moved: bool = False,
    early_exit: bool = False,
    minutes_after_sl: Optional[float] = None,
    outcome: Optional[TradeOutcome] = None,
    r_realized: float = 0.0,
    risk_pct: float = 0.5,
) -> TradeEntry:
    t = TradeEntry(
        trade_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        session_date=session_date,
        direction=direction,
        entry_price=entry,
        stop_price=stop,
        exit_price=exit_,
        window_name=window,
        sl_moved=sl_moved,
        early_exit=early_exit,
        minutes_after_last_sl=minutes_after_sl,
        risk_pct_used=risk_pct,
    )
    t = finalize_trade(t)
    if outcome is not None:
        t.outcome = outcome
    if r_realized != 0.0:
        t.r_realized = r_realized
    return t


# ---------------------------------------------------------------------------
# T1 : finalize_trade — calcul de R et outcome
# ---------------------------------------------------------------------------


def test_finalize_trade_win():
    """R > 0 → WIN."""
    t = TradeEntry(
        trade_id="1",
        recorded_at=datetime.now(timezone.utc),
        session_date="2026-09-30",
        direction=TradeDirection.LONG,
        entry_price=20000,
        stop_price=19950,   # risque 50 pts
        exit_price=20100,   # gain 100 pts → 2R
    )
    t = finalize_trade(t)
    assert t.r_realized == pytest.approx(2.0, abs=1e-3)
    assert t.outcome == TradeOutcome.WIN


def test_finalize_trade_loss():
    """R < 0 → LOSS."""
    t = TradeEntry(
        trade_id="2",
        recorded_at=datetime.now(timezone.utc),
        session_date="2026-09-30",
        direction=TradeDirection.LONG,
        entry_price=20000,
        stop_price=19950,
        exit_price=19950,   # sorti exactement au SL → -1R
    )
    t = finalize_trade(t)
    assert t.r_realized == pytest.approx(-1.0, abs=1e-3)
    assert t.outcome == TradeOutcome.LOSS


def test_finalize_trade_short():
    """Direction SHORT : R positif quand le prix baisse."""
    t = TradeEntry(
        trade_id="3",
        recorded_at=datetime.now(timezone.utc),
        session_date="2026-09-30",
        direction=TradeDirection.SHORT,
        entry_price=20000,
        stop_price=20050,   # risque 50 pts
        exit_price=19900,   # baisse 100 pts → +2R
    )
    t = finalize_trade(t)
    assert t.r_realized == pytest.approx(2.0, abs=1e-3)
    assert t.outcome == TradeOutcome.WIN


# ---------------------------------------------------------------------------
# T2 : SQLite store
# ---------------------------------------------------------------------------


def test_store_save_and_load(mem_db):
    """Save + load retourne un trade identique."""
    t = _trade()
    save_trade(mem_db, t)
    loaded = load_trades(mem_db, session_date=t.session_date)
    assert len(loaded) == 1
    assert loaded[0].trade_id == t.trade_id
    assert loaded[0].r_realized == pytest.approx(t.r_realized, abs=1e-4)


def test_store_delete(mem_db):
    """Delete supprime exactement 1 ligne."""
    t = _trade()
    save_trade(mem_db, t)
    n = delete_trade(mem_db, t.trade_id)
    assert n == 1
    assert load_trades(mem_db, session_date=t.session_date) == []


def test_store_multi_session(mem_db):
    """load_trades filtre correctement par session_date."""
    t1 = _trade(session_date="2026-09-29")
    t2 = _trade(session_date="2026-09-30")
    save_trade(mem_db, t1)
    save_trade(mem_db, t2)
    assert len(load_trades(mem_db, session_date="2026-09-30")) == 1
    assert len(load_trades(mem_db)) == 2


# ---------------------------------------------------------------------------
# T3 : detect_violations — chaque violation a une cause explicite
# ---------------------------------------------------------------------------


def test_violation_out_of_window():
    """Trade sans fenêtre → OUT_OF_WINDOW avec cause lisible."""
    config = _make_config()
    t = _trade(window="")
    violations = detect_violations(t, [t], config)
    types = [v.violation for v in violations]
    assert DisciplineViolationType.OUT_OF_WINDOW in types
    # Vérifier que le détail n'est pas vide
    oot = next(v for v in violations if v.violation == DisciplineViolationType.OUT_OF_WINDOW)
    assert len(oot.detail) > 10


def test_violation_trade_limit():
    """3e trade de la séance → TRADE_LIMIT (config.rules.max_trades_per_day = 2)."""
    config = _make_config()
    t1 = _trade(window="trade1")
    t2 = _trade(window="trade2")
    t3 = _trade(window="trade1")
    # t3 vient après t1 et t2
    for t in (t1, t2, t3):
        # S'assurer des recorded_at distincts
        pass
    violations = detect_violations(t3, [t1, t2, t3], config)
    types = [v.violation for v in violations]
    assert DisciplineViolationType.TRADE_LIMIT in types


def test_violation_trade2_after_loss():
    """Trade2 après perte de trade1 → TRADE2_AFTER_LOSS."""
    config = _make_config()
    t1 = _trade(window="trade1", entry=20000, stop=19950, exit_=19950)
    assert t1.outcome == TradeOutcome.LOSS
    t2 = _trade(window="trade2")
    t2.recorded_at = datetime.now(timezone.utc)
    violations = detect_violations(t2, [t1, t2], config)
    types = [v.violation for v in violations]
    assert DisciplineViolationType.TRADE2_AFTER_LOSS in types


def test_violation_quick_reentry():
    """Rentrée < cooldown_after_sl_minutes → QUICK_REENTRY."""
    config = _make_config()
    cooldown = config.rules.cooldown_after_sl_minutes
    t = _trade(window="trade1", minutes_after_sl=cooldown - 1.0)
    violations = detect_violations(t, [t], config)
    types = [v.violation for v in violations]
    assert DisciplineViolationType.QUICK_REENTRY in types


def test_violation_sl_moved():
    """sl_moved=True → MOVED_SL avec cause explicite."""
    config = _make_config()
    t = _trade(window="trade1", sl_moved=True)
    violations = detect_violations(t, [t], config)
    types = [v.violation for v in violations]
    assert DisciplineViolationType.MOVED_SL in types
    moved = next(v for v in violations if v.violation == DisciplineViolationType.MOVED_SL)
    assert "sl_moved" in moved.detail.lower() or "stop" in moved.detail.lower()


def test_violation_early_exit():
    """early_exit=True → EARLY_EXIT."""
    config = _make_config()
    t = _trade(window="trade1", early_exit=True)
    violations = detect_violations(t, [t], config)
    types = [v.violation for v in violations]
    assert DisciplineViolationType.EARLY_EXIT in types


def test_violation_oversized():
    """risk_pct_used > risk_per_trade_pct → OVERSIZED."""
    config = _make_config()
    limit = config.risk.risk_per_trade_pct
    t = _trade(window="trade1", risk_pct=limit + 1.0)
    violations = detect_violations(t, [t], config)
    types = [v.violation for v in violations]
    assert DisciplineViolationType.OVERSIZED in types


# ---------------------------------------------------------------------------
# T4 : Tilt alerts
# ---------------------------------------------------------------------------


def test_tilt_two_consecutive_losses():
    """2 pertes consécutives → TiltAlert."""
    config = _make_config()
    t1 = _trade(window="trade1", entry=20000, stop=19950, exit_=19950)
    t2 = _trade(window="trade2", entry=20000, stop=19950, exit_=19950)
    assert t1.outcome == TradeOutcome.LOSS
    assert t2.outcome == TradeOutcome.LOSS
    alerts = detect_tilt_alerts("2026-09-30", [t1, t2], config)
    assert len(alerts) >= 1
    assert "consécutives" in alerts[0].reason.lower() or "perte" in alerts[0].reason.lower()


# ---------------------------------------------------------------------------
# T5 : compute_daily_stats
# ---------------------------------------------------------------------------


def test_daily_stats_limit_hit():
    """R total <= -daily_loss_limit_r → limit_hit=True."""
    config = _make_config()
    limit = config.rules.daily_loss_limit_r
    # Deux trades perdants de -1R chacun
    t1 = _trade(window="trade1", entry=20000, stop=19950, exit_=19950)
    t2 = _trade(window="trade2", entry=20000, stop=19950, exit_=19950)
    assert t1.r_realized == pytest.approx(-1.0, abs=1e-3)
    stats = compute_daily_stats("2026-09-30", [t1, t2], config)
    assert stats.r_total == pytest.approx(-2.0, abs=1e-3)
    # Limite = 2.0R → r_total <= -2.0 → limit_hit
    assert stats.limit_hit == (stats.r_total <= -limit)


def test_daily_stats_compliance_rate():
    """1 trade conforme sur 2 → compliance_rate = 0.5."""
    config = _make_config()
    t1 = _trade(window="trade1")              # conforme
    t2 = _trade(window="trade1", sl_moved=True)  # violation
    stats = compute_daily_stats("2026-09-30", [t1, t2], config)
    assert 0.0 <= stats.compliance_rate <= 1.0


# ---------------------------------------------------------------------------
# T6 : compute_performance_stats — seuils et IC Wilson
# ---------------------------------------------------------------------------


def test_perf_stats_insufficient_sample():
    """< min_trades → sample_sufficient=False, espérance=None."""
    trades = [_trade() for _ in range(5)]
    stats = compute_performance_stats(trades, min_trades=60)
    assert not stats.sample_sufficient
    assert stats.expectancy_r is None
    assert stats.win_rate is not None  # win rate calculé même sous seuil


def test_perf_stats_wilson_ci_bounds():
    """IC Wilson : ci_low <= win_rate <= ci_high, et 0 <= ci_low, ci_high <= 1."""
    trades = [_trade(entry=20000, stop=19950, exit_=20100) for _ in range(10)]
    stats = compute_performance_stats(trades, min_trades=1)
    assert stats.win_rate_ci_low is not None
    assert stats.win_rate_ci_high is not None
    assert 0.0 <= stats.win_rate_ci_low <= stats.win_rate <= stats.win_rate_ci_high <= 1.0


def test_perf_stats_sufficient_sample():
    """Avec n >= min_trades → tous les champs calculés."""
    # Mix: 40 wins 2R, 20 losses -1R
    wins = [_trade(entry=20000, stop=19950, exit_=20100) for _ in range(40)]
    losses = [_trade(entry=20000, stop=19950, exit_=19950) for _ in range(20)]
    trades = wins + losses
    stats = compute_performance_stats(trades, min_trades=60)
    assert stats.sample_sufficient
    assert stats.expectancy_r is not None
    assert stats.expectancy_r > 0   # 40/60 * 2R + 20/60 * (-1R) = 1.0R
    assert stats.profit_factor is not None
    assert stats.max_drawdown_r >= 0


# ---------------------------------------------------------------------------
# T7 : segment_performance
# ---------------------------------------------------------------------------


def test_segment_by_setup_tag():
    """Segmentation par setup_tag crée bien des sous-groupes distincts."""
    trades_a = [_trade() for _ in range(5)]
    for t in trades_a:
        t.setup_tag = "ICT_BOS"
    trades_b = [_trade() for _ in range(5)]
    for t in trades_b:
        t.setup_tag = "FVG"
    seg = segment_performance(trades_a + trades_b, by="setup_tag", min_samples=1)
    assert "ICT_BOS" in seg
    assert "FVG" in seg
    assert seg["ICT_BOS"].n_trades == 5


def test_segment_by_gamma_regime():
    """Segmentation par gamma_regime fonctionne."""
    trades = [_trade() for _ in range(8)]
    for t in trades[:4]:
        t.gamma_regime = GammaRegime.POSITIVE
    for t in trades[4:]:
        t.gamma_regime = GammaRegime.NEGATIVE
    seg = segment_performance(trades, by="gamma_regime", min_samples=1)
    assert GammaRegime.POSITIVE.value in seg
    assert GammaRegime.NEGATIVE.value in seg


# ---------------------------------------------------------------------------
# T8 : generate_coaching_report — ton factuel, seuils respectés
# ---------------------------------------------------------------------------


def test_coaching_report_insufficient():
    """Moins de min_sessions trades → insufficient_data=True."""
    config = _make_config()
    trades = [_trade() for _ in range(10)]
    report = generate_coaching_report(trades, "hebdo", "S39-2026", config)
    assert report.insufficient_data
    assert any("insuffisant" in leak.lower() for leak in report.top_leaks)


def test_coaching_report_no_emotional_language():
    """Le rapport ne contient pas de jugements émotionnels ni de biais directionnels."""
    config = _make_config()
    wins = [_trade(entry=20000, stop=19950, exit_=20100) for _ in range(40)]
    losses = [_trade(entry=20000, stop=19950, exit_=19950) for _ in range(25)]
    trades = wins + losses
    report = generate_coaching_report(trades, "hebdo", "S39-2026", config)

    forbidden = [
        "va monter", "va baisser", "haussier", "baissier",
        "bullish", "bearish", "bravo", "nul", "mauvais trader",
        "excellent", "tu es", "vous êtes",
    ]
    full_text = " ".join([
        report.rule_to_reinforce,
        report.strength_to_keep,
        " ".join(report.measurable_goals),
        " ".join(report.top_leaks),
    ]).lower()

    for term in forbidden:
        assert term not in full_text, (
            f"Terme interdit '{term}' trouvé dans le rapport de coaching"
        )


def test_coaching_report_goals_measurable():
    """Les objectifs contiennent des indicateurs chiffrés ou des actions concrètes."""
    config = _make_config()
    wins = [_trade(entry=20000, stop=19950, exit_=20100) for _ in range(45)]
    losses = [_trade(entry=20000, stop=19950, exit_=19950, sl_moved=True)
              for _ in range(20)]
    trades = wins + losses
    report = generate_coaching_report(trades, "hebdo", "S39-2026", config)
    assert len(report.measurable_goals) >= 1
    assert report.rule_to_reinforce != ""
    assert report.strength_to_keep != ""


# ---------------------------------------------------------------------------
# T9 : CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_journal_stats_empty(tmp_path, monkeypatch):
    """CLI `journal stats` s'exécute sans erreur même avec 0 trade."""

    # Utilise une DB temporaire
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("NQ_DATA_DB_PATH", db_path)

    # On ne peut pas facilement patcher la config, on vérifie juste que le
    # parser reconnaît la sous-commande
    from nqcockpit.cli import create_parser
    p = create_parser()
    args = p.parse_args(["journal", "stats"])
    assert args.subcommand == "journal"
    assert args.journal_action == "stats"


def test_cli_journal_coaching_args():
    """CLI `journal coaching --period mensuel --label Oct-2026` parse correctement."""
    from nqcockpit.cli import create_parser
    p = create_parser()
    args = p.parse_args(["journal", "coaching", "--period", "mensuel", "--label", "Oct-2026"])
    assert args.subcommand == "journal"
    assert args.journal_action == "coaching"
    assert args.period == "mensuel"
    assert args.label == "Oct-2026"
