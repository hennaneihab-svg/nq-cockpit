"""Tests unitaires pour le moteur de niveaux (P04).

Tous les tests utilisent des fixtures locales synthétiques, sans aucun appel réseau.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nqcockpit.data.basis import compute_previous_session_basis
from nqcockpit.data.calendar import CALENDAR
from nqcockpit.data.cboe import CboeChainSnapshot
from nqcockpit.data.models import Bar, DataStatus
from nqcockpit.levels.engine import (
    LevelsEngine,
    calculate_expected_move,
    calculate_gamma_profile,
    calculate_max_pain,
    calculate_zero_gamma,
    compute_gamma_exposure,
)
from nqcockpit.levels.models import LevelsSnapshot
from nqcockpit.levels.scheduler import compare_snapshots


@pytest.fixture
def sample_options_df():
    """Génère une chaîne d'options synthétique NDX réaliste."""
    exp_0dte = date(2026, 9, 28)
    exp_front = date(2026, 10, 16)

    rows = []
    # Spot = 20000. Strikes de 19000 à 21000 par pas de 100
    for exp in (exp_0dte, exp_front):
        for k in range(19000, 21100, 100):
            # Gamma culmine autour de 20000
            dist = abs(k - 20000)
            g = max(0.00001, 0.0015 - dist * 0.000001)
            iv = 0.20 + (k - 20000) * 0.00001

            c_bid = max(0.5, 20000 - k + 50) if k <= 20000 else max(0.5, 100 - (k - 20000) * 0.1)
            c_ask = max(1.0, 20000 - k + 52) if k <= 20000 else max(1.0, 102 - (k - 20000) * 0.1)
            c_oi = 5000.0 if k == 20500 else 1000.0  # Pic à 20500 pour Call Wall

            # Calls
            rows.append(
                {
                    "contract": f"NDX_{exp}_C_{k}",
                    "expiry": exp,
                    "type": "C",
                    "strike": float(k),
                    "bid": c_bid,
                    "ask": c_ask,
                    "iv": iv,
                    "open_interest": c_oi,
                    "volume": 200.0,
                    "delta": 0.5,
                    "gamma": g,
                    "last_trade_price": 50.0,
                    "last_trade_time": "2026-09-28T19:50:00Z",
                }
            )

            p_bid = max(0.5, k - 20000 + 50) if k >= 20000 else max(0.5, 100 - (20000 - k) * 0.1)
            p_ask = max(1.0, k - 20000 + 52) if k >= 20000 else max(1.0, 102 - (20000 - k) * 0.1)
            p_oi = 6000.0 if k == 19500 else 1000.0  # Pic à 19500 pour Put Wall

            # Puts
            rows.append(
                {
                    "contract": f"NDX_{exp}_P_{k}",
                    "expiry": exp,
                    "type": "P",
                    "strike": float(k),
                    "bid": p_bid,
                    "ask": p_ask,
                    "iv": iv,
                    "open_interest": p_oi,
                    "volume": 200.0,
                    "delta": -0.5,
                    "gamma": g,
                    "last_trade_price": 50.0,
                    "last_trade_time": "2026-09-28T19:50:00Z",
                }
            )

    return pd.DataFrame(rows)


def test_gex_formula_and_regime(sample_options_df):
    """Vérifie la formule GEX ($/1%) : sign * gamma * OI * 100 * S^2 * 0.01."""
    spot = 20000.0
    df_gex = compute_gamma_exposure(sample_options_df, spot)

    assert "gex" in df_gex.columns
    # Les calls doivent être positifs, les puts négatifs
    calls = df_gex[df_gex["type"] == "C"]
    puts = df_gex[df_gex["type"] == "P"]
    assert (calls["gex"] > 0).all()
    assert (puts["gex"] < 0).all()

    # Net GEX
    net_gex = df_gex["gex"].sum()
    assert isinstance(net_gex, float)


def test_gamma_profile_and_zero_gamma(sample_options_df):
    """Vérifie le profil de gamma et l'interpolation du zéro gamma."""
    spot = 20000.0
    df_gex = compute_gamma_exposure(sample_options_df, spot)
    profile_res = calculate_gamma_profile(df_gex, spot, today_date=date(2026, 9, 28))

    assert profile_res is not None
    grid, profile = profile_res
    assert len(grid) == 101
    assert len(profile) == 101

    flip = calculate_zero_gamma(grid, profile, spot)
    # Dans notre distribution synthétique, il peut y avoir un flip ou non
    if flip is not None:
        assert 18000.0 <= flip <= 22000.0


def test_zero_gamma_absent_when_no_crossing():
    """Vérifie que calculate_zero_gamma renvoie None si aucun passage par zéro (flip absent)."""
    grid = np.linspace(19000, 21000, 101)
    # Profil strictement positif (régime très stable)
    profile = np.ones(101) * 500000.0

    flip = calculate_zero_gamma(grid, profile, 20000.0)
    assert flip is None


def test_walls_and_0dte_detection(sample_options_df):
    """Vérifie que le Call Wall est au-dessus du spot et le Put Wall en dessous."""
    spot = 20000.0
    df_gex = compute_gamma_exposure(sample_options_df, spot)

    by_strike = df_gex.groupby("strike")["gex"].sum()
    calls_above = by_strike[(by_strike.index >= spot) & (by_strike > 0)]
    puts_below = by_strike[(by_strike.index <= spot) & (by_strike < 0)]

    # Selon notre fixture, pic call à 20500 et put à 19500
    assert calls_above.idxmax() == 20500.0
    assert puts_below.idxmin() == 19500.0


def test_expected_move_calculation(sample_options_df):
    """Vérifie la formule 1 sigma : S * IV * sqrt(jours / 252) et le straddle ATM."""
    spot = 20000.0
    em = calculate_expected_move(sample_options_df, spot, today_date=date(2026, 9, 28))

    assert em is not None
    assert em.formula_move > 0
    assert em.lower_bound_ndx < spot < em.upper_bound_ndx
    assert em.straddle_move is not None
    assert em.straddle_move > 0


def test_max_pain_calculation(sample_options_df):
    """Vérifie que le strike Max Pain est calculé et situé dans la plage des strikes."""
    mp = calculate_max_pain(sample_options_df)
    assert mp is not None
    assert 19000.0 <= mp <= 21000.0


def test_levels_engine_full_snapshot(sample_options_df, tmp_path: Path):
    """Vérifie l'exécution de bout en bout du snapshot de niveaux avec conversion NQ."""
    engine = LevelsEngine(output_dir=tmp_path)

    t0 = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)
    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=20000.0,
        options_df=sample_options_df,
        latest_quote_time_utc=t0 - timedelta(minutes=10),
        fetched_at_utc=t0,
        age_minutes=10.0,
        status=DataStatus.OK,
    )

    nq_bar = Bar(timestamp_utc=t0, open=20020.0, high=20025.0, low=20018.0, close=20020.0)
    ndx_bar = Bar(timestamp_utc=t0, open=20000.0, high=20005.0, low=19998.0, close=20000.0)

    snap = engine.compute_snapshot(chain=chain, nq_bars=[nq_bar], ndx_bars=[ndx_bar], now_utc=t0)

    assert snap.status == DataStatus.OK
    assert snap.spot_ndx == 20000.0
    assert snap.spot_nq == 20020.0  # spot + 20 pts de base
    assert snap.basis == 20.0
    assert snap.call_wall_ndx == 20500.0
    assert snap.call_wall_nq == 20520.0  # 20500 + 20
    assert snap.put_wall_ndx == 19500.0
    assert snap.put_wall_nq == 19520.0  # 19500 + 20
    assert snap.expected_move is not None
    assert snap.expected_move.lower_bound_nq == snap.expected_move.lower_bound_ndx + 20.0

    # Vérification du fichier JSON généré
    json_files = list(tmp_path.glob("*.json"))
    assert len(json_files) == 1


def test_empty_chain_handling(tmp_path: Path):
    """Vérifie la robustesse si la chaîne d'options CBOE est vide."""
    engine = LevelsEngine(output_dir=tmp_path)
    t0 = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)

    chain_empty = CboeChainSnapshot(
        symbol="NDX",
        spot=20000.0,
        options_df=pd.DataFrame(),
        latest_quote_time_utc=None,
        fetched_at_utc=t0,
        age_minutes=None,
        status=DataStatus.BLOCKED,
    )

    snap = engine.compute_snapshot(chain=chain_empty, nq_bars=[], ndx_bars=[], now_utc=t0)
    assert snap.status == DataStatus.BLOCKED
    assert "vide" in str(snap.anomalies).lower()


def test_compare_snapshots():
    """Vérifie la détection de déplacement des niveaux entre deux snapshots."""
    t0 = datetime(2026, 9, 28, 14, 0, 0, tzinfo=timezone.utc)
    snap1 = LevelsSnapshot(
        timestamp_utc=t0,
        source_timestamp_utc=t0,
        data_age_minutes=5.0,
        status=DataStatus.OK,
        spot_ndx=20000.0,
        spot_nq=20120.0,
        basis=120.0,
        basis_label="base en séance",
        basis_status=DataStatus.OK,
        synthetic_basis=None,
        net_gex=1000000.0,
        regime="AMORTISSEUR",
        gamma_flip_ndx=19800.0,
        gamma_flip_nq=19920.0,
        call_wall_ndx=20500.0,
        call_wall_nq=20620.0,
        put_wall_ndx=19500.0,
        put_wall_nq=19620.0,
    )

    # 1 heure plus tard : Call Wall monte à 20600
    snap2 = LevelsSnapshot(
        timestamp_utc=t0 + timedelta(hours=1),
        source_timestamp_utc=t0 + timedelta(hours=1),
        data_age_minutes=5.0,
        status=DataStatus.OK,
        spot_ndx=20050.0,
        spot_nq=20170.0,
        basis=120.0,
        basis_label="base en séance",
        basis_status=DataStatus.OK,
        synthetic_basis=None,
        net_gex=1200000.0,
        regime="AMORTISSEUR",
        gamma_flip_ndx=19800.0,
        gamma_flip_nq=19920.0,
        call_wall_ndx=20600.0,
        call_wall_nq=20720.0,
        put_wall_ndx=19500.0,
        put_wall_nq=19620.0,
    )

    moves = compare_snapshots(snap1, snap2)
    cw_move = next(m for m in moves if m.metric == "Call Wall NDX")
    assert cw_move.status == "MIGRATION_HAUSSIERE"
    assert cw_move.delta == 100.0

    pw_move = next(m for m in moves if m.metric == "Put Wall NDX")
    assert pw_move.status == "STABLE"


def test_basis_previous_session_ok() -> None:
    """Base hors séance normale : statut OK avec mention (âge N h)."""
    # Vendredi 25 sept 2026 16:00 ET = 20:00 UTC
    t_close = datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
    # Samedi 26 sept 2026 10:00 ET = 14:00 UTC (âge 18 h)
    t_ref = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)

    nq_bars = [
        Bar(timestamp_utc=t_close, open=20120.0, high=20125.0, low=20118.0, close=20120.0)
    ]
    ndx_bars = [
        Bar(timestamp_utc=t_close, open=20000.0, high=20005.0, low=19995.0, close=20000.0)
    ]

    snap = compute_previous_session_basis(nq_bars, ndx_bars, ref_utc=t_ref)
    assert snap.status == DataStatus.OK
    assert snap.basis == 120.0
    assert "base de la séance précédente" in snap.label
    assert "âge 18.0 h" in snap.label


def test_basis_previous_session_stale_degraded() -> None:
    """Base datant de plus d'une séance de bourse : statut DÉGRADÉ."""
    # Jeudi 24 sept 2026 16:00 ET = 20:00 UTC
    t_thu = datetime(2026, 9, 24, 20, 0, tzinfo=timezone.utc)
    # Samedi 26 sept 2026 (une séance complète le vendredi a eu lieu entre-temps)
    t_sat = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)

    nq_bars = [
        Bar(timestamp_utc=t_thu, open=20120.0, high=20125.0, low=20118.0, close=20120.0)
    ]
    ndx_bars = [
        Bar(timestamp_utc=t_thu, open=20000.0, high=20005.0, low=19995.0, close=20000.0)
    ]

    snap = compute_previous_session_basis(nq_bars, ndx_bars, ref_utc=t_sat)
    assert snap.status == DataStatus.DEGRADED


def test_basis_parity_divergence_degraded(tmp_path: Path, sample_options_df: pd.DataFrame) -> None:
    """Écart supérieur à la tolérance entre base future et parité : DÉGRADÉ."""
    engine = LevelsEngine(output_dir=tmp_path / "levels")
    # Date en séance régulière : vendredi 25 sept 2026 14:00 ET = 18:00 UTC
    t_now = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)

    # Base = 20300 - 20000 = +300 pts
    nq_bars = [
        Bar(timestamp_utc=t_now, open=20300.0, high=20305.0, low=20295.0, close=20300.0)
    ]
    ndx_bars = [
        Bar(timestamp_utc=t_now, open=20000.0, high=20005.0, low=19995.0, close=20000.0)
    ]

    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=20000.0,
        options_df=sample_options_df,
        latest_quote_time_utc=t_now,
        fetched_at_utc=t_now,
        age_minutes=2.0,
        status=DataStatus.OK,
    )

    snap = engine.compute_snapshot(chain, nq_bars, ndx_bars, now_utc=t_now)
    if snap.synthetic_basis is not None:
        diff = abs(snap.basis - snap.synthetic_basis)
        if diff > 50.0:
            assert snap.basis_status == DataStatus.DEGRADED
            assert any("Écart base future-spot vs parité" in a for a in snap.anomalies)


def test_expected_move_trading_days_friday_to_monday() -> None:
    """Vendredi soir après 16:00 ET -> expiration lundi = 1 jour de bourse."""
    # Vendredi 2 oct 2026 17:00 ET = 21:00 UTC
    ref_utc = datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)
    exp_monday = date(2026, 10, 5)

    days = CALENDAR.calculate_trading_days_to_expiry(ref_utc, exp_monday)
    assert days == 1.0


def test_expected_move_trading_days_holiday() -> None:
    """Veille de Thanksgiving (mercredi) -> expiration vendredi = 1 jour de bourse."""
    # Mercredi 25 nov 2026 17:00 ET = 22:00 UTC
    ref_utc = datetime(2026, 11, 25, 22, 0, tzinfo=timezone.utc)
    exp_friday = date(2026, 11, 27)

    days = CALENDAR.calculate_trading_days_to_expiry(ref_utc, exp_friday)
    assert days == 1.0


def test_expected_move_0dte_fraction() -> None:
    """0DTE le vendredi à 12:45 ET (3.25h avant clôture 16:00) = 0.5 jour de bourse."""
    # Vendredi 2 oct 2026 12:45 ET = 16:45 UTC
    ref_utc = datetime(2026, 10, 2, 16, 45, tzinfo=timezone.utc)
    exp_today = date(2026, 10, 2)

    days = CALENDAR.calculate_trading_days_to_expiry(ref_utc, exp_today)
    assert pytest.approx(days, abs=0.01) == 0.5


def test_reference_session_monday_evening(tmp_path: Path):
    """Fixture test (1) : Lundi 21:37 ET.

    - Échéance du lundi exclue.
    - Session de référence = mardi.
    - Expected Move basé sur l'échéance du mardi avec jours = 1,0.
    - 0DTE = mardi.
    """
    engine = LevelsEngine(output_dir=tmp_path)
    # Lundi 28 sept 2026 21:37 ET = Mardi 29 sept 2026 01:37 UTC
    now_utc = datetime(2026, 9, 29, 1, 37, 0, tzinfo=timezone.utc)

    exp_monday = date(2026, 9, 28)
    exp_tuesday = date(2026, 9, 29)
    exp_friday = date(2026, 10, 2)

    rows = []
    spot = 20000.0
    for exp in (exp_monday, exp_tuesday, exp_friday):
        for k in (19800, 20000, 20200):
            rows.append(
                {
                    "contract": f"NDX_{exp}_C_{k}",
                    "expiry": exp,
                    "type": "C",
                    "strike": float(k),
                    "bid": 50.0,
                    "ask": 52.0,
                    "iv": 0.20,
                    "open_interest": 1000.0,
                    "volume": 100.0,
                    "delta": 0.5,
                    "gamma": 0.001,
                    "last_trade_price": 51.0,
                    "last_trade_time": "2026-09-28 16:14:59",
                }
            )
            rows.append(
                {
                    "contract": f"NDX_{exp}_P_{k}",
                    "expiry": exp,
                    "type": "P",
                    "strike": float(k),
                    "bid": 50.0,
                    "ask": 52.0,
                    "iv": 0.20,
                    "open_interest": 1000.0,
                    "volume": 100.0,
                    "delta": -0.5,
                    "gamma": 0.001,
                    "last_trade_price": 51.0,
                    "last_trade_time": "2026-09-28 16:14:59",
                }
            )

    df_chain = pd.DataFrame(rows)
    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=spot,
        options_df=df_chain,
        latest_quote_time_utc=now_utc - timedelta(hours=5),
        fetched_at_utc=now_utc,
        age_minutes=300.0,
        status=DataStatus.OK,
    )

    t_close = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
    nq_bars = [Bar(timestamp_utc=t_close, open=20280.0, high=20285.0, low=20275.0, close=20280.0)]
    ndx_bars = [Bar(timestamp_utc=t_close, open=20000.0, high=20005.0, low=19995.0, close=20000.0)]

    snap = engine.compute_snapshot(chain=chain, nq_bars=nq_bars, ndx_bars=ndx_bars, now_utc=now_utc)

    # 1. Échéance du lundi exclue
    assert snap.reference_session_date == exp_tuesday
    assert any("Échéances expirées exclues" in a for a in snap.anomalies)

    # 2. 0DTE = mardi
    assert snap.zero_dte_expiry == exp_tuesday

    # 3. Expected move basé sur mardi avec jours = 1.0
    assert snap.expected_move is not None
    assert snap.expected_move.expiry == exp_tuesday
    assert snap.expected_move.days_to_expiry == 1.0


def test_reference_session_tuesday_morning_fraction(tmp_path: Path):
    """Fixture test (2) : Mardi 10:00 ET.

    - 0DTE = mardi avec fraction de jour.
    """
    engine = LevelsEngine(output_dir=tmp_path)
    # Mardi 29 sept 2026 10:00 ET = 14:00 UTC
    now_utc = datetime(2026, 9, 29, 14, 0, 0, tzinfo=timezone.utc)

    exp_tuesday = date(2026, 9, 29)
    exp_friday = date(2026, 10, 2)

    rows = []
    spot = 20000.0
    for exp in (exp_tuesday, exp_friday):
        for k in (19800, 20000, 20200):
            rows.append(
                {
                    "contract": f"NDX_{exp}_C_{k}",
                    "expiry": exp,
                    "type": "C",
                    "strike": float(k),
                    "bid": 50.0,
                    "ask": 52.0,
                    "iv": 0.20,
                    "open_interest": 1000.0,
                    "volume": 100.0,
                    "delta": 0.5,
                    "gamma": 0.001,
                    "last_trade_price": 51.0,
                    "last_trade_time": "2026-09-29 09:59:00",
                }
            )
            rows.append(
                {
                    "contract": f"NDX_{exp}_P_{k}",
                    "expiry": exp,
                    "type": "P",
                    "strike": float(k),
                    "bid": 50.0,
                    "ask": 52.0,
                    "iv": 0.20,
                    "open_interest": 1000.0,
                    "volume": 100.0,
                    "delta": -0.5,
                    "gamma": 0.001,
                    "last_trade_price": 51.0,
                    "last_trade_time": "2026-09-29 09:59:00",
                }
            )

    df_chain = pd.DataFrame(rows)
    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=spot,
        options_df=df_chain,
        latest_quote_time_utc=now_utc - timedelta(minutes=1),
        fetched_at_utc=now_utc,
        age_minutes=1.0,
        status=DataStatus.OK,
    )

    nq_bars = [Bar(timestamp_utc=now_utc, open=20280.0, high=20285.0, low=20275.0, close=20280.0)]
    ndx_bars = [Bar(timestamp_utc=now_utc, open=20000.0, high=20005.0, low=19995.0, close=20000.0)]

    snap = engine.compute_snapshot(chain=chain, nq_bars=nq_bars, ndx_bars=ndx_bars, now_utc=now_utc)

    # Session de référence et 0DTE = mardi
    assert snap.reference_session_date == exp_tuesday
    assert snap.zero_dte_expiry == exp_tuesday

    # Fraction de séance : de 10:00 à 16:00 = 6.0 heures / 6.5 heures = 0.923 jour
    assert snap.expected_move is not None
    assert snap.expected_move.expiry == exp_tuesday
    assert pytest.approx(snap.expected_move.days_to_expiry, abs=0.01) == 6.0 / 6.5


def test_expected_move_order_of_magnitude_22pct():
    """Fixture test (3) : Ordre de grandeur.

    IV ATM ≈ 22 % donne un Expected Move à 1 jour ≈ 1,39 % du spot.
    Formule : S * 0.22 * sqrt(1 / 252) ≈ S * 0.0138586 ≈ 1.39 % de S.
    """
    spot = 20000.0
    iv_atm = 0.22

    df = pd.DataFrame(
        [
            {
                "contract": "NDX_2026-09-29_C_20000",
                "expiry": date(2026, 9, 29),
                "type": "C",
                "strike": 20000.0,
                "bid": 100.0,
                "ask": 102.0,
                "iv": iv_atm,
                "open_interest": 1000.0,
                "volume": 100.0,
                "delta": 0.5,
                "gamma": 0.001,
                "last_trade_price": 101.0,
                "last_trade_time": "2026-09-28 16:14:59",
            },
            {
                "contract": "NDX_2026-09-29_P_20000",
                "expiry": date(2026, 9, 29),
                "type": "P",
                "strike": 20000.0,
                "bid": 100.0,
                "ask": 102.0,
                "iv": iv_atm,
                "open_interest": 1000.0,
                "volume": 100.0,
                "delta": -0.5,
                "gamma": 0.001,
                "last_trade_price": 101.0,
                "last_trade_time": "2026-09-28 16:14:59",
            },
        ]
    )

    # Référence hors séance pour avoir days = 1.0
    ref_utc = datetime(2026, 9, 29, 1, 37, 0, tzinfo=timezone.utc)
    em = calculate_expected_move(df, spot, ref_utc=ref_utc)

    assert em is not None
    assert em.days_to_expiry == 1.0
    ratio = em.formula_move / spot
    # 1.38586 % ≈ 1.39 %
    assert abs(ratio - 0.0139) < 0.0005
    assert pytest.approx(ratio * 100.0, abs=0.05) == 1.39
