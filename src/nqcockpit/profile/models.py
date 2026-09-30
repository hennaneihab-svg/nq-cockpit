"""Modèles de données pour le profil de séance, la carte de scénarios
et les drapeaux NO-TRADE (P08).

Règles impératives :
- .agents/skills/nq-principles/SKILL.md : aucun biais directionnel.
- Statut par composant (OK / DÉGRADÉ) explicite, jamais masqué.
- Scénarios strictement conditionnels ("Si... alors...").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ComponentStatus(str, Enum):
    """Statut de santé d'un composant source."""

    OK = "OK"
    DEGRADED = "DÉGRADÉ"


class NoTradeFlagCode(str, Enum):
    """Codes normalisés des drapeaux NO-TRADE."""

    EVENT_RED = "EVENT_RED"
    WALL_COMPRESSION = "WALL_COMPRESSION"
    STALE_DATA = "STALE_DATA"
    ABNORMAL_BASIS = "ABNORMAL_BASIS"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"


@dataclass
class ComponentHealth:
    """Santé détaillée d'un composant de données."""

    name: str
    status: str  # "OK" ou "DÉGRADÉ: <cause>"
    detail: str = ""
    age_minutes: float | None = None
    timestamp_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KeyLevel:
    """Niveau de prix clé en points NQ avec distance au spot."""

    name: str
    symbol: str
    price: float
    level_type: str  # "GAMMA", "OVERNIGHT", "HISTORICAL", "EXPECTED_MOVE"
    distance_pts: float
    distance_pct: float
    source: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioCard:
    """Carte de scénario conditionnel "si... alors..." pour un niveau clé.

    STRICTEMENT NON-DIRECTIONNEL : décrit le plan et le comportement attendu
    du carnet / des teneurs de marché sans jamais prédire la direction du prix.
    """

    level_name: str
    level_price: float
    level_type: str
    if_condition: str  # Doit commencer par "Si..."
    then_plan: str  # Doit commencer par "alors..."
    context_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NoTradeFlag:
    """Drapeau d'interdiction de trading ou d'alerte critique."""

    code: NoTradeFlagCode
    title: str
    triggered: bool
    status: str  # "ACTIF", "INACTIF", "DÉGRADÉ"
    reason: str
    severity: str  # "BLOCKING", "INFORMATIVE"
    source_module: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["code"] = self.code.value
        return d


@dataclass
class NoTradeAssessment:
    """Évaluation globale des drapeaux NO-TRADE."""

    is_trading_allowed: bool
    overall_status: str  # "AUTORISÉ (sous conditions)" ou "NO-TRADE ACTIF"
    active_flags_count: int
    blocking_flags: list[NoTradeFlag] = field(default_factory=list)
    all_flags: list[NoTradeFlag] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_trading_allowed": self.is_trading_allowed,
            "overall_status": self.overall_status,
            "active_flags_count": self.active_flags_count,
            "blocking_flags": [f.to_dict() for f in self.blocking_flags],
            "all_flags": [f.to_dict() for f in self.all_flags],
            "summary": self.summary,
        }


@dataclass
class DayProfile:
    """Profil complet de la séance combinant P04, P05, P06 et P07."""

    as_of_utc: str
    as_of_algiers: str
    as_of_et: str
    target_date: str
    spot_nq: float

    # Risque événementiel (P05/P06)
    event_risk_level: str  # "GREEN", "AMBER", "RED"
    event_risk_reason: str
    next_tier1_event: str | None
    next_tier1_countdown: str | None

    # Régime de volatilité & macro (P07)
    volatility_regime: str  # "VOLATILITÉ NORMALE", "VOLATILITÉ ÉLEVÉE", "VOLATILITÉ COMPRIMÉE"
    vix_level: float | None
    vxn_level: float | None
    overnight_range_pts: float | None

    # Régime Gamma (P04)
    gamma_regime: str  # "POSITIVE_GAMMA", "NEGATIVE_GAMMA", "NEUTRAL"
    net_gex_dollars: float | None
    distance_to_flip_pts: float | None

    # Expected move & consommation (P07)
    base_expected_move_pts: float
    em_consumption_pct: float | None

    # Types de journée et justifications
    probable_day_type: str
    day_type_reasons: list[str]

    # Niveaux clés et scénarios
    key_levels: list[KeyLevel] = field(default_factory=list)
    scenarios: list[ScenarioCard] = field(default_factory=list)

    # Drapeaux NO-TRADE
    no_trade: NoTradeAssessment = field(
        default_factory=lambda: NoTradeAssessment(
            is_trading_allowed=True,
            overall_status="AUTORISÉ",
            active_flags_count=0,
        )
    )

    # Statut par composant (séparation stricte, aucun composant masqué)
    component_statuses: dict[str, ComponentHealth] = field(default_factory=dict)
    status: str = "OK"
    status_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_utc": self.as_of_utc,
            "as_of_algiers": self.as_of_algiers,
            "as_of_et": self.as_of_et,
            "target_date": self.target_date,
            "spot_nq": self.spot_nq,
            "event_risk": {
                "level": self.event_risk_level,
                "reason": self.event_risk_reason,
                "next_tier1_event": self.next_tier1_event,
                "next_tier1_countdown": self.next_tier1_countdown,
            },
            "volatility_regime": {
                "regime": self.volatility_regime,
                "vix": self.vix_level,
                "vxn": self.vxn_level,
                "overnight_range_pts": self.overnight_range_pts,
            },
            "gamma_regime": {
                "regime": self.gamma_regime,
                "net_gex_dollars": self.net_gex_dollars,
                "distance_to_flip_pts": self.distance_to_flip_pts,
            },
            "expected_move": {
                "base_em_pts": self.base_expected_move_pts,
                "em_consumption_pct": self.em_consumption_pct,
            },
            "session_type": {
                "probable_type": self.probable_day_type,
                "reasons": self.day_type_reasons,
            },
            "key_levels": [lvl.to_dict() for lvl in self.key_levels],
            "scenarios": [sc.to_dict() for sc in self.scenarios],
            "no_trade": self.no_trade.to_dict(),
            "component_statuses": {
                k: v.to_dict() for k, v in self.component_statuses.items()
            },
            "status": self.status,
            "status_detail": self.status_detail,
        }
