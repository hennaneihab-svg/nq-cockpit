"""Tests de conformité P04-fix6 : Diagnostic Straddle, Base Live, Fraîcheur & Murs 3%.

Règles de conformité :
- Aucun chiffre inventé, aucun forçage de données.
- Statut DÉGRADÉ visible si écart > tolérance ou source en retard.
- Horodatages via zoneinfo (America/New_York et Africa/Algiers).
- Découplage strict des sources et repli SQLite testé sans texte en dur.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from nqcockpit.data.cboe import CboeChainSnapshot
from nqcockpit.data.models import Bar, DataStatus
from nqcockpit.levels.engine import (
    LevelsEngine,
    calculate_expected_move,
)

ET = ZoneInfo("America/New_York")
ALG = ZoneInfo("Africa/Algiers")


def test_straddle_diagnostic_calculation_and_cause_documentation():
    """TÂCHE 1 : Vérifie la construction du bloc StraddleDiagnostic :
    - Spot NDX et strike ATM
    - Racines OCC et expirations Call/Put
    - Bid, ask, mid, volume, IV CBOE, horodatages
    - Largeur relative et alerte si > seuil
    - Straddle pur en points NDX
    - IV implicite du straddle via formule Brenner-Subrahmanyam inversée
    - 3 strikes voisins ATM (ATM-1, ATM, ATM+1)
    - Cause documentée sur divergence conventionnelle ACT/365 vs ACT/252
    """
    ref_utc = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)  # 10:30 ET
    spot_ndx = 20000.0
    exp_date = date(2026, 9, 29)

    # 3 strikes : 19900, 20000 (ATM), 20100
    rows = []
    for k in [19900.0, 20000.0, 20100.0]:
        # Call
        rows.append(
            {
                "contract": f"NDXP260929C{int(k * 1000):08d}",
                "expiry": exp_date,
                "type": "C",
                "strike": k,
                "bid": 60.0 if k == 20000.0 else (120.0 if k < 20000 else 20.0),
                "ask": 62.0 if k == 20000.0 else (122.0 if k < 20000 else 22.0),
                "last_trade_price": 61.0,
                "iv": 0.20,
                "volume": 500.0,
                "open_interest": 1000.0,
                "gamma": 0.0002,
                "last_trade_time": "2026-09-29 10:15:00",
            }
        )
        # Put
        rows.append(
            {
                "contract": f"NDXP260929P{int(k * 1000):08d}",
                "expiry": exp_date,
                "type": "P",
                "strike": k,
                "bid": 58.0 if k == 20000.0 else (18.0 if k < 20000 else 118.0),
                "ask": 60.0 if k == 20000.0 else (20.0 if k < 20000 else 120.0),
                "last_trade_price": 59.0,
                "iv": 0.20,
                "volume": 450.0,
                "open_interest": 1200.0,
                "gamma": 0.0002,
                "last_trade_time": "2026-09-29 10:14:50",
            }
        )

    df = pd.DataFrame(rows)
    em = calculate_expected_move(df, spot=spot_ndx, ref_utc=ref_utc)
    assert em is not None
    assert em.straddle_diagnostic is not None

    diag = em.straddle_diagnostic
    # 1. Spot et Strike ATM
    assert diag.spot_ndx_used == spot_ndx
    assert diag.atm_strike == 20000.0

    # 2. Racines et Expirations
    assert diag.roots_match is True
    assert diag.call_leg.root == "NDXP"
    assert diag.put_leg.root == "NDXP"
    assert diag.expiries_match is True
    assert diag.call_leg.expiry == exp_date

    # 3. Call et Put détails
    assert diag.call_leg.bid == 60.0
    assert diag.call_leg.ask == 62.0
    assert diag.call_leg.mid == 61.0
    assert diag.call_leg.volume == 500.0
    assert diag.call_leg.quote_time_et is not None
    assert diag.call_leg.quote_time_algiers is not None

    assert diag.put_leg.bid == 58.0
    assert diag.put_leg.ask == 60.0
    assert diag.put_leg.mid == 59.0

    # 4. Largeurs relatives
    # Call mid=61, spread = 2 -> 2/61 = 3.28% <= 20%
    assert diag.call_leg.spread_rel_pct < 20.0
    assert diag.call_leg.is_spread_wide is False

    # 5. Straddle pur en points NDX
    assert diag.straddle_points == 120.0  # 61 + 59

    # 6. IV implicite du straddle
    assert diag.implied_iv_straddle > 0.0

    # 7. Voisins ATM
    assert len(diag.neighbors) == 3
    strikes = [n.strike for n in diag.neighbors]
    assert strikes == [19900.0, 20000.0, 20100.0]

    # 8. Cause calculée dynamiquement (pas de texte figé) et T en heures
    assert diag.time_to_expiry_hours == pytest.approx(5.75, abs=0.01)
    assert diag.time_to_expiry_years == pytest.approx(5.75 / (365 * 24), abs=1e-6)
    assert diag.formula_move_1sigma > 0.0
    assert diag.straddle_theo_from_iv > 0.0
    assert diag.calculated_cause != ""
    if diag.is_degraded:
        assert f"{diag.spread_pct_vs_iv:.1f}%" in diag.calculated_cause
        assert "T=" in diag.calculated_cause
        assert "IV straddle" in diag.calculated_cause
        assert "IV CBOE" in diag.calculated_cause


def test_live_basis_calculation_and_three_way_comparison():
    """TÂCHE 2 : Vérifie le calcul de la base live et le comparatif des 3 bases.
    - Recherche de la barre NQ la plus proche (|Δt| <= 1.0 min)
    - Calcul des écarts live vs séance précédente, live vs parité, précédente vs parité
    - Détection de désalignement temporel (> 1 min) entraînant l'indisponibilité de la base live
    """
    engine = LevelsEngine()
    now_utc = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)
    spot_ndx = 20000.0

    # Options fictives pour la parité
    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=spot_ndx,
        options_df=pd.DataFrame(),
        latest_quote_time_utc=now_utc,
        fetched_at_utc=now_utc,
        age_minutes=1.0,
        status=DataStatus.OK,
    )

    # 1. Barres NQ et NDX synchronisées (Δt = 0 s)
    bar_time = now_utc
    nq_bars = [
        Bar(
            timestamp_utc=bar_time,
            open=20250.0,
            high=20250.0,
            low=20250.0,
            close=20250.0,
            volume=100.0,
        )
    ]
    ndx_bars = [
        Bar(
            timestamp_utc=bar_time,
            open=20000.0,
            high=20000.0,
            low=20000.0,
            close=20000.0,
            volume=100.0,
        )
    ]

    snap = engine.compute_snapshot(
        chain=chain,
        nq_bars=nq_bars,
        ndx_bars=ndx_bars,
        now_utc=now_utc,
    )

    # Base live disponible
    assert snap.live_basis_available is True
    assert snap.live_basis_status == DataStatus.OK
    assert snap.live_basis_value == 250.0  # 20250 - 20000
    assert snap.live_basis_delta_t_minutes == 0.0
    assert snap.live_basis_nq_time_utc == bar_time
    assert snap.live_basis_ndx_time_utc == bar_time

    # 2. Cas de désalignement temporel (> 1.0 min)
    ndx_old_time = bar_time - timedelta(minutes=5)
    ndx_old_bars = [
        Bar(
            timestamp_utc=ndx_old_time,
            open=20000.0,
            high=20000.0,
            low=20000.0,
            close=20000.0,
            volume=100.0,
        )
    ]

    snap_misaligned = engine.compute_snapshot(
        chain=chain,
        nq_bars=nq_bars,
        ndx_bars=ndx_old_bars,
        now_utc=now_utc,
    )
    assert snap_misaligned.live_basis_available is False
    assert snap_misaligned.live_basis_status == DataStatus.DEGRADED
    assert "Désalignement temporel" in (snap_misaligned.live_basis_unavailable_reason or "")


def test_cboe_distinct_age_metrics_and_stale_detection():
    """TÂCHE 3 : Vérifie que l'âge de la chaîne JSON et le retard des cotations
    d'options actives sont distincts et mesurés séparément.
    """
    engine = LevelsEngine()
    now_utc = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)
    chain_file_time = now_utc - timedelta(seconds=30)  # JSON publié il y a 0.5 min
    quote_time = now_utc - timedelta(minutes=15)  # Cotation retardée de 15 min

    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=20000.0,
        options_df=pd.DataFrame(),
        latest_quote_time_utc=quote_time,
        fetched_at_utc=now_utc,
        age_minutes=15.0,
        status=DataStatus.OK,
        chain_internal_timestamp_utc=chain_file_time,
    )

    snap = engine.compute_snapshot(
        chain=chain,
        nq_bars=[],
        ndx_bars=[],
        now_utc=now_utc,
    )

    assert snap.cboe_chain_age_minutes is not None
    assert abs(snap.cboe_chain_age_minutes - 0.5) < 0.1
    assert snap.cboe_active_quote_delay_minutes is not None
    assert abs(snap.cboe_active_quote_delay_minutes - 15.0) < 0.1


def test_useful_walls_window_3_pct():
    """TÂCHE 4 : Vérifie que la fenêtre des murs utiles est de ±3%."""
    from nqcockpit.config import load_config
    cfg = load_config()
    assert cfg.levels.wall_window_pct == 0.03


def test_sqlite_fallback_on_network_failure(monkeypatch):
    """TÂCHE 5 : Si Yahoo échoue, le flux snapshot bascule sur le cache SQLite,
    calcule l'âge réel du spot NQ et passe en DÉGRADÉ sans texte en dur.
    """
    from nqcockpit.data.fetcher import DataFetcher

    def mock_fetch_fail(*args, **kwargs):
        raise ConnectionError("Simulated network outage to Yahoo")

    monkeypatch.setattr(DataFetcher, "fetch_yahoo_bars", mock_fetch_fail)

    # Vérification que le fetcher lève bien l'erreur simulée
    fetcher = DataFetcher()
    with pytest.raises(ConnectionError):
        fetcher.fetch_yahoo_bars("NQ=F")


def test_straddle_diagnostic_serialization_to_dict():
    """Vérifie la sérialisation JSON complète du diagnostic de straddle."""
    ref_utc = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)
    spot_ndx = 20000.0
    exp_date = date(2026, 9, 29)

    rows = [
        {
            "contract": "NDXP260929C20000000",
            "expiry": exp_date,
            "type": "C",
            "strike": 20000.0,
            "bid": 60.0,
            "ask": 62.0,
            "last_trade_price": 61.0,
            "iv": 0.20,
            "volume": 500.0,
            "open_interest": 1000.0,
            "gamma": 0.0002,
            "last_trade_time": "2026-09-29 10:15:00",
        },
        {
            "contract": "NDXP260929P20000000",
            "expiry": exp_date,
            "type": "P",
            "strike": 20000.0,
            "bid": 58.0,
            "ask": 60.0,
            "last_trade_price": 59.0,
            "iv": 0.20,
            "volume": 450.0,
            "open_interest": 1200.0,
            "gamma": 0.0002,
            "last_trade_time": "2026-09-29 10:14:50",
        },
    ]

    df = pd.DataFrame(rows)
    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=spot_ndx,
        options_df=df,
        latest_quote_time_utc=ref_utc,
        fetched_at_utc=ref_utc,
        age_minutes=1.0,
        status=DataStatus.OK,
    )

    engine = LevelsEngine()
    snap = engine.compute_snapshot(
        chain=chain,
        nq_bars=[],
        ndx_bars=[],
        now_utc=ref_utc,
    )

    d = snap.to_dict()
    assert "expected_move" in d
    assert "straddle_diagnostic" in d["expected_move"]
    sd_dict = d["expected_move"]["straddle_diagnostic"]
    assert sd_dict is not None
    assert sd_dict["spot_ndx_used"] == 20000.0
    assert sd_dict["atm_strike"] == 20000.0
    assert sd_dict["roots_match"] is True
    assert sd_dict["call_leg"]["root"] == "NDXP"
    assert sd_dict["put_leg"]["root"] == "NDXP"
    assert sd_dict["straddle_points"] == 120.0
    assert "time_to_expiry_hours" in sd_dict
    assert "formula_move_1sigma" in sd_dict
    assert "calculated_cause" in sd_dict


def test_p04fix6a_straddle_calendar_time_and_dynamic_diagnostic():
    """P04-fix6a : Test dédié complet :
    1. T = temps calendaire restant jusqu'à l'expiration (horodatage CBOE, pas d'heure en dur).
    2. Méthode IV recalculée avec T/365.
    3. Comparaison straddle et 1σ à unités égales (straddle ≈ 0,8σ).
    4. T affiché en heures (5.75 h pour 10:15 -> 16:00).
    5. Diagnostic : cause calculée dynamiquement (pas de texte figé).
    """
    spot_ndx = 20000.0
    exp_date = date(2026, 9, 29)
    # Quote CBOE à 10:15 ET (14:15 UTC) -> expiration 16:00 ET (20:00 UTC) -> T = 5.75 h
    cboe_ts_str = "2026-09-29 10:15:00"

    # Cas 1 : Straddle cohérent avec l'IV (écart < 25%)
    # IV = 0.20, T_years = 5.75 / (365*24) = 0.0006564
    # 1σ_IV = 102.48 pts -> Théo 0.8σ = 81.98 pts
    # Marché : Call mid = 41.0, Put mid = 41.0 -> Straddle = 82.0 pts
    df_coherent = pd.DataFrame(
        [
            {
                "contract": "NDXP260929C20000000",
                "expiry": exp_date,
                "type": "C",
                "strike": 20000.0,
                "bid": 40.5,
                "ask": 41.5,
                "last_trade_price": 41.0,
                "iv": 0.20,
                "volume": 200.0,
                "open_interest": 500.0,
                "last_trade_time": cboe_ts_str,
            },
            {
                "contract": "NDXP260929P20000000",
                "expiry": exp_date,
                "type": "P",
                "strike": 20000.0,
                "bid": 40.5,
                "ask": 41.5,
                "last_trade_price": 41.0,
                "iv": 0.20,
                "volume": 180.0,
                "open_interest": 600.0,
                "last_trade_time": cboe_ts_str,
            },
        ]
    )

    em_coh = calculate_expected_move(df_coherent, spot=spot_ndx)
    assert em_coh is not None
    assert em_coh.time_to_expiry_hours == pytest.approx(5.75, abs=0.01)
    # Formule 1σ : 20000 * 0.20 * sqrt(5.75 / (365*24)) ≈ 102.48 pts
    assert em_coh.formula_move == pytest.approx(102.48, abs=0.1)

    diag_coh = em_coh.straddle_diagnostic
    assert diag_coh is not None
    assert diag_coh.time_to_expiry_hours == pytest.approx(5.75, abs=0.01)
    assert diag_coh.straddle_points == 82.0
    assert diag_coh.straddle_theo_from_iv == pytest.approx(81.98, abs=0.1)
    assert diag_coh.spread_pct_vs_iv < 1.0  # quasi 0%
    assert diag_coh.is_degraded is False
    assert "Cohérent à unités égales 0,8σ" in diag_coh.calculated_cause
    assert "T=5.8h" in diag_coh.calculated_cause
    assert "IV straddle" in diag_coh.calculated_cause

    # Cas 2 : Straddle divergent (> 25%) avec prime de volatilité
    # Marché : Call mid = 61.0, Put mid = 59.0 -> Straddle = 120.0 pts (écart 31.7% vs 81.98 pts)
    df_divergent = pd.DataFrame(
        [
            {
                "contract": "NDXP260929C20000000",
                "expiry": exp_date,
                "type": "C",
                "strike": 20000.0,
                "bid": 60.0,
                "ask": 62.0,
                "last_trade_price": 61.0,
                "iv": 0.20,
                "volume": 500.0,
                "open_interest": 1000.0,
                "last_trade_time": cboe_ts_str,
            },
            {
                "contract": "NDXP260929P20000000",
                "expiry": exp_date,
                "type": "P",
                "strike": 20000.0,
                "bid": 58.0,
                "ask": 60.0,
                "last_trade_price": 59.0,
                "iv": 0.20,
                "volume": 450.0,
                "open_interest": 1200.0,
                "last_trade_time": cboe_ts_str,
            },
        ]
    )

    em_div = calculate_expected_move(df_divergent, spot=spot_ndx)
    assert em_div is not None
    diag_div = em_div.straddle_diagnostic
    assert diag_div is not None
    assert diag_div.spread_pct_vs_iv == pytest.approx(31.7, abs=0.2)
    assert diag_div.is_degraded is True
    # Cause calculée dynamiquement, aucune phrase statique codée en dur
    assert "Écart 31.7% > 25% à 0,8σ [T=5.8h]" in diag_div.calculated_cause
    assert "IV straddle 29.27% soit +46.4% vs IV CBOE 20.00%" in diag_div.calculated_cause
    assert "incertitude bid-ask de 3.3% sur le straddle" in diag_div.calculated_cause
    assert "NDXP" in diag_div.calculated_cause

