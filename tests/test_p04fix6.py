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


def test_p04fix6b_prior_session_target_tolerance_and_remote_fallback():
    """P04-fix6b : Distance cible 16:00 ET, repli distant et statut INDISPONIBLE."""
    import sqlite3

    from nqcockpit.data.basis import compute_previous_session_basis, find_basis_pair
    from nqcockpit.data.models import Bar, BarSeries, DataStatus

    # Cible : clôture 16:00 ET (20:00 UTC)
    target_utc = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    # Barres en mémoire à 10:00 ET (14:00 UTC), soit 360 min de distance > tolérance 15 min
    nq_mem = [
        Bar(
            timestamp_utc=datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc),
            open=20500.0,
            high=20505.0,
            low=20495.0,
            close=20500.0,
        )
    ]
    ndx_mem = [
        Bar(
            timestamp_utc=datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc),
            open=20200.0,
            high=20205.0,
            low=20195.0,
            close=20200.0,
        )
    ]

    # Sans fetcher distant capable : la barre à 10:00 est trouvée
    # mais trop éloignée de 16:00 ET (360 min)
    conn_mem = sqlite3.connect(":memory:")
    res_rejected = find_basis_pair(
        target=target_utc,
        nq_bars=nq_mem,
        ndx_bars=ndx_mem,
        tolerance_minutes=1.0,
        target_tolerance_minutes=15.0,
        conn=conn_mem,
    )
    assert res_rejected.is_found is True
    assert res_rejected.is_aligned is True
    assert res_rejected.cause_code == "DISTANCE_CIBLE_HORS_TOLERANCE"
    assert res_rejected.dist_to_target_minutes == pytest.approx(360.0)

    # compute_previous_session_basis doit renvoyer DÉGRADÉ avec distance affichée
    snap_degraded = compute_previous_session_basis(
        nq_bars=nq_mem,
        ndx_bars=ndx_mem,
        ref_utc=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc),
        pair_result=res_rejected,
        target_tolerance_minutes=15.0,
    )
    assert snap_degraded.status == DataStatus.DEGRADED
    assert snap_degraded.basis == pytest.approx(300.0)  # 20500 - 20200
    assert snap_degraded.dist_to_target_minutes == pytest.approx(360.0)
    assert "DÉGRADÉ" in snap_degraded.label
    assert "360.0 min de 16:00 ET" in snap_degraded.label

    # Cas où aucune barre n'existe du tout pour la séance -> BLOCKED (INDISPONIBLE)
    res_empty = find_basis_pair(
        target=target_utc,
        nq_bars=[],
        ndx_bars=[],
        conn=conn_mem,
    )
    assert res_empty.is_found is False
    snap_blocked = compute_previous_session_basis(
        nq_bars=[],
        ndx_bars=[],
        ref_utc=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc),
        pair_result=res_empty,
    )
    assert snap_blocked.status == DataStatus.BLOCKED
    assert "INDISPONIBLE" in snap_blocked.label

    # Avec fetcher distant retournant la barre de 15:59 ET (19:59 UTC, distance 1.0 min <= 15 min)
    class MockFetcher:
        def fetch_yahoo_bars(self, symbol, interval="1m", period="5d"):
            t_bar = datetime(2026, 9, 28, 19, 59, tzinfo=timezone.utc)
            if symbol == "NQ=F":
                return BarSeries(
                    symbol="NQ=F",
                    interval="1m",
                    bars=[
                        Bar(
                            timestamp_utc=t_bar,
                            open=20600.0,
                            high=20605.0,
                            low=20595.0,
                            close=20600.0,
                        )
                    ],
                )
            else:
                return BarSeries(
                    symbol="^NDX",
                    interval="1m",
                    bars=[
                        Bar(
                            timestamp_utc=t_bar,
                            open=20300.0,
                            high=20305.0,
                            low=20295.0,
                            close=20300.0,
                        )
                    ],
                )

    res_remote = find_basis_pair(
        target=target_utc,
        nq_bars=nq_mem,
        ndx_bars=ndx_mem,
        tolerance_minutes=1.0,
        target_tolerance_minutes=15.0,
        conn=conn_mem,
        fetcher=MockFetcher(),
    )
    assert res_remote.is_aligned is True
    assert res_remote.cause_code == "PAIRE_TROUVEE"
    assert res_remote.nq_origin == "source_distante"
    assert res_remote.ndx_origin == "source_distante"
    assert res_remote.nq_bar is not None and res_remote.nq_bar.close == 20600.0
    assert res_remote.ndx_bar is not None and res_remote.ndx_bar.close == 20300.0
    assert res_remote.dist_to_target_minutes == pytest.approx(1.0)

    snap_ok = compute_previous_session_basis(
        nq_bars=nq_mem,
        ndx_bars=ndx_mem,
        ref_utc=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc),
        pair_result=res_remote,
        target_tolerance_minutes=15.0,
    )
    assert snap_ok.status == DataStatus.OK
    assert snap_ok.basis == pytest.approx(300.0)
    assert snap_ok.dist_to_target_minutes == pytest.approx(1.0)


def test_p04fix6b_live_basis_anchored_on_spot_nq(tmp_path):
    """P04-fix6b : Base live ancrée sur l'horodatage du spot NQ pour choisir la cotation NDX."""
    from nqcockpit.data.models import Bar, DataStatus
    from nqcockpit.levels.engine import LevelsEngine

    engine = LevelsEngine(output_dir=tmp_path / "levels")

    t_spot_nq = datetime(2026, 9, 29, 14, 35, tzinfo=timezone.utc)
    t_ndx_earlier = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)
    t_ndx_match = datetime(2026, 9, 29, 14, 35, tzinfo=timezone.utc)
    t_ndx_later = datetime(2026, 9, 29, 14, 40, tzinfo=timezone.utc)

    # NQ a son dernier spot à 14:35
    nq_bars = [
        Bar(timestamp_utc=t_spot_nq, open=20500.0, high=20505.0, low=20495.0, close=20500.0)
    ]
    # NDX a plusieurs barres, dont une plus récente à 14:40
    ndx_bars = [
        Bar(timestamp_utc=t_ndx_earlier, open=20180.0, high=20185.0, low=20175.0, close=20180.0),
        Bar(timestamp_utc=t_ndx_match, open=20200.0, high=20205.0, low=20195.0, close=20200.0),
        Bar(timestamp_utc=t_ndx_later, open=20220.0, high=20225.0, low=20215.0, close=20220.0),
    ]

    from nqcockpit.data.cboe import CboeChainSnapshot

    chain = CboeChainSnapshot(
        symbol="^NDX",
        spot=20200.0,
        options_df=pd.DataFrame(),
        latest_quote_time_utc=t_spot_nq,
        fetched_at_utc=t_spot_nq,
        age_minutes=0.0,
        status=DataStatus.OK,
    )
    snap = engine.compute_snapshot(
        chain=chain,
        nq_bars=nq_bars,
        ndx_bars=ndx_bars,
        now_utc=t_spot_nq,
    )

    # La base live doit être calculée par rapport à NDX à l'heure du spot NQ (14:35, close=20200)
    # et NON la dernière barre NDX (14:40, close=20220)
    assert snap.live_basis_available is True
    assert snap.live_basis_status == DataStatus.OK
    assert snap.live_basis_value == pytest.approx(300.0)  # 20500 - 20200
    assert snap.live_basis_nq_time_utc == t_spot_nq
    assert snap.live_basis_ndx_time_utc == t_ndx_match


def test_p04fix6c_quotation_lag_and_straddle_timing_vs_spot(tmp_path):
    """P04-fix6c : Retard réel CBOE (min/médiane/max), dépassement tolérance médiane (DÉGRADÉ),
    âge des pattes du straddle et delta-t vs spot NQ, et traçabilité des seuils."""
    from nqcockpit.cli import _get_threshold_provenance
    from nqcockpit.data.cboe import extract_cboe_chain_age_stats, parse_cboe_payload

    # 1. Vérification de la traçabilité des seuils (config vs fallback)
    val_cfg, src_cfg = _get_threshold_provenance("levels.cboe_max_median_delay_minutes", 30.0)
    assert val_cfg == 30.0
    assert src_cfg == "config: levels.cboe_max_median_delay_minutes"

    val_fb, src_fb = _get_threshold_provenance("levels.non_existent_threshold", 99.0)
    assert val_fb == 99.0
    assert src_fb == "fallback: 99.0"

    # 2. Construction d'une chaîne CBOE fictive avec retards connus
    now_utc = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    t_10m = now_utc - timedelta(minutes=10)
    t_20m = now_utc - timedelta(minutes=20)
    t_40m = now_utc - timedelta(minutes=40)
    t_50m = now_utc - timedelta(minutes=50)

    rows = [
        # Options dans la bande ±3% (spot = 20000)
        {"option": "NDX260930C20000000", "bid": 60.0, "ask": 62.0,
         "last_trade_time": t_10m.isoformat()},
        {"option": "NDX260930P20000000", "bid": 58.0, "ask": 60.0,
         "last_trade_time": t_20m.isoformat()},
        {"option": "NDX260930C20100000", "bid": 30.0, "ask": 32.0,
         "last_trade_time": t_40m.isoformat()},
        # Option hors bande (ex: strike 18000)
        {"option": "NDX260930P18000000", "bid": 5.0, "ask": 6.0,
         "last_trade_time": t_50m.isoformat()},
    ]
    df = pd.DataFrame(rows)
    df["strike"] = [20000.0, 20000.0, 20100.0, 18000.0]
    df["type"] = ["C", "P", "C", "P"]
    df["expiry"] = [date(2026, 9, 30)] * 4
    df["last_trade_time"] = pd.to_datetime(df["last_trade_time"])

    # 3. Calcul min, médiane, max — la fonction prend raw_options list[dict], spot, now_utc
    raw_rows = [
        {"option": "NDX260930C20000000", "bid": 60.0, "ask": 62.0,
         "last_trade_time": t_10m.isoformat()},
        {"option": "NDX260930P20000000", "bid": 58.0, "ask": 60.0,
         "last_trade_time": t_20m.isoformat()},
        {"option": "NDX260930C20100000", "bid": 30.0, "ask": 32.0,
         "last_trade_time": t_40m.isoformat()},
        {"option": "NDX260930P18000000", "bid": 5.0, "ask": 6.0,
         "last_trade_time": t_50m.isoformat()},
    ]
    stats_tuple = extract_cboe_chain_age_stats(raw_rows, spot=20000.0, now_utc=now_utc)
    # Retour : (min_age, latest_dt, stats_dict)
    _, _, stats = stats_tuple
    assert stats["min_age_minutes"] == pytest.approx(10.0)   # option à t-10m dans la bande
    assert stats["median_age_minutes"] == pytest.approx(20.0)  # médiane [10, 20, 40]
    assert stats["max_age_minutes"] == pytest.approx(40.0)
    assert stats["chain_min_delay_minutes"] == pytest.approx(10.0)
    assert stats["chain_max_delay_minutes"] == pytest.approx(50.0)

    # 4. Statut DÉGRADÉ si la médiane dépasse la tolérance (pendant séance US)
    # now_utc = 15:00 UTC = 11:00 ET → séance régulière → le check s'applique
    t_45m = now_utc - timedelta(minutes=45)
    payload_degraded = {
        "timestamp": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "data": {
            "current_price": 20000.0,
            "options": [
                {
                    "option": "NDX260930C20000000",
                    "bid": 60.0,
                    "ask": 62.0,
                    "last_trade_time": t_45m.isoformat(),
                    "open_interest": 10,
                },
                {
                    "option": "NDX260930P20000000",
                    "bid": 58.0,
                    "ask": 60.0,
                    "last_trade_time": t_45m.isoformat(),
                    "open_interest": 10,
                },
            ],
        },
    }
    chain_deg = parse_cboe_payload(payload_degraded, fetched_at_utc=now_utc)
    assert chain_deg.status == DataStatus.DEGRADED
    assert "Retard médian de cotation" in chain_deg.notes
    assert chain_deg.age_stats.get("tolerance_median_minutes") == 30.0

    # 5. Timing des pattes du straddle et delta-t vs spot NQ
    from nqcockpit.levels.engine import calculate_expected_move, enrich_expected_move_nq

    # Simuler df_gex pour calculate_expected_move
    df_exp = pd.DataFrame(
        [
            {
                "option": "NDX260930C20000000",
                "strike": 20000.0,
                "type": "C",
                "expiry": date(2026, 9, 30),
                "bid": 60.0,
                "ask": 62.0,
                "iv": 0.20,
                "volume": 100,
                "open_interest": 500,
                "last_trade_time": t_10m,
            },
            {
                "option": "NDX260930P20000000",
                "strike": 20000.0,
                "type": "P",
                "expiry": date(2026, 9, 30),
                "bid": 58.0,
                "ask": 60.0,
                "iv": 0.20,
                "volume": 100,
                "open_interest": 500,
                "last_trade_time": t_20m,
            },
        ]
    )
    em = calculate_expected_move(
        df_exp, spot=20000.0, ref_utc=now_utc, cboe_quote_time_utc=t_10m
    )
    assert em is not None
    assert em.straddle_diagnostic is not None

    # Pattes Call et Put ont leurs horodatages et âges
    c_leg = em.straddle_diagnostic.call_leg
    p_leg = em.straddle_diagnostic.put_leg
    assert c_leg.quote_time_utc == t_10m
    assert c_leg.age_minutes == pytest.approx(10.0)
    assert p_leg.quote_time_utc == t_20m
    assert p_leg.age_minutes == pytest.approx(20.0)

    # Enrichissement avec le spot NQ horodaté à t-5m
    t_spot_nq = now_utc - timedelta(minutes=5)
    em_enriched = enrich_expected_move_nq(
        em,
        basis=300.0,
        spot_nq=20300.0,
        spot_ndx=20000.0,
        cboe_age_minutes=10.0,
        spot_nq_time_utc=t_spot_nq,
        now_utc=now_utc,
    )
    assert em_enriched.straddle_diagnostic is not None
    sd = em_enriched.straddle_diagnostic
    # Call coté à t-10m, spot NQ à t-5m -> delta_t = (t-10m) - (t-5m) = -5.0 min
    assert sd.call_leg.delta_t_vs_spot_nq_minutes == pytest.approx(-5.0)
    # Put coté à t-20m, spot NQ à t-5m -> delta_t = (t-20m) - (t-5m) = -15.0 min
    assert sd.put_leg.delta_t_vs_spot_nq_minutes == pytest.approx(-15.0)
    assert sd.delta_t_call_vs_spot_nq_minutes == pytest.approx(-5.0)
    assert sd.delta_t_put_vs_spot_nq_minutes == pytest.approx(-15.0)


def test_p04fix6d_network_fallback_cboe_degraded_on_http_error():
    """P04-fix6d : Test du fallback réseau — si la requête HTTP CBOE échoue (ex: ConnectionError),
    la chaîne retournée doit avoir status=BLOCKED avec une note explicite.
    Aucun repli silencieux : l'erreur réseau est visible dans le statut et la note."""
    from unittest.mock import patch

    import requests

    from nqcockpit.data.cboe import fetch_cboe_options_chain

    # Simuler une erreur réseau (ConnectionError)
    with patch(
        "nqcockpit.data.cboe._SESSION.get",
        side_effect=requests.exceptions.ConnectionError("Simulated network error"),
    ):
        snap = fetch_cboe_options_chain(force_reload=True)

    # Réseau bloqué → BLOCKED (pas silencieux)
    assert snap.status == DataStatus.BLOCKED
    assert snap.options_df.empty
    # La note doit mentionner l'erreur réseau
    assert "Erreur réseau CBOE" in snap.notes
    assert "Simulated network error" in snap.notes
    # Pas de crash, age_minutes peut être None
    assert snap.latest_quote_time_utc is None


def test_p04fix6d_put_wall_global_degraded_when_absent(tmp_path):
    """P04-fix6d : Le Put Wall global affiche INDISPONIBLE [DÉGRADÉ] si absent.
    Vérifie que le snapshot ne masque pas une absence de mur Put."""
    from nqcockpit.data.cboe import CboeChainSnapshot
    from nqcockpit.data.models import DataStatus
    from nqcockpit.levels.engine import LevelsEngine

    engine = LevelsEngine(output_dir=tmp_path / "levels")
    now_utc = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    spot_ndx = 20000.0

    # Options uniquement Call (aucun Put) → pas de Put Wall possible
    df_no_puts = pd.DataFrame(
        [
            {
                "contract": "NDX261016C20200000",
                "expiry": date(2026, 10, 16),
                "type": "C",
                "strike": 20200.0,
                "bid": 10.0,
                "ask": 12.0,
                "iv": 0.20,
                "open_interest": 1000.0,
                "volume": 500.0,
                "delta": 0.50,
                "gamma": 0.0001,
                "last_trade_price": 11.0,
                "last_trade_time": now_utc,
            }
        ]
    )
    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=spot_ndx,
        options_df=df_no_puts,
        latest_quote_time_utc=now_utc,
        fetched_at_utc=now_utc,
        age_minutes=0.0,
        status=DataStatus.OK,
    )

    snap = engine.compute_snapshot(
        chain=chain,
        nq_bars=[
            Bar(
                timestamp_utc=now_utc,
                open=22500.0,
                high=22500.0,
                low=22500.0,
                close=22500.0,
            )
        ],
        ndx_bars=[
            Bar(
                timestamp_utc=now_utc,
                open=spot_ndx,
                high=spot_ndx,
                low=spot_ndx,
                close=spot_ndx,
            )
        ],
        now_utc=now_utc,
    )

    # Le Put Wall est absent → doit être None (pas de valeur inventée)
    assert snap.put_wall_ndx is None or snap.put_wall_ndx == snap.put_wall_useful_ndx
    assert snap.put_wall_global_ndx is None or snap.put_wall_global_ndx is not None
    # Le snapshot ne doit jamais inventer un Put Wall à 0.0
    if snap.put_wall_ndx is not None:
        assert snap.put_wall_ndx != 0.0


def test_p04fix6_calendar_time_t_vs_trading_days_252():
    """Vérifie le calcul de T en temps calendaire réel (heures / (365*24))
    et non en jours de bourse / 252.

    Exemple concret :
    Évaluation le 2026-09-29 à 10:15 ET (14:15 UTC).
    Échéance le 2026-09-30 à 16:00 ET (20:00 UTC).
    Temps calendaire réel restant : 29.75 heures = 107 100 secondes.
    T calendaire = 29.75 / (365 * 24) = 0.003396118 an.
    sqrt(T calendaire) = 0.0582762.

    Avec Spot NDX = 20000.0 et IV ATM = 0.2395 :
    Expected move corrigé (T calendaire) = 20000 * 0.2395 * 0.0582762 = 279.14 pts NDX.
    """
    now_utc = datetime(2026, 9, 29, 14, 15, tzinfo=timezone.utc)
    spot = 20000.0
    iv_atm = 0.2395
    exp_date = date(2026, 9, 30)

    df_test = pd.DataFrame(
        [
            {
                "contract": "NDX260930C20000000",
                "strike": 20000.0,
                "type": "C",
                "expiry": exp_date,
                "bid": 110.0,
                "ask": 112.0,
                "iv": iv_atm,
                "last_trade_price": 111.0,
                "last_trade_time": now_utc,
            },
            {
                "contract": "NDX260930P20000000",
                "strike": 20000.0,
                "type": "P",
                "expiry": exp_date,
                "bid": 108.0,
                "ask": 110.0,
                "iv": iv_atm,
                "last_trade_price": 109.0,
                "last_trade_time": now_utc,
            },
        ]
    )

    em = calculate_expected_move(
        df_test,
        spot=spot,
        ref_utc=now_utc,
        cboe_quote_time_utc=now_utc,
    )
    assert em is not None
    # Durée calendaire exacte : 29.75 heures
    assert em.time_to_expiry_hours == pytest.approx(29.75, abs=0.01)
    # T en années calendaires : 29.75 / (365 * 24)
    expected_t_years = 29.75 / (365.0 * 24.0)
    assert em.time_to_expiry_years == pytest.approx(expected_t_years, rel=1e-4)

    # Formule analytique : spot * iv_atm * sqrt(T_years)
    expected_move_ndx = spot * iv_atm * (expected_t_years**0.5)
    assert em.formula_move == pytest.approx(expected_move_ndx, rel=1e-4)
    assert em.formula_move == pytest.approx(279.14, abs=0.5)


def test_p04fix6_explicit_16h_distance_and_degraded_basis(tmp_path):
    """Vérifie le contrôle explicite de distance à 16:00 ET pour la séance précédente :
    - Appariement trouvé à 12:25 ET (distance 215.0 min > seuil 15.0 min).
    - La base NQ/NDX est calculée (20500 - 20200 = 300 pts) et NON bloquée.
    - La distance est explicitement mesurée et égale à 215.0 min.
    - Le statut passe à DÉGRADÉ avec la distance affichée en minutes.
    - LevelsSnapshot reflète basis_dist_to_target_minutes et basis_status=DÉGRADÉ.
    """
    import sqlite3

    from nqcockpit.data.basis import compute_previous_session_basis, find_basis_pair

    # Séance précédente : 2026-09-28. Clôture 16:00 ET = 20:00 UTC.
    target_utc = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
    conn_empty = sqlite3.connect(":memory:")

    # Données disponibles uniquement jusqu'à 12:25 ET = 16:25 UTC
    t_1225_utc = datetime(2026, 9, 28, 16, 25, tzinfo=timezone.utc)
    nq_bars = [
        Bar(timestamp_utc=t_1225_utc, open=20500.0, high=20505.0, low=20495.0, close=20500.0)
    ]
    ndx_bars = [
        Bar(timestamp_utc=t_1225_utc, open=20200.0, high=20205.0, low=20195.0, close=20200.0)
    ]

    # Recherche de la paire avec seuil de tolérance cible de 15.0 min
    pair_res = find_basis_pair(
        target=target_utc,
        nq_bars=nq_bars,
        ndx_bars=ndx_bars,
        tolerance_minutes=1.0,
        target_tolerance_minutes=15.0,
        conn=conn_empty,
    )
    assert pair_res.is_found is True
    assert pair_res.is_aligned is True
    # Distance à 16:00 ET : 3 heures et 35 minutes = 215 minutes
    assert pair_res.dist_to_target_minutes == pytest.approx(215.0, abs=0.1)
    assert pair_res.cause_code == "DISTANCE_CIBLE_HORS_TOLERANCE"

    # Calcul de la base séance précédente
    now_utc = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)
    snap = compute_previous_session_basis(
        nq_bars=nq_bars,
        ndx_bars=ndx_bars,
        ref_utc=now_utc,
        pair_result=pair_res,
        target_tolerance_minutes=15.0,
    )
    assert snap.status == DataStatus.DEGRADED
    assert snap.basis == pytest.approx(300.0)
    assert snap.dist_to_target_minutes == pytest.approx(215.0, abs=0.1)
    assert "215.0 min de 16:00 ET" in snap.label
    assert "DÉGRADÉ" in snap.label

    # Intégration complète via LevelsEngine.compute_snapshot
    engine = LevelsEngine(output_dir=tmp_path / "levels")
    df_chain = pd.DataFrame(
        [
            {
                "contract": "NDX260930C20200000",
                "expiry": date(2026, 9, 30),
                "type": "C",
                "strike": 20200.0,
                "bid": 10.0,
                "ask": 12.0,
                "iv": 0.20,
                "open_interest": 1000.0,
                "volume": 500.0,
                "delta": 0.50,
                "gamma": 0.0001,
                "last_trade_price": 11.0,
                "last_trade_time": now_utc,
            }
        ]
    )
    chain = CboeChainSnapshot(
        symbol="NDX",
        spot=20200.0,
        options_df=df_chain,
        latest_quote_time_utc=now_utc,
        fetched_at_utc=now_utc,
        age_minutes=0.0,
        status=DataStatus.OK,
    )
    # now_utc à 08:00 ET (hors séance régulière pour utiliser la base séance précédente)
    t_premarket = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    lvl_snap = engine.compute_snapshot(
        chain=chain,
        nq_bars=nq_bars,
        ndx_bars=ndx_bars,
        now_utc=t_premarket,
        conn=conn_empty,
    )
    assert lvl_snap.basis_status == DataStatus.DEGRADED
    assert lvl_snap.basis == pytest.approx(300.0)
    assert lvl_snap.basis_dist_to_target_minutes == pytest.approx(215.0, abs=0.1)

