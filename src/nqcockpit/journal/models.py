"""Modèles de données P09 — Journal de bord et métriques de performance.

Chaque trade est enregistré avec son contexte auto-taggé (event_risk, régime gamma,
volatilité, distance flip/mur, jour de la semaine). Toutes les statistiques sont
calculées uniquement sur les trades enregistrés dans le journal ; les seuils minimaux
sont définis en config (min_trades, min_pattern_samples).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"  # pas de direction (entrée neutre / à la clôture)


class TradeOutcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


class DisciplineViolationType(str, Enum):
    """Types de violation de discipline — chacun avec une cause explicite."""
    OUT_OF_WINDOW = "hors_fenêtre"
    TRADE_LIMIT = "limite_trades_dépassée"
    TRADE2_AFTER_LOSS = "trade2_après_perte_t1"
    QUICK_REENTRY = "rentrée_rapide_après_sl"
    MOVED_SL = "sl_déplacé"
    EARLY_EXIT = "sortie_anticipée"
    OVERSIZED = "risque_supérieur_limite"
    TILT_SIGNAL = "signal_tilt"


class GammaRegime(str, Enum):
    POSITIVE = "GEX+"
    NEGATIVE = "GEX-"
    UNKNOWN = "inconnu"


class VolRegime(str, Enum):
    LOW = "faible"
    NORMAL = "normale"
    HIGH = "élevée"
    UNKNOWN = "inconnu"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TradeEntry:
    """Un trade enregistré dans le journal.

    Champs obligatoires pour calculer le R :
        entry_price, stop_price, exit_price (avec sign = direction implicite).
    R = (exit - entry) / abs(entry - stop) * sign(direction)
    """

    # Identité
    trade_id: str                          # UUID ou timestamp ISO
    recorded_at: datetime                  # horodatage enregistrement Alger
    session_date: str                      # date de la séance YYYY-MM-DD (NY)

    # Contexte marché
    instrument: str = "MNQ"               # MNQ ou NQ
    direction: TradeDirection = TradeDirection.NONE

    # Prix (points NQ)
    entry_price: float = 0.0
    stop_price: float = 0.0               # SL initial
    tp1_price: Optional[float] = None
    tp2_price: Optional[float] = None
    exit_price: float = 0.0
    exit_reason: str = ""                  # "TP1", "TP2", "SL", "Manuel", "Temps"

    # Résultat
    r_realized: float = 0.0               # calculé automatiquement
    fees_points: float = 0.0              # en points NQ
    outcome: TradeOutcome = TradeOutcome.BREAKEVEN

    # Fenêtre & timing
    window_name: str = ""                  # "trade1" | "trade2" | ""
    entry_time_ny: Optional[datetime] = None
    exit_time_ny: Optional[datetime] = None
    minutes_after_last_sl: Optional[float] = None

    # Contexte auto-taggé (P05/P07/P04)
    event_risk_label: str = ""            # ex. "CPI Tier1 dans 2h"
    gamma_regime: GammaRegime = GammaRegime.UNKNOWN
    vol_regime: VolRegime = VolRegime.UNKNOWN
    distance_flip_pts: Optional[float] = None
    distance_wall_pts: Optional[float] = None
    day_of_week: int = -1                 # 0=lundi … 4=vendredi

    # Discipline
    sl_moved: bool = False
    early_exit: bool = False
    risk_pct_used: float = 0.0

    # Notes
    setup_tag: str = ""
    notes: str = ""
    screenshot_path: str = ""
    contracts: int | None = None

    def compute_r(self) -> float:
        """Calcule le R réalisé depuis les prix bruts."""
        initial_risk = abs(self.entry_price - self.stop_price)
        if initial_risk == 0:
            return 0.0
        raw_r = (self.exit_price - self.entry_price) / initial_risk
        if self.direction == TradeDirection.SHORT:
            raw_r = -raw_r
        return round(raw_r - self.fees_points / max(initial_risk, 1e-9), 4)

    @property
    def initial_risk_pts(self) -> float:
        return abs(self.entry_price - self.stop_price)

    @property
    def pnl_pts(self) -> float:
        raw = self.exit_price - self.entry_price
        return raw if self.direction != TradeDirection.SHORT else -raw

    def pnl_dollars(self, tick_value: float = 2.0) -> float:
        """Valeur en dollars. MNQ = 2$/pt, NQ = 20$/pt."""
        return self.pnl_pts * tick_value


@dataclass
class DisciplineFlag:
    """Une violation de règle détectée sur un trade."""
    trade_id: str
    violation: DisciplineViolationType
    detail: str   # explication lisible, avec les valeurs observées


@dataclass
class TiltAlert:
    """Alerte tilt : ne bloque pas, signale un risque de déviation comportementale."""
    session_date: str
    reason: str         # "2 pertes consécutives", "rentrée < Xmin après SL", etc.
    trades_involved: list[str] = field(default_factory=list)
    pattern_type: str = ""


@dataclass
class DailyStats:
    """Résumé d'une séance, calculé depuis les trades enregistrés."""
    session_date: str
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    n_breakeven: int = 0
    r_total: float = 0.0
    r_max_adverse: float = 0.0           # pire trade de la journée
    daily_loss_limit_r: float = 2.0      # depuis config.rules
    limit_hit: bool = False              # si r_total <= -daily_loss_limit_r
    violations: list[DisciplineFlag] = field(default_factory=list)
    tilt_alerts: list[TiltAlert] = field(default_factory=list)
    compliance_rate: float = 1.0         # trades conformes / total (0→1)

    def to_dict(self) -> dict:
        return {
            "session_date": self.session_date,
            "n_trades": self.n_trades,
            "n_wins": self.n_wins,
            "n_losses": self.n_losses,
            "r_total": round(self.r_total, 4),
            "limit_hit": self.limit_hit,
            "compliance_rate": round(self.compliance_rate, 4),
            "n_violations": len(self.violations),
            "n_tilt_alerts": len(self.tilt_alerts),
        }


@dataclass
class PerformanceStats:
    """Métriques de performance sur un échantillon de trades (avec IC Wilson)."""

    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    n_breakeven: int = 0

    # Espérance
    expectancy_r: Optional[float] = None          # None si n < seuil
    expectancy_ci_low: Optional[float] = None
    expectancy_ci_high: Optional[float] = None

    # Win rate (Wilson IC 95 %)
    win_rate: Optional[float] = None
    win_rate_ci_low: Optional[float] = None
    win_rate_ci_high: Optional[float] = None

    # Distributions
    avg_win_r: Optional[float] = None
    avg_loss_r: Optional[float] = None
    profit_factor: Optional[float] = None
    max_drawdown_r: float = 0.0
    max_loss_streak: int = 0

    # Conformité
    n_compliant: int = 0
    compliance_rate: Optional[float] = None
    expectancy_r_compliant: Optional[float] = None
    expectancy_r_noncompliant: Optional[float] = None

    # Métadonnées
    sample_sufficient: bool = False       # True si n_trades >= min_trades config
    min_trades_required: int = 60
    computed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        def _fmt(v: Optional[float]) -> Optional[float]:
            return round(v, 4) if v is not None else None

        return {
            "n_trades": self.n_trades,
            "sample_sufficient": self.sample_sufficient,
            "min_trades_required": self.min_trades_required,
            "win_rate": _fmt(self.win_rate),
            "win_rate_ci_low": _fmt(self.win_rate_ci_low),
            "win_rate_ci_high": _fmt(self.win_rate_ci_high),
            "expectancy_r": _fmt(self.expectancy_r),
            "expectancy_ci_low": _fmt(self.expectancy_ci_low),
            "expectancy_ci_high": _fmt(self.expectancy_ci_high),
            "avg_win_r": _fmt(self.avg_win_r),
            "avg_loss_r": _fmt(self.avg_loss_r),
            "profit_factor": _fmt(self.profit_factor),
            "max_drawdown_r": _fmt(self.max_drawdown_r),
            "max_loss_streak": self.max_loss_streak,
            "compliance_rate": _fmt(self.compliance_rate),
            "expectancy_r_compliant": _fmt(self.expectancy_r_compliant),
            "expectancy_r_noncompliant": _fmt(self.expectancy_r_noncompliant),
        }


@dataclass
class CoachingReport:
    """Rapport hebdo/mensuel factuel — uniquement si échantillon suffisant."""
    period: str                            # "hebdo" | "mensuel"
    period_label: str                      # ex. "S39-2026"
    generated_at: datetime = field(default_factory=datetime.utcnow)
    stats: Optional[PerformanceStats] = None
    top_leaks: list[str] = field(default_factory=list)   # max 3, chiffrées
    rule_to_reinforce: str = ""
    strength_to_keep: str = ""
    measurable_goals: list[str] = field(default_factory=list)
    insufficient_data: bool = False        # si < seuil → rapport partiel

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "period_label": self.period_label,
            "generated_at": self.generated_at.isoformat(),
            "insufficient_data": self.insufficient_data,
            "stats": self.stats.to_dict() if self.stats else None,
            "top_leaks": self.top_leaks,
            "rule_to_reinforce": self.rule_to_reinforce,
            "strength_to_keep": self.strength_to_keep,
            "measurable_goals": self.measurable_goals,
        }
