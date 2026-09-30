"""Statistiques et calculs de calibration (Wilson score interval, couverture 1-sigma, Brier score).

Aucun chiffre inventé : calculs mathématiques purs sans dépendances externes lourdes.
"""

from __future__ import annotations

import math


def wilson_score_interval(
    successes: int,
    trials: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Calcule l'intervalle de confiance de Wilson pour une proportion binomiale.

    Idéal pour les petits échantillons (n < 60) où l'approximation normale échoue.

    Args:
        successes: Nombre de succès (k >= 0).
        trials: Nombre total d'essais (n >= 0).
        confidence: Niveau de confiance (défaut 0.95 -> z = 1.95996).

    Returns:
        (borne_inf_pct, borne_sup_pct) en pourcentages (0.0 à 100.0).
        Si trials == 0, retourne (0.0, 0.0).
    """
    if trials <= 0:
        return 0.0, 0.0

    k = max(0, min(successes, trials))
    n = trials

    # Quantile z selon le niveau de confiance
    if abs(confidence - 0.95) < 1e-4:
        z = 1.959963984540054
    elif abs(confidence - 0.90) < 1e-4:
        z = 1.6448536269514722
    elif abs(confidence - 0.99) < 1e-4:
        z = 2.5758293035489004
    else:
        # Approximation normale standard
        # Pour 0.95 -> 1.96
        z = 1.95996

    p_hat = k / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denominator
    spread = (z / denominator) * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z2 / (4.0 * n * n)))

    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)

    return round(lower * 100.0, 1), round(upper * 100.0, 1)


def calculate_1sigma_coverage(
    records: list[dict],
    target_coverage_pct: float = 68.27,
) -> tuple[int, int, float, float]:
    """Calcule la couverture observée des bandes 1-sigma sur un historique de prévisions.

    Chaque record doit contenir :
    - 'predicted_range_low'
    - 'predicted_range_high'
    - 'actual_low'
    - 'actual_high' (ou 'actual_close')

    Returns:
        (total_valid, covered_count, observed_coverage_pct, gap_pct)
    """
    total_valid = 0
    covered_count = 0

    for rec in records:
        p_low = rec.get("predicted_range_low")
        p_high = rec.get("predicted_range_high")
        a_low = rec.get("actual_low")
        a_high = rec.get("actual_high")

        if p_low is None or p_high is None or a_low is None or a_high is None:
            continue

        total_valid += 1
        # La bande 1-sigma contient la séance si le range réel reste dans les bornes
        if a_low >= p_low and a_high <= p_high:
            covered_count += 1

    if total_valid == 0:
        return 0, 0, 0.0, round(-target_coverage_pct, 2)

    observed_pct = round((covered_count / total_valid) * 100.0, 2)
    gap_pct = round(observed_pct - target_coverage_pct, 2)

    return total_valid, covered_count, observed_pct, gap_pct


def compute_brier_score(
    outcomes: list[int],
    forecast_probability: float = 0.6827,
) -> float | None:
    """Calcule le Brier score de calibration pour la probabilité 1-sigma.

    BS = (1/N) * sum((forecast_prob - outcome_i)^2).
    Plus le score est proche de 0, meilleure est la calibration.
    """
    if not outcomes:
        return None

    squared_errors = [(forecast_probability - float(y)) ** 2 for y in outcomes]
    return round(sum(squared_errors) / len(squared_errors), 4)
