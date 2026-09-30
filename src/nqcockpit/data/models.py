"""Modèles de données pour la couche de données NQ Cockpit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class DataStatus(str, Enum):
    """Statuts de santé standardisés pour toute donnée du cockpit (OK / DÉGRADÉ / BLOQUÉ)."""

    OK = "OK"
    DEGRADED = "DÉGRADÉ"
    BLOCKED = "BLOQUÉ"

    @classmethod
    def _missing_(cls, value: object) -> DataStatus | None:
        if isinstance(value, str):
            val_upper = value.upper()
            if val_upper in ("DEGRADED", "DEGRADE", "DÉGRADÉ"):
                return cls.DEGRADED
            if val_upper in ("BLOCKED", "BLOQUE", "BLOQUÉ"):
                return cls.BLOCKED
            if val_upper == "OK":
                return cls.OK
        return None


@dataclass(frozen=True)
class Bar:
    """Barre OHLCV horodatée en UTC."""

    timestamp_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class BarSeries:
    """Série de barres OHLCV avec métadonnées de traçabilité."""

    symbol: str
    interval: str  # "1m", "5m", "1d"
    bars: list[Bar] = field(default_factory=list)
    source: str = "unknown"
    fetched_at_utc: datetime = field(default_factory=datetime.utcnow)
    status: DataStatus = DataStatus.OK
    latency_seconds: float | None = None
    notes: str = ""

    @property
    def count(self) -> int:
        return len(self.bars)

    @property
    def latest_bar(self) -> Bar | None:
        return self.bars[-1] if self.bars else None


@dataclass
class FredObservation:
    """Observation macro FRED avec date d'observation (pas d'âge en minutes)."""

    series_id: str
    observation_date: str  # YYYY-MM-DD
    value: float
    source: str = "FRED"
    fetched_at_utc: datetime = field(default_factory=datetime.utcnow)
    status: DataStatus = DataStatus.OK
    notes: str = ""


@dataclass
class BasisSnapshot:
    """Snapshot de conversion NDX vers NQ et base future-spot."""

    timestamp_utc: datetime
    nq_price: float
    ndx_price: float
    basis: float
    is_session_basis: bool
    status: DataStatus
    label: str  # "base en séance" ou "base de la séance précédente"
    age_minutes: float | None = None
    synthetic_basis: float | None = None
    basis_spread_delta: float | None = None
    nq_timestamp_utc: datetime | None = None
    ndx_timestamp_utc: datetime | None = None
    method: str = "live"
    delta_t_minutes: float = 0.0
    tolerance_minutes: float = 1.0
    is_aligned: bool = True
    formula: str = "base = NQ_close - NDX_spot"
    delay_compensation_note: str | None = None
    # Distance entre la barre retenue et la cible 16:00 ET (min). None = non calculé.
    dist_to_target_minutes: float | None = None
    # Seuil utilisé pour marquer DÉGRADÉ (issu de la config, sinon fallback).
    target_tolerance_minutes: float | None = None


@dataclass
class SearchStepResult:
    """Résultat d'une étape de recherche pour la paire NQ/NDX."""

    step_name: str  # "memoire" | "sqlite" | "source_distante"
    nq_found: bool
    nq_time_utc: datetime | None = None
    nq_close: float | None = None
    ndx_found: bool = False
    ndx_time_utc: datetime | None = None
    ndx_spot: float | None = None
    details: str = ""


@dataclass
class PairResult:
    """Résultat unique et prouvé de la recherche de paire NQ/NDX.

    Lu conjointement par compute_previous_session_basis et build_diagnostic_1c.
    """

    target_utc: datetime
    nq_bar: Bar | None = None
    ndx_bar: Bar | None = None
    nq_origin: str | None = None  # "memoire" | "sqlite" | "source_distante" | None
    ndx_origin: str | None = None  # "memoire" | "sqlite" | "source_distante" | None
    search_steps: list[SearchStepResult] = field(default_factory=list)
    delta_t_minutes: float | None = None
    tolerance_minutes: float = 1.0
    is_aligned: bool = False
    cause_code: str = "AUTRE"
    cause_detail: str = ""
    action_taken: str = ""
    dist_to_target_minutes: float | None = None
    target_tolerance_minutes: float = 15.0

    @property
    def is_found(self) -> bool:
        return self.nq_bar is not None and self.ndx_bar is not None

    @property
    def nq_close(self) -> float | None:
        return self.nq_bar.close if self.nq_bar else None

    @property
    def ndx_spot(self) -> float | None:
        return self.ndx_bar.close if self.ndx_bar else None


@dataclass
class RollInfo:
    """Information sur le contrat NQ actif et la détection de roll."""

    reference_date: date
    active_contract: str
    next_contract: str
    expiry_date: date
    roll_window_start: date
    is_roll_window: bool
    days_to_expiry: int
    status: str
    message: str
