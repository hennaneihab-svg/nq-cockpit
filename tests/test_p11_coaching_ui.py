"""Tests de la page Coaching & Analytics P11 (tests/test_p11_coaching_ui.py).

Couvre :
- Les visualisations Plotly (courbe d'équité chronologique, heatmap, segmentation)
- Le comportement avec données vides, échantillon insuffisant (< 60) et suffisant (>= 60)
- La superposition des marqueurs de tilt sur la courbe d'équité
- La commande CLI coaching-ui (port par défaut 8504)
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
    build_equity_curve_figure,
    build_heatmap_figure,
    build_segmentation_figure,
)


@pytest.fixture
def mock_config() -> AppConfig:
    """Configuration de test depuis config.yaml."""
    from nqcockpit.config import load_config

    return load_config()


@pytest.fixture(autouse=True)
def _force_english_ui(monkeypatch):
    """Libellés EN déterministes (langue par défaut configurée, ui.language=EN)."""
    import nqcockpit.ui.i18n as i18n

    monkeypatch.setattr(i18n, "get_lang", lambda: "EN")


def _make_dummy_trade(
    trade_id: str,
    session_date: str,
    r_realized: float,
    outcome: TradeOutcome,
    setup_tag: str = "FVG_REVERSAL",
    gamma_regime: GammaRegime = GammaRegime.POSITIVE,
    entry_time_ny: datetime | None = None,
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
# 2. Tests Courbe d'équité & superposition tilt
# ---------------------------------------------------------------------------


def test_build_equity_curve_empty():
    """Figure vide sans erreur si aucun trade."""
    fig = build_equity_curve_figure([])
    assert fig is not None
    assert len(fig.data) == 0
    assert any("No trades available" in str(ann.text) for ann in fig.layout.annotations)


def test_build_equity_curve_with_trades_and_tilt():
    """Vérifie la progression du R cumulé, l'abscisse chronologique et les tilt."""
    trades = [
        _make_dummy_trade("t1", "2026-09-01", 1.5, TradeOutcome.WIN,
                           entry_time_ny=datetime(2026, 9, 1, 10, 0)),
        _make_dummy_trade("t2", "2026-09-01", -1.0, TradeOutcome.LOSS,
                           entry_time_ny=datetime(2026, 9, 1, 11, 0)),
        _make_dummy_trade("t3", "2026-09-02", 2.0, TradeOutcome.WIN,
                           entry_time_ny=datetime(2026, 9, 2, 10, 0)),
    ]

    tilt_alert = TiltAlert(
        session_date="2026-09-01",
        reason="Deuxième perte consécutive",
        trades_involved=["t2"],
        pattern_type="série_pertes",
    )

    fig = build_equity_curve_figure(trades, tilt_alerts=[tilt_alert])
    names = [trace.name for trace in fig.data]
    assert "Cumulative R" in names

    cumulative = next(trace for trace in fig.data if trace.name == "Cumulative R")
    assert list(cumulative.y) == [1.5, 0.5, 2.5]
    # L'abscisse est désormais une date/heure, pas un index de séquence.
    assert all(isinstance(x, datetime) for x in cumulative.x)

    # Le trade de tilt est marqué sur la courbe.
    tilt_trace = next(trace for trace in fig.data if trace.name == "Tilt alert")
    assert list(tilt_trace.x) == [datetime(2026, 9, 1, 11, 0)]
    assert list(tilt_trace.y) == [0.5]


# ---------------------------------------------------------------------------
# 3. Tests Segmentation (barres de régime)
# ---------------------------------------------------------------------------


def test_build_segmentation_figure_empty():
    """Segmentation vide retourne une figure propre."""
    fig = build_segmentation_figure({}, title="Test Seg", by_label="Label")
    assert fig is not None
    assert len(fig.data) == 0
    assert any("No segments available" in str(ann.text) for ann in fig.layout.annotations)


def test_build_segmentation_figure_populated():
    """Segmentation avec données produit les barres et le suffixe « low sample »."""
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
    assert any("BREAKOUT" in str(lbl) for lbl in bar_trace.y)
    assert any("(low sample)" in str(lbl) for lbl in bar_trace.y if "PULLBACK" in str(lbl))


# ---------------------------------------------------------------------------
# 4. Tests Heatmap
# ---------------------------------------------------------------------------


def test_build_heatmap_figure_empty():
    """Heatmap vide retourne une figure propre."""
    fig = build_heatmap_figure([])
    assert len(fig.data) == 0
    assert any("No trades available" in str(ann.text) for ann in fig.layout.annotations)


def test_build_heatmap_figure_populated():
    """Heatmap avec données produit une trace Heatmap."""
    trades = [
        _make_dummy_trade("t1", "2026-09-07", 1.0, TradeOutcome.WIN,
                           entry_time_ny=datetime(2026, 9, 7, 10, 0)),
    ]
    fig = build_heatmap_figure(trades)
    assert len(fig.data) == 1
    assert fig.data[0].type == "heatmap"


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

    coaching = generate_coaching_report(
        trades, period="hebdo", period_label="S36", config=mock_config
    )
    assert coaching.insufficient_data is True
    assert any("Échantillon insuffisant" in leak for leak in coaching.top_leaks)


def test_sample_sufficient_handling(mock_config: AppConfig):
    """Au-dessus ou égal au seuil de 60 trades, sample_sufficient=True."""
    trades = [
        _make_dummy_trade(
            f"t{i}",
            f"2026-09-{(i % 28) + 1:02d}",
            1.0 if i % 2 == 0 else -1.0,
            TradeOutcome.WIN if i % 2 == 0 else TradeOutcome.LOSS,
        )
        for i in range(65)
    ]
    stats = compute_performance_stats(trades, min_trades=60, config=mock_config)
    assert stats.sample_sufficient is True
    assert stats.n_trades == 65
    assert stats.expectancy_r is not None
    assert stats.profit_factor is not None
    assert stats.max_drawdown_r is not None


# ---------------------------------------------------------------------------
# 6. Rendu headless de la page complète avec une fixture synthétique (150 trades)
# ---------------------------------------------------------------------------


def _render_coaching_from_env() -> None:
    """Point d'entrée AppTest : importe et rend la page Coaching."""
    from nqcockpit.ui.coaching_page import render_coaching_app

    render_coaching_app()


def test_coaching_page_renders_with_synthetic_fixture(tmp_path, monkeypatch):
    """Rend la page Coaching headless sur 150 trades sans exception."""
    from streamlit.testing.v1 import AppTest

    from nqcockpit.journal.store import init_journal_db, save_trade

    db_path = tmp_path / "coaching_fixture.db"
    conn = init_journal_db(db_path)
    for i in range(150):
        day = (i % 28) + 1
        trade = _make_dummy_trade(
            f"t{i}",
            f"2026-09-{day:02d}",
            1.2 if i % 3 != 0 else -0.9,
            TradeOutcome.WIN if i % 3 != 0 else TradeOutcome.LOSS,
            setup_tag="BREAKOUT" if i % 2 == 0 else "PULLBACK",
            entry_time_ny=datetime(2026, 9, day, 9 + (i % 8), 0),
            sl_moved=(i % 5 == 0),
            early_exit=(i % 7 == 0),
        )
        save_trade(conn, trade)
    conn.close()

    monkeypatch.setenv("NQ_DATA_DB_PATH", str(db_path))

    app = AppTest.from_function(_render_coaching_from_env, default_timeout=120)
    app.run()
    assert not app.exception, app.exception
