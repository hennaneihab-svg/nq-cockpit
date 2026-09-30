"""Moteur de prévision d'amplitude et de calibration (P07).

Règles de conformité strictes :
- .agents/skills/nq-principles/SKILL.md : aucun biais directionnel (aucun sens haussier/baissier).
- Séparation stricte de l'amplitude prévue et de l'état de calibration ("calibré" vs "non calibré").
- Aucun ajustement empirique sans échantillon validé (n >= min_calibration_sessions, config).
- Définitions du type de journée figées dans config.yaml AVANT tout calcul.
- Intervalles de confiance de Wilson à 95 % pour chaque proportion empirique.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from nqcockpit.config import AppConfig, DayTypesConfig
from nqcockpit.forecast.models import (
    AmplitudeForecast,
    CalibrationMetric,
    CalibrationReport,
    DayTypeProbability,
)
from nqcockpit.forecast.stats import (
    calculate_1sigma_coverage,
    compute_brier_score,
    wilson_score_interval,
)

log = logging.getLogger(__name__)

ET_TZ = ZoneInfo("America/New_York")
ALG_TZ = ZoneInfo("Africa/Algiers")
UTC = timezone.utc


def classify_session(
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    expected_move_pts: float | None,
    day_types_cfg: DayTypesConfig,
) -> str:
    """Classifie une séance historique selon les critères figés dans config.yaml.

    - Tendance : |Close - Open| / (High - Low) >= trend_min_change_ratio (0.60)
    - Volatile : (High - Low) >= volatile_min_em_ratio * expected_move (1.15)
    - Range : (High - Low) <= range_max_em_ratio * expected_move (0.85)
    - Par défaut : 'range' (comportement d'équilibre)
    """
    day_range = high_price - low_price
    if day_range <= 0:
        return "range"

    directional_efficiency = abs(close_price - open_price) / day_range
    if directional_efficiency >= day_types_cfg.trend_min_change_ratio:
        return "trend"

    if expected_move_pts and expected_move_pts > 0:
        em_ratio = day_range / expected_move_pts
        if em_ratio >= day_types_cfg.volatile_min_em_ratio:
            return "volatile"
        if em_ratio <= day_types_cfg.range_max_em_ratio:
            return "range"

    return "range"


def compute_day_type_probabilities(
    historical_sessions: list[dict],
    expected_move_pts: float | None,
    config: AppConfig,
) -> list[DayTypeProbability]:
    """Calcule les probabilités empiriques de type de journée avec intervalle de Wilson.

    Définitions figées dans config.yaml avant tout calcul.
    """
    n = len(historical_sessions)
    min_sessions = config.forecast.min_calibration_sessions
    day_cfg = config.forecast.day_types
    confidence = config.forecast.confidence_level

    counts = {"range": 0, "trend": 0, "volatile": 0}

    for sess in historical_sessions:
        o = sess.get("open")
        h = sess.get("high")
        lo = sess.get("low")
        c = sess.get("close")
        if o is None or h is None or lo is None or c is None:
            continue
        st = classify_session(o, h, lo, c, expected_move_pts, day_cfg)
        counts[st] = counts.get(st, 0) + 1

    definitions = {
        "range": f"range <= {day_cfg.range_max_em_ratio:.2f} * expected move (config)",
        "trend": f"|clôture - ouverture| / range >= {day_cfg.trend_min_change_ratio:.2f} (config)",
        "volatile": f"range >= {day_cfg.volatile_min_em_ratio:.2f} * expected move (config)",
    }

    is_sufficient = n >= min_sessions
    note_suff = "" if is_sufficient else f"échantillon insuffisant (n={n} < {min_sessions})"

    results: list[DayTypeProbability] = []
    for dt_name in ["range", "trend", "volatile"]:
        c = counts.get(dt_name, 0)
        prob = round((c / n) * 100.0, 1) if n > 0 else 0.0
        low, high = wilson_score_interval(c, n, confidence=confidence)
        results.append(
            DayTypeProbability(
                day_type=dt_name,
                count=c,
                total_sessions=n,
                probability_pct=prob,
                wilson_ci_low_pct=low,
                wilson_ci_high_pct=high,
                is_sufficient=is_sufficient,
                definition=definitions.get(dt_name, ""),
                note=note_suff,
            )
        )

    return results


def compute_amplitude_forecast(
    spot_nq: float | None,
    base_expected_move_pts: float | None,
    target_date: str,
    historical_sessions: list[dict],
    config: AppConfig,
    now_utc: datetime | None = None,
) -> AmplitudeForecast:
    """Calcule la prévision d'amplitude du jour avec état de calibration séparé.

    RÈGLE : Aucun ajustement empirique sans échantillon prouvé (n >= min_calibration_sessions).
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    n = len(historical_sessions)
    min_sessions = config.forecast.min_calibration_sessions

    # Probabilités de type de journée
    day_probs = compute_day_type_probabilities(
        historical_sessions=historical_sessions,
        expected_move_pts=base_expected_move_pts,
        config=config,
    )

    # État de calibration
    is_calibrated = n >= min_sessions
    if is_calibrated:
        cal_status = "calibré"
        cal_reason = f"échantillon suffisant ({n} séances >= {min_sessions})"
        adj_factor = 1.0  # Facteur calibré (neutre ici sans sur-ajustement)
    else:
        cal_status = "non calibré"
        cal_reason = f"échantillon insuffisant (n={n} < {min_sessions} séances requises)"
        adj_factor = None  # Aucun ajustement non prouvé

    # Amplitude projetée
    projected_em: float | None = None
    range_low: float | None = None
    range_high: float | None = None

    if base_expected_move_pts is not None:
        projected_em = round(base_expected_move_pts, 2)
        if spot_nq is not None:
            half_em = base_expected_move_pts / 2.0
            range_low = round(spot_nq - half_em, 2)
            range_high = round(spot_nq + half_em, 2)

    status = "OK"
    status_detail = ""
    if base_expected_move_pts is None:
        status = "DÉGRADÉ"
        status_detail = "Expected move de base non disponible"

    return AmplitudeForecast(
        as_of_utc=now_utc,
        target_date=target_date,
        spot_nq=round(spot_nq, 2) if spot_nq is not None else None,
        base_expected_move_pts=round(base_expected_move_pts, 2) if base_expected_move_pts else None,
        base_source="ACT/365 CBOE NDX Options (P04-fix6)",
        empirical_adjustment_factor=adj_factor,
        is_calibrated=is_calibrated,
        calibration_status=cal_status,
        calibration_reason=cal_reason,
        projected_amplitude_pts=projected_em,
        range_low=range_low,
        range_high=range_high,
        day_type_probabilities=day_probs,
        status=status,
        status_detail=status_detail,
    )


def record_daily_forecast(
    forecast: AmplitudeForecast,
    conn: sqlite3.Connection,
) -> bool:
    """Enregistre la prévision du jour dans la table forecasts pour le suivi de calibration."""
    sql = """
    INSERT OR REPLACE INTO forecasts (
        forecast_id, timestamp_utc, target_date,
        predicted_range_low, predicted_range_high,
        actual_low, actual_high,
        source, status, created_at_utc
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now_iso = datetime.now(UTC).isoformat()
    fid = f"FCST-{forecast.target_date}"
    try:
        with conn:
            conn.execute(
                sql,
                (
                    fid,
                    forecast.as_of_utc.isoformat(),
                    forecast.target_date,
                    forecast.range_low,
                    forecast.range_high,
                    None,  # actual_low alimenté après la séance
                    None,  # actual_high alimenté après la séance
                    forecast.base_source,
                    forecast.status,
                    now_iso,
                ),
            )
        log.info("Prévision enregistrée dans forecasts: %s", fid)
        return True
    except sqlite3.Error as exc:
        log.warning("Impossible d'enregistrer la prévision %s: %s", fid, exc)
        return False


def build_calibration_report(
    conn: sqlite3.Connection,
    config: AppConfig,
    now_utc: datetime | None = None,
) -> CalibrationReport:
    """Construit le rapport de calibration et génère le fichier reports/calibration.md."""
    if now_utc is None:
        now_utc = datetime.now(UTC)

    target_coverage = config.forecast.target_coverage_1sigma * 100.0  # 68.27%
    min_sessions = config.forecast.min_calibration_sessions

    try:
        cur = conn.execute(
            """
            SELECT target_date, predicted_range_low, predicted_range_high,
                   actual_low, actual_high, status
            FROM forecasts
            ORDER BY target_date ASC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        rows = []

    total_valid, covered, obs_pct, gap_pct = calculate_1sigma_coverage(
        rows, target_coverage_pct=target_coverage
    )

    outcomes: list[int] = []
    for r in rows:
        a_l = r.get("actual_low")
        a_h = r.get("actual_high")
        p_l = r.get("predicted_range_low")
        p_h = r.get("predicted_range_high")
        if a_l is not None and a_h is not None and p_l is not None and p_h is not None:
            is_cov = 1 if (a_l >= p_l and a_h <= p_h) else 0
            outcomes.append(is_cov)

    target_prob = config.forecast.target_coverage_1sigma
    brier = compute_brier_score(outcomes, forecast_probability=target_prob)

    is_calibrated = total_valid >= min_sessions and abs(gap_pct) <= 5.0

    cal_metric = CalibrationMetric(
        total_forecasts=total_valid,
        covered_count=covered,
        observed_coverage_pct=obs_pct,
        target_coverage_pct=round(target_coverage, 2),
        coverage_gap_pct=gap_pct,
        brier_score=brier,
        is_calibrated=is_calibrated,
        status="OK" if is_calibrated else f"non calibré (n={total_valid} < {min_sessions})",
    )

    now_et = now_utc.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")
    now_alg = now_utc.astimezone(ALG_TZ).strftime("%Y-%m-%d %H:%M Alger")

    # Génération du markdown
    bs_display = f"{cal_metric.brier_score:.4f}" if cal_metric.brier_score is not None else "N/A"
    md_lines = [
        "# Rapport de Calibration des Prévisions d'Amplitude (P07)",
        "",
        f"**Date du rapport :** {now_et} | {now_alg}  ",
        f"**État global de calibration :** `{cal_metric.status}`  ",
        "",
        "---",
        "",
        "## 1. Métriques de Couverture 1-Sigma",
        "",
        (
            f"- **Séances évaluées (n) :** {cal_metric.total_forecasts} "
            f"(seuil de validation requis : {min_sessions})"
        ),
        f"- **Séances couvertes dans la bande :** {cal_metric.covered_count}",
        f"- **Taux de couverture observé :** {cal_metric.observed_coverage_pct:.2f} %",
        f"- **Taux théorique 1-sigma attendu :** {cal_metric.target_coverage_pct:.2f} %",
        f"- **Écart à la cible :** {cal_metric.coverage_gap_pct:+.2f} %",
        f"- **Brier score :** {bs_display}",
        "",
        "---",
        "",
        "## 2. Règle de Non-Surajustement",
        "",
        "> **JAMAIS d'ajustement non prouvé :** tant que l'échantillon $n$ n'atteint pas "
        f"le seuil configuré de {min_sessions} séances complètes archivées, la prévision "
        "d'amplitude reste strictement égale à l'expected move de base (P04 ACT/365 CBOE) "
        "étiquetée **« non calibré »**.",
        "",
        "---",
        "",
        "## 3. Historique Récent des Prévisions",
        "",
        "| Date cible | Prévu Bas | Prévu Haut | Réel Bas | Réel Haut | Couvert ? | Statut |",
        "| :--- | :--- | :--- | :--- | :--- | :---: | :--- |",
    ]

    if not rows:
        md_lines.append("| *Aucune prévision archivée* | - | - | - | - | - | `n=0` |")
    else:
        for r in rows[-15:]:
            p_l_str = f"{r['predicted_range_low']:.1f}" if r.get("predicted_range_low") else "N/A"
            p_h_str = f"{r['predicted_range_high']:.1f}" if r.get("predicted_range_high") else "N/A"
            a_l_str = f"{r['actual_low']:.1f}" if r.get("actual_low") else "N/A"
            a_h_str = f"{r['actual_high']:.1f}" if r.get("actual_high") else "N/A"
            if r.get("actual_low") and r.get("predicted_range_low"):
                is_c = (
                    r["actual_low"] >= r["predicted_range_low"]
                    and r["actual_high"] <= r["predicted_range_high"]
                )
                cov_str = "OUI" if is_c else "NON"
            else:
                cov_str = "en attente"
            row_str = (
                f"| {r['target_date']} | {p_l_str} | {p_h_str} | {a_l_str} | {a_h_str} | "
                f"{cov_str} | `{r['status']}` |"
            )
            md_lines.append(row_str)

    md_lines.append("")
    md_content = "\n".join(md_lines)

    # Sauvegarde sur disque dans reports/calibration.md
    report_path = Path("reports/calibration.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md_content, encoding="utf-8")

    return CalibrationReport(
        generated_at_utc=now_utc,
        metrics_1sigma=cal_metric,
        historical_records=rows,
        markdown_content=md_content,
    )
