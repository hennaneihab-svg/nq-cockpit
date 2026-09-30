"""Tests P07 — Contexte macroéconomique et prévisions d'amplitude.

Couvre :
- Intervalle de Wilson (test_wilson_score_interval)
- Couverture 1-sigma et Brier score (test_1sigma_coverage_and_brier)
- Calcul des percentiles 1 an et variations 5 jours (test_series_stats_percentiles_and_delta)
- Statistiques de la session overnight CME (test_overnight_range_and_gap)
- Contexte COT CFTC sans biais directionnel (test_cot_positioning_no_directional_bias)
- Définition figée des types de journée (test_day_type_classification)
- Séparation amplitude vs calibration (test_amplitude_forecast_calibration_separation)
- Génération du rapport reports/calibration.md (test_build_calibration_report)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig, DayTypesConfig
from nqcockpit.data.models import Bar
from nqcockpit.forecast.engine import (
    build_calibration_report,
    classify_session,
    compute_amplitude_forecast,
)
from nqcockpit.forecast.stats import (
    calculate_1sigma_coverage,
    compute_brier_score,
    wilson_score_interval,
)
from nqcockpit.macro.engine import (
    compute_overnight_stats,
    compute_series_stats,
)
from nqcockpit.macro.models import CotPositioning

UTC = timezone.utc
ET_TZ = ZoneInfo("America/New_York")


def _make_dummy_app_config() -> AppConfig:
    from nqcockpit.config import load_config

    return load_config()


# ---------------------------------------------------------------------------
# Test 1 : Intervalle de confiance de Wilson
# ---------------------------------------------------------------------------


def test_wilson_score_interval():
    """Vérifie la formule de Wilson sur des cas limites et des cas standards."""
    # Cas 0/0 -> (0.0, 0.0)
    low, high = wilson_score_interval(0, 0)
    assert low == 0.0 and high == 0.0

    # Cas 10/20 (50 % observé)
    low, high = wilson_score_interval(10, 20, confidence=0.95)
    assert low < 50.0 < high
    assert 28.0 <= low <= 32.0  # Wilson 10/20 ~ [29.9%, 70.1%]
    assert 68.0 <= high <= 72.0

    # Cas 68/100 (68 % observé, proche de 1-sigma)
    low, high = wilson_score_interval(68, 100, confidence=0.95)
    assert 58.0 <= low <= 60.0  # Wilson 68/100 ~ [58.3%, 76.3%]
    assert 75.0 <= high <= 78.0

    # Propriété : low <= p_hat <= high
    low, high = wilson_score_interval(15, 60, confidence=0.95)
    p_hat = (15 / 60) * 100.0
    assert low <= p_hat <= high


# ---------------------------------------------------------------------------
# Test 2 : Couverture 1-sigma et Brier score
# ---------------------------------------------------------------------------


def test_1sigma_coverage_and_brier():
    """Vérifie le calcul de couverture des bandes 1-sigma et le Brier score."""
    # 10 records : 7 séances couvertes (actual reste dans [pred_low, pred_high])
    records = []
    for i in range(10):
        if i < 7:
            # Couvert
            records.append({
                "predicted_range_low": 20000.0,
                "predicted_range_high": 20200.0,
                "actual_low": 20020.0,
                "actual_high": 20180.0,
            })
        else:
            # Sortie de bande (dépassement)
            records.append({
                "predicted_range_low": 20000.0,
                "predicted_range_high": 20200.0,
                "actual_low": 19950.0,
                "actual_high": 20250.0,
            })

    total, covered, obs_pct, gap_pct = calculate_1sigma_coverage(
        records, target_coverage_pct=68.27
    )
    assert total == 10
    assert covered == 7
    assert obs_pct == 70.0
    assert round(gap_pct, 2) == round(70.0 - 68.27, 2)

    # Brier score avec 7 succès et 3 échecs vs proba 0.6827
    outcomes = [1] * 7 + [0] * 3
    bs = compute_brier_score(outcomes, forecast_probability=0.6827)
    assert bs is not None
    assert 0.15 <= bs <= 0.25


# ---------------------------------------------------------------------------
# Test 3 : Percentiles 1 an et variations 5 jours
# ---------------------------------------------------------------------------


def test_series_stats_percentiles_and_delta():
    """Vérifie le calcul du rang percentile sur 252 jours et la variation 5 jours."""
    # Générer 260 observations linéaires (1.0 à 260.0)
    history = [(f"2026-01-{i:02d}", float(i)) for i in range(1, 261)]

    metric = compute_series_stats(
        name="US 10Y",
        symbol="DGS10",
        history=history,
        lookback_days=252,
        delta_days=5,
        source_label="FRED",
    )

    assert metric.name == "US 10Y"
    assert metric.current_value == 260.0
    assert metric.percentile_1y == 100.0  # Valeur max sur la fenêtre
    # Delta 5j = history[-1] (260) - history[-6] (255) = 5.0
    assert metric.delta_5d == 5.0
    assert metric.delta_5d_pct is not None
    assert metric.status == "OK"

    # Cas historique vide -> statut DÉGRADÉ
    metric_empty = compute_series_stats("US 10Y", "DGS10", [], source_label="FRED")
    assert "DÉGRADÉ" in metric_empty.status
    assert metric_empty.current_value is None


# ---------------------------------------------------------------------------
# Test 4 : Statistiques Overnight NQ (CME 18:00 - 09:30 ET)
# ---------------------------------------------------------------------------


def test_overnight_range_and_gap():
    """Vérifie le calcul du range et du gap de la session de nuit CME."""
    # Créer des barres simulant une clôture veille à 16:00 ET (20000.0)
    # puis session de nuit (Low: 19950, High: 20100, Last: 20050)
    t_prior_close = datetime(2026, 9, 29, 20, 0, tzinfo=UTC)  # 16:00 ET
    t_overnight_1 = datetime(2026, 9, 29, 22, 0, tzinfo=UTC)  # 18:00 ET
    t_overnight_2 = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)   # 04:00 ET

    bars = [
        Bar(
            timestamp_utc=t_prior_close,
            open=19990.0,
            high=20005.0,
            low=19985.0,
            close=20000.0,
            volume=100,
        ),
        Bar(
            timestamp_utc=t_overnight_1,
            open=20005.0,
            high=20100.0,
            low=20000.0,
            close=20080.0,
            volume=50,
        ),
        Bar(
            timestamp_utc=t_overnight_2,
            open=20080.0,
            high=20090.0,
            low=19950.0,
            close=20050.0,
            volume=70,
        ),
    ]

    ref_utc = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)  # 08:00 ET jour J
    ov = compute_overnight_stats(bars, now_utc=ref_utc)

    assert ov.status == "OK"
    assert ov.high_price == 20100.0
    assert ov.low_price == 19950.0
    assert ov.range_pts == 150.0  # 20100 - 19950
    assert ov.prior_close_price == 20000.0
    assert ov.gap_pts == 50.0  # 20050 - 20000


# ---------------------------------------------------------------------------
# Test 5 : COT Positionnement — Règle de non-directionnalité
# ---------------------------------------------------------------------------


def test_cot_positioning_no_directional_bias():
    """Le rapport COT doit obligatoirement inclure l'avertissement non-directionnel."""
    cot = CotPositioning(
        report_date="2026-09-22",
        contract_name="NASDAQ-100 CONSOLIDATED - CME",
        non_commercial_long=54230,
        non_commercial_short=48110,
        non_commercial_net=6120,
    )
    assert cot.note == "contexte de positionnement, pas un signal directionnel"
    assert cot.non_commercial_net == 6120


# ---------------------------------------------------------------------------
# Test 6 : Définitions figées des types de journée (config.yaml)
# ---------------------------------------------------------------------------


def test_day_type_classification():
    """Vérifie la classification des séances selon les critères figés dans DayTypesConfig."""
    cfg = DayTypesConfig(
        range_max_em_ratio=0.85,
        trend_min_change_ratio=0.60,
        volatile_min_em_ratio=1.15,
    )
    expected_move = 200.0

    # 1. Tendance : |Close - Open| / Range >= 0.60
    # Open: 20000, Close: 20150, High: 20160, Low: 19990 -> 150/170 = 0.88 >= 0.60
    st_trend = classify_session(20000.0, 20160.0, 19990.0, 20150.0, expected_move, cfg)
    assert st_trend == "trend"

    # 2. Volatile : Range >= 1.15 * expected_move (230 pts)
    # Open: 20000, Close: 20050, High: 20260, Low: 20000 -> Range: 260 >= 230
    st_vol = classify_session(20000.0, 20260.0, 20000.0, 20050.0, expected_move, cfg)
    assert st_vol == "volatile"

    # 3. Range : Range <= 0.85 * expected_move (170 pts)
    # Open: 20000, Close: 20020, High: 20080, Low: 19980 -> Range: 100 <= 170
    st_range = classify_session(20000.0, 20080.0, 19980.0, 20020.0, expected_move, cfg)
    assert st_range == "range"


# ---------------------------------------------------------------------------
# Test 7 : Séparation stricte amplitude prévue vs état de calibration
# ---------------------------------------------------------------------------


def test_amplitude_forecast_calibration_separation():
    """L'amplitude et l'état de calibration sont strictement séparés.

    Si n < 60 : aucun ajustement empirique (ajustement=None), statut='non calibré'.
    """
    app_cfg = _make_dummy_app_config()

    # Créer 15 séances historiques (< 60)
    sessions_small = [
        {"open": 20000.0, "high": 20100.0, "low": 19950.0, "close": 20020.0}
        for _ in range(15)
    ]

    fcst_uncalibrated = compute_amplitude_forecast(
        spot_nq=20000.0,
        base_expected_move_pts=220.0,
        target_date="2026-09-30",
        historical_sessions=sessions_small,
        config=app_cfg,
    )

    # 1. Vérification de la séparation stricte
    assert fcst_uncalibrated.is_calibrated is False
    assert fcst_uncalibrated.calibration_status == "non calibré"
    assert fcst_uncalibrated.empirical_adjustment_factor is None
    # RÈGLE : JAMAIS D'AJUSTEMENT NON PROUVÉ
    assert fcst_uncalibrated.projected_amplitude_pts == 220.0  # Base conservée
    assert fcst_uncalibrated.range_low == 19890.0  # 20000 - 110
    assert fcst_uncalibrated.range_high == 20110.0  # 20000 + 110

    # 2. Vérification quand n >= 60 (calibré)
    sessions_large = [
        {"open": 20000.0, "high": 20100.0, "low": 19950.0, "close": 20020.0}
        for _ in range(65)
    ]
    fcst_calibrated = compute_amplitude_forecast(
        spot_nq=20000.0,
        base_expected_move_pts=220.0,
        target_date="2026-09-30",
        historical_sessions=sessions_large,
        config=app_cfg,
    )
    assert fcst_calibrated.is_calibrated is True
    assert fcst_calibrated.calibration_status == "calibré"
    assert fcst_calibrated.empirical_adjustment_factor == 1.0


# ---------------------------------------------------------------------------
# Test 8 : Construction du rapport de calibration (reports/calibration.md)
# ---------------------------------------------------------------------------


def test_build_calibration_report(tmp_path):
    """Vérifie la génération du rapport reports/calibration.md."""
    app_cfg = _make_dummy_app_config()

    # Connexion DB temporaire avec table forecasts
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            forecast_id TEXT UNIQUE NOT NULL,
            timestamp_utc TEXT NOT NULL,
            target_date TEXT NOT NULL,
            predicted_range_low REAL,
            predicted_range_high REAL,
            actual_low REAL,
            actual_high REAL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        )
        """
    )
    # Insérer quelques prévisions
    conn.execute(
        """
        INSERT INTO forecasts (
            forecast_id, timestamp_utc, target_date, predicted_range_low,
            predicted_range_high, actual_low, actual_high, source, status,
            created_at_utc
        ) VALUES (
            'FCST-1', '2026-09-28T08:00:00', '2026-09-28', 19900.0, 20100.0,
            19920.0, 20080.0, 'test', 'OK', 'now'
        )
        """
    )
    conn.commit()

    report = build_calibration_report(conn, config=app_cfg)
    conn.close()

    assert report.metrics_1sigma.total_forecasts == 1
    assert report.metrics_1sigma.covered_count == 1
    assert report.metrics_1sigma.observed_coverage_pct == 100.0
    assert "JAMAIS d'ajustement non prouvé" in report.markdown_content
    assert Path("reports/calibration.md").exists()
