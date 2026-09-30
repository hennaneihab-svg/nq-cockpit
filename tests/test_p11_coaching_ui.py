"""Tests de la page de coaching et analytics P11 (tests/test_p11_coaching_ui.py).

Couvre :
- Les visualisations Plotly (courbe d'équité, timeline tilt, segmentation, conformité)
- Le comportement avec données vides, échantillon insuffisant (< 60) et représentatif (>= 60)
- La superposition exacte des alertes de tilt sur les trades concernés
- L'intégration de la commande CLI coaching-ui (port par défaut 8504)
- La stricte réutilisation des fonctions d'engine et de reports sans duplication
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nqcockpit.cli import create_parser
from nqcockpit.config import AppConfig
from nqcockpit.journal.engine import (
    compute_performance_stats,
    generate_coaching_report,
    segment_by_setup_tag,
)
from nqcockpit.journal.models import (
    GammaRegime,
    TiltAlert,
    TradeDirection,
    TradeEntry,
    TradeOutcome,
    VolRegime,
)
from nqcockpit.ui.coaching_page import (
    build_compliance_timeline_figure,
    build_equity_curve_figure,
    build_segmentation_figure,
)


@pytest.fixture
def mock_config() -> AppConfig:
    """Configuration de test depuis config.yaml."""
    from nqcockpit.config import load_config
    return load_config()


def _make_dummy_trade(
    trade_id: str,
    session_date: str,
    r_realized: float,
    outcome: TradeOutcome,
    setup_tag: str = "FVG_REVERSAL",
    gamma_regime: GammaRegime = GammaRegime.POSITIVE,
    entry_time_ny: str = "09:45",
    contracts: int | None = 1,
    sl_moved: bool = False,
    early_exit: bool = False,
    window_name: str = "trade1",
    risk_pct_used: float = 0.5,
    recorded_at: datetime | None = None,
) -> TradeEntry:
    return TradeEntry(
        trade_id=trade_id,
        session_date=session_date,
        instrument="MNQ",
        direction=TradeDirection.LONG,
        entry_price=20000.0,
        stop_price=19980.0,
        exit_price=20000.0 + r_realized * 20.0,
        r_realized=r_realized,
        outcome=outcome,
        setup_tag=setup_tag,
        gamma_regime=gamma_regime,
        vol_regime=VolRegime.NORMAL,
        day_of_week=0,
        contracts=contracts,
        window_name=window_name,
        risk_pct_used=risk_pct_used,
        entry_time_ny=entry_time_ny,
        sl_moved=sl_moved,
        early_exit=early_exit,
        recorded_at=recorded_at or datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# 1. Tests CLI & Arguments
# ---------------------------------------------------------------------------


def test_cli_coaching_ui_parser():
    """Vérifie que la sous-commande coaching-ui est déclarée avec le port 8504 par défaut."""
    parser = create_parser()
    args = parser.parse_args(["journal", "coaching-ui"])
    assert args.subcommand == "journal"
    assert args.journal_action == "coaching-ui"
    assert args.port == 8504

    args_custom = parser.parse_args(["journal", "coaching-ui", "--port", "8510"])
    assert args_custom.port == 8510


# ---------------------------------------------------------------------------
# 2. Tests Courbe d'équité & Superposition Tilt
# ---------------------------------------------------------------------------


def test_build_equity_curve_empty():
    """Figure vide sans erreur si aucun trade."""
    fig = build_equity_curve_figure([])
    assert fig is not None
    assert len(fig.data) == 0
    assert any("Aucun trade" in str(ann.text) for ann in fig.layout.annotations)


def test_build_equity_curve_with_trades_and_tilt(mock_config: AppConfig):
    """Vérifie la progression du R cumulé et le placement des alertes de tilt."""
    trades = [
        _make_dummy_trade("t1", "2026-09-01", 1.5, TradeOutcome.WIN),
        _make_dummy_trade("t2", "2026-09-01", -1.0, TradeOutcome.LOSS),
        _make_dummy_trade("t3", "2026-09-02", 2.0, TradeOutcome.WIN),
    ]

    tilt_alert = TiltAlert(
        session_date="2026-09-01",
        reason="Deuxième perte consécutive",
        trades_involved=["t2"],
        pattern_type="série_pertes",
    )

    fig = build_equity_curve_figure(trades, tilt_alerts=[tilt_alert])
    assert len(fig.data) == 2  # Trace équité + Trace alertes tilt

    # Vérification trace équité
    trace_equity = fig.data[0]
    assert trace_equity.name == "R Cumulé"
    assert list(trace_equity.y) == [1.5, 0.5, 2.5]
    assert len(trace_equity.x) == 3

    # Vérification trace tilt
    trace_tilt = fig.data[1]
    assert trace_tilt.name == "Alertes de Tilt"
    assert len(trace_tilt.x) == 1
    assert trace_tilt.x[0] == "#2 (2026-09-01)"
    assert trace_tilt.y[0] == 0.5
    assert "Alerte Tilt : série_pertes" in trace_tilt.hovertext[0]


# ---------------------------------------------------------------------------
# 3. Tests Segmentation
# ---------------------------------------------------------------------------


def test_build_segmentation_figure_empty():
    """Segmentation vide retourne une figure propre."""
    fig = build_segmentation_figure({}, title="Test Seg", by_label="Label")
    assert fig is not None
    assert len(fig.data) == 0
    assert any("Aucun segment" in str(ann.text) for ann in fig.layout.annotations)


def test_build_segmentation_figure_populated():
    """Segmentation avec données produit les barres et annotations adaptées."""
    trades = [
        _make_dummy_trade("t1", "2026-09-01", 1.5, TradeOutcome.WIN, setup_tag="BREAKOUT"),
        _make_dummy_trade("t2", "2026-09-01", -1.0, TradeOutcome.LOSS, setup_tag="BREAKOUT"),
        _make_dummy_trade("t3", "2026-09-02", 2.0, TradeOutcome.WIN, setup_tag="PULLBACK"),
    ]
    segments = segment_by_setup_tag(trades, min_samples=2)
    fig = build_segmentation_figure(segments, title="Par Setup", by_label="Setup")
    assert len(fig.data) == 1
    bar_trace = fig.data[0]
    assert len(bar_trace.y) == 2
    # BREAKOUT a 2 trades (suffisant pour min_samples=2)
    # PULLBACK a 1 trade (n < seuil)
    assert any("BREAKOUT" in str(lbl) for lbl in bar_trace.y)
    assert any("(n < seuil)" in str(lbl) for lbl in bar_trace.y if "PULLBACK" in str(lbl))


# ---------------------------------------------------------------------------
# 4. Tests Évolution temporelle de la conformité
# ---------------------------------------------------------------------------


def test_build_compliance_timeline_empty(mock_config: AppConfig):
    """Conformité vide."""
    fig = build_compliance_timeline_figure([], mock_config)
    assert len(fig.data) == 0


def test_build_compliance_timeline_populated(mock_config: AppConfig):
    """Calcule le taux de conformité par séance."""
    trades = [
        # Séance 1 : 2 trades, tous conformes -> 100%
        _make_dummy_trade("t1", "2026-09-01", 1.0, TradeOutcome.WIN, sl_moved=False),
        _make_dummy_trade("t2", "2026-09-01", 1.0, TradeOutcome.WIN, sl_moved=False),
        # Séance 2 : 2 trades, 1 violation (sl_moved) -> 50%
        _make_dummy_trade("t3", "2026-09-02", -1.0, TradeOutcome.LOSS, sl_moved=True),
        _make_dummy_trade("t4", "2026-09-02", 1.0, TradeOutcome.WIN, sl_moved=False),
    ]
    fig = build_compliance_timeline_figure(trades, mock_config)
    assert len(fig.data) == 1
    bar_trace = fig.data[0]
    assert list(bar_trace.x) == ["2026-09-01", "2026-09-02"]
    assert list(bar_trace.y) == [100.0, 50.0]
    # Vert pour 100%, Rouge pour 50%
    assert list(bar_trace.marker.color) == ["#3fb950", "#f85149"]


# ---------------------------------------------------------------------------
# 5. Tests Cohérence des seuils & Non-invention de données
# ---------------------------------------------------------------------------


def test_sample_insufficient_handling(mock_config: AppConfig):
    """Sous le seuil minimal de 60 trades : sample_sufficient=False."""
    trades = [_make_dummy_trade(f"t{i}", "2026-09-01", 1.0, TradeOutcome.WIN) for i in range(10)]
    stats = compute_performance_stats(trades, min_trades=60, config=mock_config)
    assert stats.sample_sufficient is False
    assert stats.n_trades == 10
    assert stats.min_trades_required == 60
    assert stats.expectancy_r is None
    assert stats.profit_factor is None
    assert stats.max_drawdown_r == 0.0

    # Le rapport de coaching signale explicitement l'insuffisance
    coaching = generate_coaching_report(
        trades, period="hebdo", period_label="S36", config=mock_config
    )
    assert coaching.insufficient_data is True
    assert any("Échantillon insuffisant" in leak for leak in coaching.top_leaks)


def test_sample_sufficient_handling(mock_config: AppConfig):
    """Au-dessus ou égal au seuil de 60 trades, sample_sufficient=True."""
    trades = [_make_dummy_trade(f"t{i}", f"2026-09-{(i % 28) + 1:02d}", 1.0 if i % 2 == 0 else -1.0,
                                TradeOutcome.WIN if i % 2 == 0 else TradeOutcome.LOSS)
              for i in range(65)]
    stats = compute_performance_stats(trades, min_trades=60, config=mock_config)
    assert stats.sample_sufficient is True
    assert stats.n_trades == 65
    assert stats.expectancy_r is not None
    assert stats.profit_factor is not None
    assert stats.max_drawdown_r is not None
