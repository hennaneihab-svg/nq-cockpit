"""Tests P13 — démarrage Streamlit : rafraîchissement des niveaux et planificateur."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from nqcockpit.config import load_config
from nqcockpit.data.cboe import CboeChainSnapshot
from nqcockpit.data.db import apply_migrations, insert_snapshot
from nqcockpit.data.models import Bar, DataStatus
from nqcockpit.profile.engine import build_day_profile
from nqcockpit.profile.models import (
    ComponentHealth,
    DayProfile,
    NoTradeAssessment,
)

UTC = timezone.utc
NOW_UTC = datetime(2026, 9, 30, 14, 30, tzinfo=UTC)


def _insert_snapshot(conn: sqlite3.Connection, timestamp_utc: datetime, spot: float = 20000.0):
    insert_snapshot(
        conn=conn,
        timestamp_utc=timestamp_utc,
        spot=spot,
        regime="AMORTISSEUR",
        gamma_flip=19800.0,
        call_wall=20500.0,
        put_support=19500.0,
        expected_move=300.0,
        basis=300.0,
        synthetic_basis=305.0,
        source="CBOE",
        status="OK",
        payload={},
    )


def _fake_chain() -> CboeChainSnapshot:
    df = pd.DataFrame(
        [
            {
                "contract": "NDX261016C20000000",
                "expiry": date(2026, 10, 16),
                "type": "C",
                "strike": 20000.0,
                "bid": 10.0,
                "ask": 12.0,
                "iv": 0.20,
                "open_interest": 1000.0,
                "gamma": 0.0001,
            }
        ]
    )
    return CboeChainSnapshot(
        symbol="NDX",
        spot=20000.0,
        options_df=df,
        latest_quote_time_utc=NOW_UTC - timedelta(minutes=1),
        fetched_at_utc=NOW_UTC,
        age_minutes=1.0,
        status=DataStatus.OK,
    )


def _fake_bars() -> SimpleNamespace:
    bar = Bar(
        timestamp_utc=NOW_UTC - timedelta(minutes=2),
        open=20200.0,
        high=20250.0,
        low=20150.0,
        close=20250.0,
        volume=10.0,
    )
    return SimpleNamespace(bars=[bar])


def test_stale_snapshot_triggers_single_refresh(tmp_path: Path, monkeypatch):
    """Un snapshot plus vieux que le seuil déclenche UN rafraîchissement CBOE."""
    conn = sqlite3.connect(str(tmp_path / "refresh.db"))
    apply_migrations(conn)
    _insert_snapshot(conn, NOW_UTC - timedelta(hours=2))

    calls = {"chain": 0}

    def _fetch_chain():
        calls["chain"] += 1
        return _fake_chain()

    monkeypatch.setattr("nqcockpit.data.cboe.fetch_cboe_options_chain", _fetch_chain)
    monkeypatch.setattr(
        "nqcockpit.data.fetcher.DataFetcher.fetch_yahoo_bars",
        lambda self, *args, **kwargs: _fake_bars(),
    )

    profile = build_day_profile(conn=conn, config=load_config(), now_utc=NOW_UTC)

    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    latest_ts = conn.execute(
        "SELECT timestamp_utc FROM snapshots ORDER BY timestamp_utc DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()

    assert calls["chain"] == 1
    assert count == 2  # ancien snapshot conservé + snapshot frais
    assert datetime.fromisoformat(latest_ts) == NOW_UTC
    assert profile.spot_nq is not None
    assert profile.component_statuses["gamma"].status != "STALE"


def test_failed_refresh_keeps_old_snapshot_as_stale(tmp_path: Path, monkeypatch):
    """Échec de fetch : l'ancien snapshot reste utilisé, marqué STALE avec son âge."""
    conn = sqlite3.connect(str(tmp_path / "refresh_fail.db"))
    apply_migrations(conn)
    _insert_snapshot(conn, NOW_UTC - timedelta(hours=2))

    def _raise(*args, **kwargs):
        raise ConnectionError("CBOE indisponible (test)")

    monkeypatch.setattr("nqcockpit.data.cboe.fetch_cboe_options_chain", _raise)
    monkeypatch.setattr("nqcockpit.data.fetcher.DataFetcher.fetch_yahoo_bars", _raise)

    profile = build_day_profile(conn=conn, config=load_config(), now_utc=NOW_UTC)

    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    conn.close()

    gamma = profile.component_statuses["gamma"]
    assert count == 1  # aucune nouvelle ligne, aucune exception levée
    assert gamma.status == "STALE"
    assert gamma.reason_key == "reason.snapshot_stale"
    assert gamma.age_minutes is not None and gamma.age_minutes > 30.0
    assert profile.status == "DEGRADED"


def test_scheduler_starts_once_per_process(monkeypatch):
    """Le planificateur ne démarre qu'une seule fois par process (reruns Streamlit)."""
    import nqcockpit.levels.scheduler as scheduler_mod

    class _FakeScheduler:
        starts = 0

        def start(self) -> None:
            _FakeScheduler.starts += 1

    monkeypatch.setattr(scheduler_mod, "_is_test_session", lambda: False)
    monkeypatch.setattr(scheduler_mod, "_scheduler_singleton", None)

    assert scheduler_mod.start_levels_scheduler_once(_FakeScheduler) is True
    assert scheduler_mod.start_levels_scheduler_once(_FakeScheduler) is False
    assert _FakeScheduler.starts == 1


def test_scheduler_never_starts_during_tests(monkeypatch):
    """Sous pytest, le planificateur n'est jamais instancié."""
    import nqcockpit.levels.scheduler as scheduler_mod

    def _factory():
        raise AssertionError("Le planificateur ne doit pas démarrer en tests")

    monkeypatch.setattr(scheduler_mod, "_scheduler_singleton", None)
    assert scheduler_mod.start_levels_scheduler_once(_factory) is False


def test_none_values_do_not_crash_cockpit_render():
    """Spot/EM/niveaux à None : la page Cockpit s'affiche sans exception."""
    from streamlit.testing.v1 import AppTest

    fake_profile = DayProfile(
        as_of_utc=NOW_UTC.isoformat(),
        as_of_algiers="2026-09-30 15:30 (Alger)",
        as_of_et="2026-09-30 10:30 ET",
        target_date="2026-09-30",
        spot_nq=None,
        event_risk_level="GREEN",
        event_risk_reason="Aucun événement critique",
        next_tier1_event=None,
        next_tier1_countdown=None,
        volatility_regime="VOLATILITÉ NORMALE",
        vix_level=None,
        vxn_level=None,
        overnight_range_pts=None,
        gamma_regime="INDISPONIBLE",
        net_gex_dollars=None,
        distance_to_flip_pts=None,
        base_expected_move_pts=None,
        em_consumption_pct=None,
        probable_day_type="range",
        day_type_reasons=["Données indisponibles"],
        key_levels=[],
        scenarios=[],
        component_statuses={
            "gamma": ComponentHealth(
                name="Niveaux Gamma",
                status="DÉGRADÉ: aucun snapshot disponible",
                detail="Données indisponibles (Data unavailable)",
            ),
        },
        no_trade=NoTradeAssessment(
            is_trading_allowed=True,
            overall_status="AUTORISÉ (sous conditions)",
            active_flags_count=0,
        ),
    )

    page = Path(__file__).parent.parent / "src" / "nqcockpit" / "ui" / "cockpit_page.py"
    with (
        patch("nqcockpit.profile.engine.build_day_profile", return_value=fake_profile),
        patch(
            "nqcockpit.macro.news_radar.fetch_macro_news_radar",
            side_effect=RuntimeError("offline (test)"),
        ),
        patch(
            "nqcockpit.macro.news_radar.fetch_live_news_wire",
            side_effect=RuntimeError("offline (test)"),
        ),
    ):
        at = AppTest.from_file(str(page), default_timeout=30)
        at.run()
        assert not at.exception, f"Streamlit a levé une exception : {at.exception}"
