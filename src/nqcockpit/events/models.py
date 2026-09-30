"""Modèles de données pour le radar d'événements NQ Cockpit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DataStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DÉGRADÉ"
    BLOCKED = "BLOQUÉ"


@dataclass
class CalendarEvent:
    """Un événement économique ou de politique monétaire."""

    name: str
    """Nom court : 'CPI', 'FOMC', 'NFP', 'FOMC Minutes', 'Powell'…"""

    tier: int
    """1 = impact majeur (RED potentiel), 2 = impact secondaire (AMBER potentiel)."""

    scheduled_utc: datetime
    """Horodatage précis en UTC. Si seule la date est connue, heure = 12:00 UTC."""

    source: str
    """Source ayant fourni cet événement : 'fed_rss', 'fed_html', 'bls', 'bea',
    'fred', 'forexfactory', 'static'."""

    description: str = ""
    """Description longue (optionnelle)."""

    consensus: str | None = None
    """Consensus de marché (ForexFactory, si disponible)."""

    previous: str | None = None
    """Valeur précédente (ForexFactory, si disponible)."""

    actual: str | None = None
    """Valeur publiée (si déjà publié)."""

    source_fetched_utc: datetime | None = None
    """Horodatage UTC du fetch de la source."""

    source_age_seconds: float = 0.0
    """Âge de la donnée source en secondes."""

    status: DataStatus = DataStatus.OK
    """Statut de la donnée : OK / DÉGRADÉ / BLOQUÉ."""

    all_sources: list[str] = field(default_factory=list)
    """Liste de toutes les sources qui ont confirmé cet événement."""

    time_provenance: str = ""
    """Origine explicite de l'heure (ex: 'table versionnée BLS (10:00 ET)')."""

    consensus_source: str = ""
    """Source de la valeur de prévision/précédent (ex: 'ForexFactory')."""

    verified: bool = True
    """True si la date est vérifiée avec une source primaire officielle."""

    primary_source_url: str = ""
    """URL de la source primaire officielle (ex: 'https://www.bls.gov/schedule/news_release/cpi.htm')."""

    consultation_date: str = ""
    """Date de consultation de la source primaire (ex: '2026-09-30')."""

    @property
    def date_origin(self) -> str:
        """Origine de la date réellement retenue.

        'officielle', 'ForexFactory', 'calendrier statique', 'estimée (règle)', 'à confirmer'.
        Si la date n'est pas vérifiée, retourne 'à confirmer'.
        """
        if not self.verified:
            return "à confirmer"

        # Si deux sources concordent sur la même date, pas une estimation
        if len(self.all_sources) >= 2 and self.source == "fred":
            if "forexfactory" in self.all_sources:
                return "ForexFactory"
            if "bls" in self.all_sources or "static" in self.all_sources:
                return "calendrier statique"
            return "FRED (concordante)"

        if self.source == "forexfactory":
            return "ForexFactory"
        if self.source in ("static", "bls", "ism") and self.status == DataStatus.DEGRADED:
            return "calendrier statique"
        if self.source in ("fed_html", "fed_rss", "bea", "ism") or (
            self.source == "bls" and self.status == DataStatus.OK
        ):
            return "officielle"
        if self.source == "fred":
            if len(self.all_sources) >= 2:
                return "FRED (concordante)"
            return "estimée (règle)"
        if "forexfactory" in self.all_sources:
            return "ForexFactory"
        if any(s in self.all_sources for s in ("bls", "static", "ism")):
            return "calendrier statique"
        return "calendrier statique"


@dataclass
class EarningsEvent:
    """Résultat d'une mégacap (yfinance)."""

    ticker: str
    """Symbole boursier : 'NVDA', 'AAPL'…"""

    scheduled_utc: datetime | None
    """Date/heure de publication des résultats, si connue."""

    confirmed: bool = False
    """True si la date est confirmée par yfinance."""

    eps_estimate: float | None = None
    """Estimation EPS analyst (si disponible)."""

    revenue_estimate: float | None = None
    """Estimation chiffre d'affaires (si disponible)."""

    source_fetched_utc: datetime | None = None
    """Horodatage UTC du fetch."""

    source_age_seconds: float = 0.0
    """Âge de la donnée source en secondes."""

    status: DataStatus = DataStatus.OK
    """Statut : OK / DÉGRADÉ (yfinance absent/erreur) / BLOQUÉ."""

    error_msg: str | None = None
    """Message d'erreur si statut != OK."""

    raw_date_str: str = ""
    """Date ou fourchette brute renvoyée par yfinance."""

    time_provided: bool = False
    """True si une heure de publication exacte a été fournie."""

    timing: str = "après clôture, heure non fournie"
    """Timing de publication : 'après clôture, heure non fournie', 'avant ouverture'…"""


@dataclass
class SourceHealth:
    """Santé d'une source de données événementielles."""

    source: str
    status: DataStatus
    events_count: int = 0
    error_msg: str | None = None
    fetched_utc: datetime | None = None


@dataclass
class EventRiskReport:
    """Rapport complet du radar d'événements."""

    as_of_utc: datetime
    """Horodatage UTC du rapport."""

    risk_level: str
    """'GREEN', 'AMBER' ou 'RED'."""

    reason: str
    """Explication détaillée du niveau de risque (toujours fournie)."""

    events_14d: list[CalendarEvent] = field(default_factory=list)
    """Tous les événements dans l'horizon configuré, triés par date."""

    earnings_14d: list[EarningsEvent] = field(default_factory=list)
    """Résultats de mégacaps dans l'horizon."""

    divergences: list[str] = field(default_factory=list)
    """Conflits détectés entre sources (même événement, heure différente > 5 min)."""

    source_health: list[SourceHealth] = field(default_factory=list)
    """Statut de chaque source interrogée."""

    next_event_countdown: str = ""
    """Texte affiché : 'Prochain: CPI dans 5j 14h 22m (Alger : 14 oct. 14h30)'."""

    calendar_display_algiers: list[str] = field(default_factory=list)
    """Calendrier des 14 prochains jours formaté pour affichage (heure Alger)."""

    daily_risks: list[dict] = field(default_factory=list)
    """Évaluation du risque pour chaque jour de l'horizon."""

    horizon_days: int = 14
    """Horizon temporel du rapport en jours."""

    @property
    def coverage_summary(self) -> str:
        """Résumé de la couverture (ex: 'couverture 8/14 jours')."""
        total = len(self.daily_risks) if self.daily_risks else self.horizon_days
        if not self.daily_risks:
            return f"couverture {total}/{total} jours"
        covered = sum(
            1 for dr in self.daily_risks
            if "DÉGRADÉ" not in dr.get("risk_level", "")
            and "INCONNU" not in dr.get("risk_level", "")
        )
        return f"couverture {covered}/{total} jours"

    @property
    def risk_header(self) -> str:
        """En-tête de risque global affichant la couverture.

        Jamais 'GREEN' seul si des jours sont DÉGRADÉ/INCONNU.
        """
        cov = self.coverage_summary
        return f"{self.risk_level} — {cov}"
