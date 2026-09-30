"""Modèles de données pour le module de prévision d'amplitude et de calibration (P07).

Interdit : toute prévision de sens (haussier/baissier).
Règles :
- Séparation stricte de l'amplitude prévue et de l'état de calibration.
- Aucun ajustement empirique sans échantillon suffisant (n >= min_calibration_sessions).
- Définitions des types de journée figées dans config.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DayTypeProbability:
    """Probabilité empirique d'un type de journée avec intervalle de confiance de Wilson."""

    day_type: str
    """'range' | 'trend' | 'volatile'."""

    count: int
    """Nombre d'occurrences observées dans l'échantillon historique."""

    total_sessions: int
    """Taille totale de l'échantillon (n)."""

    probability_pct: float
    """Fréquence observée = (count / total_sessions) * 100."""

    wilson_ci_low_pct: float
    """Borne inférieure de l'intervalle de confiance de Wilson à 95 %."""

    wilson_ci_high_pct: float
    """Borne supérieure de l'intervalle de confiance de Wilson à 95 %."""

    is_sufficient: bool
    """True si total_sessions >= min_calibration_sessions (config)."""

    definition: str = ""
    """Définition issue de config.yaml."""

    note: str = ""
    """Mention explicite si n < seuil ('échantillon insuffisant')."""


@dataclass
class AmplitudeForecast:
    """Prévision d'amplitude du jour avec état de calibration séparé.

    L'amplitude de base (P04 ACT/365) et l'ajustement empirique sont séparés.
    Si non calibré : ajustement = 1.0 (ou None) avec mention 'non calibré'.
    """

    as_of_utc: datetime
    """Horodatage UTC du calcul."""

    target_date: str
    """Date de la séance ciblée (ex: '2026-09-30')."""

    spot_nq: float | None
    """Cours spot NQ utilisé."""

    base_expected_move_pts: float | None
    """Expected move de base (P04 ACT/365, non ajusté)."""

    base_source: str = "ACT/365 CBOE NDX Options (P04-fix6)"
    """Origine du calcul de base."""

    empirical_adjustment_factor: float | None = None
    """Facteur d'ajustement empirique par régime (None si non calibré)."""

    is_calibrated: bool = False
    """True UNIQUEMENT si n >= min_calibration_sessions et validé."""

    calibration_status: str = "non calibré"
    """'calibré' | 'non calibré' (toujours affiché séparément de l'amplitude)."""

    calibration_reason: str = ""
    """Explication (ex: 'échantillon insuffisant n=14 < 60 séances')."""

    projected_amplitude_pts: float | None = None
    """Amplitude finale projetée (base si non calibré, base * facteur si calibré)."""

    range_low: float | None = None
    """Borne basse projetée = Spot - (Amplitude / 2)."""

    range_high: float | None = None
    """Borne haute projetée = Spot + (Amplitude / 2)."""

    day_type_probabilities: list[DayTypeProbability] = field(default_factory=list)
    """Distribution des probabilités empiriques de type de journée."""

    status: str = "OK"
    """'OK' | 'DÉGRADÉ: <raison>'."""

    status_detail: str = ""


@dataclass
class CalibrationMetric:
    """Métriques de calibration de couverture 1 sigma."""

    total_forecasts: int
    """Nombre total de prévisions archivées avec résultat réel connu."""

    covered_count: int
    """Nombre de séances où le range réel a été contenu dans la bande prévue."""

    observed_coverage_pct: float
    """Taux de couverture observé = (covered_count / total_forecasts) * 100."""

    target_coverage_pct: float = 68.27
    """Taux de couverture théorique 1 sigma attendu."""

    coverage_gap_pct: float = 0.0
    """Écart = observé - cible."""

    brier_score: float | None = None
    """Brier score de calibration."""

    is_calibrated: bool = False
    """True si n >= min_calibration_sessions et écart dans la tolérance."""

    status: str = "OK"


@dataclass
class CalibrationReport:
    """Rapport complet de suivi de calibration (sauvegardé dans reports/calibration.md)."""

    generated_at_utc: datetime
    metrics_1sigma: CalibrationMetric
    historical_records: list[dict] = field(default_factory=list)
    markdown_content: str = ""
