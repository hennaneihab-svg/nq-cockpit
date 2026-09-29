"""Tests unitaires pour P04-fix5 :
1. Âge réel du spot NQ et détection de péremption en séance CME.
2. Rechargement prouvé CBOE, statut basé sur timestamp interne et exclusion bid=0/ask=0.
3. Murs utiles dans la fenêtre ±10% et détection des murs globaux hors fenêtre.
4. Expected Move avec décomposition explicite des spots (NDX formule vs NQ centrage).
"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from nqcockpit.data.cboe import (
    CboeChainSnapshot,
    extract_cboe_chain_age_stats,
    fetch_cboe_options_chain,
    parse_cboe_payload,
)
from nqcockpit.data.models import Bar, DataStatus
from nqcockpit.levels.engine import LevelsEngine, enrich_expected_move_nq
from nqcockpit.levels.models import ExpectedMoveInfo

ET = ZoneInfo("America/New_York")


def test_spot_nq_real_age_and_cme_staleness():
    """Vérifie le calcul de l'âge réel du spot NQ et la détection de péremption pendant CME."""
    engine = LevelsEngine()

    now_utc = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)  # Mardi 10:00 ET (CME ouvert)

    # 1. Barre fraîche (5 min)
    fresh_bar = Bar(
        timestamp_utc=datetime(2026, 9, 29, 13, 55, tzinfo=timezone.utc),
        open=30500.0,
        high=30520.0,
        low=30490.0,
        close=30510.25,
        volume=100.0,
    )

    sample_opts = pd.DataFrame(
        [
            {
                "contract": "NDX261016C28000000",
                "expiry": date(2026, 10, 16),
                "type": "C",
                "strike": 28000.0,
                "bid": 10.0,
                "ask": 12.0,
                "iv": 0.20,
                "open_interest": 100.0,
                "gamma": 0.0001,
            }
        ]
    )

    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=28000.0,
        options_df=sample_opts,
        latest_quote_time_utc=now_utc,
        fetched_at_utc=now_utc,
        age_minutes=5.0,
        status=DataStatus.OK,
    )

    snap_fresh = engine.compute_snapshot(
        chain=chain,
        nq_bars=[fresh_bar],
        ndx_bars=[],
        now_utc=now_utc,
    )

    assert snap_fresh.spot_nq == 30510.25
    assert snap_fresh.spot_nq_age_minutes == 5.0
    assert not snap_fresh.spot_nq_is_stale
    assert "âge réel 5.0 min" in (snap_fresh.spot_nq_delay_note or "")

    # 2. Barre périmée en séance CME (45 min > seuil 20 min)
    stale_bar = Bar(
        timestamp_utc=datetime(2026, 9, 29, 13, 15, tzinfo=timezone.utc),
        open=30500.0,
        high=30520.0,
        low=30490.0,
        close=30500.0,
        volume=100.0,
    )

    snap_stale = engine.compute_snapshot(
        chain=chain,
        nq_bars=[stale_bar],
        ndx_bars=[],
        now_utc=now_utc,
    )

    assert snap_stale.spot_nq_age_minutes == 45.0
    assert snap_stale.spot_nq_is_stale
    assert "SPOT NQ PÉRIMÉ" in (snap_stale.spot_nq_delay_note or "")
    assert snap_stale.status == DataStatus.DEGRADED


def test_cboe_zero_quote_exclusion_and_stats():
    """Vérifie que les options avec bid=0 ou ask=0 sont exclues des stats de trading."""
    now_utc = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)
    spot = 28000.0

    raw_options = [
        # Option active avec trade il y a 10 min (horodatage UTC)
        {
            "strike": 28000.0,
            "bid": 25.0,
            "ask": 27.0,
            "last_trade_time": "2026-09-29 13:50:00Z",
        },
        # Option sans cotation (bid=0) avec trade ancien (1000 min) -> doit être exclue !
        {
            "strike": 28100.0,
            "bid": 0.0,
            "ask": 5.0,
            "last_trade_time": "2026-09-28 21:20:00Z",
        },
        # Option sans ask (ask=0) -> doit être exclue !
        {
            "strike": 27900.0,
            "bid": 10.0,
            "ask": 0.0,
            "last_trade_time": "2026-09-28 21:20:00Z",
        },
    ]

    age_min, latest_dt, stats = extract_cboe_chain_age_stats(raw_options, spot, now_utc)

    assert age_min == 10.0
    assert stats["count"] == 1
    assert stats["excluded_zero_quotes"] == 2


def test_cboe_chain_internal_timestamp_determines_status():
    """Vérifie que le statut CBOE reflète l'horodatage interne de la chaîne."""
    fetched_at = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)  # En séance US (10:00 ET)

    raw_payload = {
        "timestamp": "2026-09-29 13:58:00",  # Chaîne très fraîche (2 min)
        "data": {
            "current_price": 28000.0,
            "options": [
                {
                    "option": "NDX260930C28000000",
                    "strike": 28000.0,
                    "bid": 10.0,
                    "ask": 12.0,
                    "last_trade_time": "2026-09-28 20:00:00",  # Dernier trade hier (illiquide)
                }
            ],
        },
    }

    snap = parse_cboe_payload(raw_payload, fetched_at)

    # L'âge de la chaîne est basé sur raw['timestamp'] (2 min)
    # et non sur le trade de l'option (hier)
    assert snap.age_minutes == 2.0
    assert snap.status == DataStatus.OK
    assert snap.chain_internal_timestamp_utc == datetime(
        2026, 9, 29, 13, 58, tzinfo=timezone.utc
    )


def test_cboe_fetch_force_reload():
    """Vérifie que fetch_cboe_options_chain capture les métadonnées de rechargement."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "timestamp": "2026-09-29 13:58:00",
        "data": {
            "current_price": 28000.0,
            "options": [],
        },
    }

    with patch("nqcockpit.data.cboe._SESSION.get", return_value=mock_resp):
        snap = fetch_cboe_options_chain(force_reload=True)
        assert snap.chain_reloaded
        assert snap.http_status == 200
        assert snap.request_duration_ms is not None
        assert snap.request_duration_ms >= 0.0


def test_useful_walls_and_global_wall_outside_window():
    """Vérifie la restriction des walls à la fenêtre ±10 %
    et le rapport du mur global hors fenêtre.
    """
    engine = LevelsEngine()
    now_utc = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)
    spot_ndx = 20000.0
    basis = 2500.0  # NQ = 22500

    # Création d'options avec :
    # 1. Call Wall dans la fenêtre (21 000, soit +5%) avec GEX = 100
    # 2. Call Wall géant hors fenêtre (25 000, soit +25%) avec GEX = 500
    # 3. Put Wall dans la fenêtre (19 000, soit -5%) avec GEX = -100
    # 4. Put Wall géant hors fenêtre (16 000, soit -20%) avec GEX = -600
    options_data = [
        {
            "contract": "NDX261016C21000000",
            "expiry": date(2026, 10, 16),
            "type": "C",
            "strike": 21000.0,
            "bid": 10.0,
            "ask": 11.0,
            "iv": 0.20,
            "open_interest": 1000.0,
            "gamma": 0.0001,
        },
        {
            "contract": "NDX261016C25000000",
            "expiry": date(2026, 10, 16),
            "type": "C",
            "strike": 25000.0,
            "bid": 10.0,
            "ask": 11.0,
            "iv": 0.20,
            "open_interest": 5000.0,
            "gamma": 0.0001,
        },
        {
            "contract": "NDX261016P19000000",
            "expiry": date(2026, 10, 16),
            "type": "P",
            "strike": 19000.0,
            "bid": 10.0,
            "ask": 11.0,
            "iv": 0.20,
            "open_interest": 1000.0,
            "gamma": 0.0001,
        },
        {
            "contract": "NDX261016P16000000",
            "expiry": date(2026, 10, 16),
            "type": "P",
            "strike": 16000.0,
            "bid": 10.0,
            "ask": 11.0,
            "iv": 0.20,
            "open_interest": 6000.0,
            "gamma": 0.0001,
        },
    ]

    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=spot_ndx,
        options_df=pd.DataFrame(options_data),
        latest_quote_time_utc=now_utc,
        fetched_at_utc=now_utc,
        age_minutes=2.0,
        status=DataStatus.OK,
    )

    nq_bar = Bar(
        timestamp_utc=now_utc,
        open=22500.0,
        high=22500.0,
        low=22500.0,
        close=22500.0,
        volume=10.0,
    )
    ndx_bar = Bar(
        timestamp_utc=now_utc,
        open=20000.0,
        high=20000.0,
        low=20000.0,
        close=20000.0,
        volume=10.0,
    )

    snap = engine.compute_snapshot(
        chain=chain,
        nq_bars=[nq_bar],
        ndx_bars=[ndx_bar],
        now_utc=now_utc,
    )

    # Murs utiles (dans la fenêtre ±10 %)
    assert snap.call_wall_useful_ndx == 21000.0
    assert snap.call_wall_useful_nq == 21000.0 + basis
    assert snap.call_wall_useful_dist_pct == 5.0
    assert snap.put_wall_useful_ndx == 19000.0
    assert snap.put_wall_useful_nq == 19000.0 + basis
    assert snap.put_wall_useful_dist_pct == -5.0

    # Murs globaux (hors fenêtre)
    assert snap.call_wall_global_ndx == 25000.0
    assert snap.call_wall_is_outside_window
    assert snap.put_wall_global_ndx == 16000.0
    assert snap.put_wall_is_outside_window


def test_expected_move_explicit_spots():
    """Vérifie la décomposition claire des spots dans l'Expected Move."""
    em = ExpectedMoveInfo(
        formula_move=300.0,
        straddle_move=290.0,
        iv_atm=0.20,
        days_to_expiry=1.0,
        lower_bound_ndx=27700.0,
        upper_bound_ndx=28300.0,
        lower_bound_nq=0.0,
        upper_bound_nq=0.0,
        expiry=date(2026, 9, 30),
    )

    spot_ndx = 28000.0
    spot_nq_obs = 30450.0
    basis = 2400.0  # NDX converti = 30 400.0

    res = enrich_expected_move_nq(
        em=em,
        basis=basis,
        spot_nq=spot_nq_obs,
        spot_ndx=spot_ndx,
        cboe_age_minutes=5.0,
    )

    assert res.spot_ndx_used == 28000.0
    assert res.spot_nq_observed == 30450.0
    assert res.spot_nq_converted == 30400.0
    assert res.spread_nq_vs_converted == 50.0  # 30450 - 30400
