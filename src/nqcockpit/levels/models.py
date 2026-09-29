"""Modèles typés pour le moteur de niveaux (gamma -> NQ)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from nqcockpit.data.models import DataStatus


@dataclass
class GammaWall:
    """Mur de gamma avec strike NDX, strike converti NQ et GEX associé."""

    strike: float
    gex: float
    type: str  # "CALL", "PUT", "NET"
    rank: int
    expiry: date | None = None
    nq_strike: float | None = None


@dataclass
class Diagnostic1cInfo:
    """Détail du Diagnostic 1c pour la séance de référence précédente."""

    session_date: date
    target_time_et: str
    target_time_algiers: str
    target_time_utc: datetime
    # NQ candidate
    nq_candidate_found: bool
    nq_candidate_time_et: str | None
    nq_candidate_time_algiers: str | None
    nq_candidate_close: float | None
    nq_bars_count_day: int
    nq_first_bar_time: str | None
    nq_last_bar_time: str | None
    # NDX candidate
    ndx_candidate_found: bool
    ndx_candidate_time_et: str | None
    ndx_candidate_time_algiers: str | None
    ndx_candidate_spot: float | None
    # Timing
    delta_t_minutes: float | None
    tolerance_minutes: float
    # Cause & Action
    cause_code: str
    cause_detail: str
    action_taken: str


@dataclass
class ExpectedMoveInfo:
    """Informations complètes sur le move attendu (Expected Move)."""

    formula_move: float
    straddle_move: float | None
    iv_atm: float
    days_to_expiry: float
    lower_bound_ndx: float
    upper_bound_ndx: float
    lower_bound_nq: float
    upper_bound_nq: float
    expiry: date | None = None
    straddle_move_nq: float | None = None
    straddle_lower_nq: float | None = None
    straddle_upper_nq: float | None = None
    iv_move_nq: float | None = None
    iv_lower_nq: float | None = None
    iv_upper_nq: float | None = None
    expiry_day_of_week: str | None = None
    data_age_minutes: float | None = None
    discrepancy_pct: float | None = None
    is_coherent: bool = True
    status: DataStatus = DataStatus.OK
    status_explanation: str | None = None


@dataclass
class LevelsSnapshot:
    """Snapshot complet consolidé des niveaux gamma, base NQ et expected move."""

    timestamp_utc: datetime
    source_timestamp_utc: datetime | None
    data_age_minutes: float | None
    status: DataStatus
    spot_ndx: float
    spot_nq: float
    basis: float
    basis_label: str
    basis_status: DataStatus
    synthetic_basis: float | None
    net_gex: float
    regime: str  # "AMORTISSEUR (volatilité comprimée)" ou "AMPLIFICATEUR (volatilité accrue)"
    gamma_flip_ndx: float | None
    gamma_flip_nq: float | None
    call_wall_ndx: float | None
    call_wall_nq: float | None
    put_wall_ndx: float | None
    put_wall_nq: float | None
    top_walls_ndx: list[GammaWall] = field(default_factory=list)
    zero_dte_call_wall_ndx: float | None = None
    zero_dte_call_wall_nq: float | None = None
    zero_dte_put_wall_ndx: float | None = None
    zero_dte_put_wall_nq: float | None = None
    zero_dte_net_gex: float | None = None
    zero_dte_expiry: date | None = None
    expected_move: ExpectedMoveInfo | None = None
    max_pain_ndx: float | None = None
    max_pain_nq: float | None = None
    max_pain_expiry: date | None = None
    reference_session_date: date | None = None
    spot_nq_delay_note: str | None = None
    cboe_age_stats: dict[str, Any] = field(default_factory=dict)
    oi_flag: str = "OI de la veille"
    anomalies: list[str] = field(default_factory=list)
    diagnostic_1c: Diagnostic1cInfo | None = None
    basis_nq_time_utc: datetime | None = None
    basis_nq_close: float | None = None
    basis_ndx_time_utc: datetime | None = None
    basis_ndx_spot: float | None = None
    basis_delta_t_minutes: float | None = None
    basis_tolerance_minutes: float = 1.0
    basis_is_aligned: bool = True
    basis_method: str = "paire séance précédente"
    basis_formula: str = "base = NQ_close - NDX_spot"
    basis_delay_compensation_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Sérialisation en dictionnaire pour export JSON et persistance."""
        return {
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "source_timestamp_utc": (
                self.source_timestamp_utc.isoformat()
                if self.source_timestamp_utc
                else None
            ),
            "data_age_minutes": self.data_age_minutes,
            "status": self.status.value,
            "spot_ndx": self.spot_ndx,
            "spot_nq": self.spot_nq,
            "basis": self.basis,
            "basis_label": self.basis_label,
            "basis_status": self.basis_status.value,
            "synthetic_basis": self.synthetic_basis,
            "net_gex": self.net_gex,
            "regime": self.regime,
            "gamma_flip_ndx": self.gamma_flip_ndx,
            "gamma_flip_nq": self.gamma_flip_nq,
            "call_wall_ndx": self.call_wall_ndx,
            "call_wall_nq": self.call_wall_nq,
            "put_wall_ndx": self.put_wall_ndx,
            "put_wall_nq": self.put_wall_nq,
            "top_walls_ndx": [
                {
                    "strike": w.strike,
                    "nq_strike": w.nq_strike,
                    "gex": w.gex,
                    "type": w.type,
                    "rank": w.rank,
                    "expiry": w.expiry.isoformat() if w.expiry else None,
                }
                for w in self.top_walls_ndx
            ],
            "zero_dte": {
                "call_wall_ndx": self.zero_dte_call_wall_ndx,
                "call_wall_nq": self.zero_dte_call_wall_nq,
                "put_wall_ndx": self.zero_dte_put_wall_ndx,
                "put_wall_nq": self.zero_dte_put_wall_nq,
                "net_gex": self.zero_dte_net_gex,
                "expiry": self.zero_dte_expiry.isoformat() if self.zero_dte_expiry else None,
            },
            "expected_move": {
                "formula_move": (
                    self.expected_move.formula_move if self.expected_move else None
                ),
                "straddle_move": (
                    self.expected_move.straddle_move if self.expected_move else None
                ),
                "iv_atm": self.expected_move.iv_atm if self.expected_move else None,
                "days_to_expiry": (
                    self.expected_move.days_to_expiry if self.expected_move else None
                ),
                "expiry": (
                    self.expected_move.expiry.isoformat()
                    if self.expected_move and self.expected_move.expiry
                    else None
                ),
                "lower_bound_ndx": (
                    self.expected_move.lower_bound_ndx if self.expected_move else None
                ),
                "upper_bound_ndx": (
                    self.expected_move.upper_bound_ndx if self.expected_move else None
                ),
                "lower_bound_nq": (
                    self.expected_move.lower_bound_nq if self.expected_move else None
                ),
                "upper_bound_nq": (
                    self.expected_move.upper_bound_nq if self.expected_move else None
                ),
            },
            "max_pain_ndx": self.max_pain_ndx,
            "max_pain_nq": self.max_pain_nq,
            "max_pain_expiry": (
                self.max_pain_expiry.isoformat() if self.max_pain_expiry else None
            ),
            "reference_session_date": (
                self.reference_session_date.isoformat()
                if self.reference_session_date
                else None
            ),
            "spot_nq_delay_note": self.spot_nq_delay_note,
            "cboe_age_stats": self.cboe_age_stats,
            "oi_flag": self.oi_flag,
            "anomalies": self.anomalies,
        }
