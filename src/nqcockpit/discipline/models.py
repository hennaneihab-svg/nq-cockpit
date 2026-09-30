"""Modèles de données pour la porte de discipline et gestionnaire de risque (P09 réel).

Strictement conforme à AGENTS.md / GEMINI.md :
- Machine à états déterministe
- Sizing avec arrondi inférieur pour ne jamais dépasser le risque
- Aucune exécution d'ordre
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SessionDisciplineStatus(str, Enum):
    """Statut de la machine à états de la séance."""

    READY = "READY"
    LOCKED_MAX_TRADES = "LOCKED_MAX_TRADES"
    LOCKED_TRADE1_LOSS = "LOCKED_TRADE1_LOSS"
    LOCKED_DAILY_LOSS = "LOCKED_DAILY_LOSS"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    OUT_OF_WINDOW = "OUT_OF_WINDOW"


class ChecklistVerdict(str, Enum):
    """Verdict strict de la checklist pré-trade."""

    GO = "GO"
    STOP = "STOP"


@dataclass(frozen=True)
class DisciplineSessionState:
    """État vivant de la séance de trading à un instant t."""

    status: SessionDisciplineStatus
    can_trade: bool
    current_window_name: str | None
    trades_taken_today: int
    max_trades_allowed: int
    trades_remaining: int
    r_realized_today: float
    daily_loss_limit_r: float
    last_sl_timestamp: datetime | None = None
    cooldown_remaining_seconds: float = 0.0
    lock_reasons: list[str] = field(default_factory=list)

    @property
    def cooldown_remaining_minutes(self) -> float:
        """Minutes restantes dans le cooldown post-SL."""
        return max(0.0, self.cooldown_remaining_seconds / 60.0)

    @property
    def cooldown_countdown_str(self) -> str:
        """Format MM:SS pour l'affichage temps réel."""
        total_sec = int(max(0.0, self.cooldown_remaining_seconds))
        mins = total_sec // 60
        secs = total_sec % 60
        return f"{mins:02d}:{secs:02d}"


@dataclass(frozen=True)
class PositionSizingResult:
    """Résultat du calcul de taille de position selon le risque défini."""

    instrument: str
    account_size: float
    risk_pct: float
    stop_points: float
    point_value: float
    risk_budget_dollars: float
    risk_per_contract_dollars: float
    contracts: int
    actual_risk_dollars: float
    actual_risk_pct: float
    warning: str | None = None
    prop_firm_warning: str | None = None


@dataclass
class PreTradeChecklist:
    """Données saisies pour la checklist pré-trade."""

    p08_reviewed: bool = False
    trading_plan: str = ""
    sizing_result: PositionSizingResult | None = None
    event_risk_tier1_red: bool = False


@dataclass(frozen=True)
class ChecklistResult:
    """Verdict de la checklist pré-trade."""

    verdict: ChecklistVerdict
    passed: bool
    blocking_reasons: list[str]
    items_status: dict[str, bool]
