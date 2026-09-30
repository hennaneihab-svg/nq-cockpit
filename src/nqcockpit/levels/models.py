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
    nq_origin: str | None = None
    nq_bars_count_day: int = 0
    nq_first_bar_time: str | None = None
    nq_last_bar_time: str | None = None
    # NDX candidate
    ndx_candidate_found: bool = False
    ndx_candidate_time_et: str | None = None
    ndx_candidate_time_algiers: str | None = None
    ndx_candidate_spot: float | None = None
    ndx_origin: str | None = None
    # Search steps
    search_steps_summary: list[str] = field(default_factory=list)
    # Timing
    delta_t_minutes: float | None = None
    tolerance_minutes: float = 1.0
    # Cause & Action
    cause_code: str = "AUTRE"
    cause_detail: str = ""
    action_taken: str = ""


@dataclass
class StraddleLegInfo:
    """Détail d'une jambe (Call ou Put) du straddle ATM."""

    option_type: str  # "C" ou "P"
    root: str  # ex: "NDXP" ou "NDX"
    expiry: date
    strike: float
    bid: float
    ask: float
    mid: float
    spread_rel_pct: float  # (ask - bid) / mid * 100
    iv: float
    volume: float
    quote_time_et: str | None
    quote_time_algiers: str | None
    is_spread_wide: bool = False
    quote_time_utc: datetime | None = None
    age_minutes: float | None = None
    delta_t_vs_spot_nq_minutes: float | None = None


@dataclass
class StraddleStrikeNeighbor:
    """Cotation et straddle pour un strike voisin."""

    strike: float
    call_mid: float
    put_mid: float
    straddle_mid: float


@dataclass
class StraddleDiagnostic:
    """Diagnostic exhaustif du straddle ATM pour élucider l'écart avec la formule IV."""

    spot_ndx_used: float
    atm_strike: float
    call_leg: StraddleLegInfo
    put_leg: StraddleLegInfo
    roots_match: bool
    expiries_match: bool
    straddle_points: float  # C_mid + P_mid en points d'indice purs
    implied_iv_straddle: float  # straddle / (0.8 * spot * sqrt(T)) avec T = heures / (365 * 24)
    iv_atm_used: float
    spread_pct_vs_iv: float  # écart relatif à unités égales 0.8σ
    time_to_expiry_hours: float = 0.0
    time_to_expiry_years: float = 0.0
    formula_move_1sigma: float = 0.0
    straddle_move_1sigma_equiv: float = 0.0
    straddle_theo_from_iv: float = 0.0
    calculated_cause: str = ""
    neighbors: list[StraddleStrikeNeighbor] = field(default_factory=list)
    is_degraded: bool = False
    degraded_reason: str = ""
    delta_t_call_vs_spot_nq_minutes: float | None = None
    delta_t_put_vs_spot_nq_minutes: float | None = None


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
    spot_ndx_used: float = 0.0
    spot_nq_observed: float = 0.0
    spot_nq_converted: float = 0.0
    spread_nq_vs_converted: float = 0.0
    straddle_diagnostic: StraddleDiagnostic | None = None
    time_to_expiry_hours: float | None = None
    time_to_expiry_years: float | None = None


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

    # Murs utiles (dans fenêtre ±10 %) et globaux (Tâche 3)
    call_wall_useful_ndx: float | None = None
    call_wall_useful_nq: float | None = None
    call_wall_useful_dist_pts: float | None = None
    call_wall_useful_dist_pct: float | None = None
    call_wall_global_ndx: float | None = None
    call_wall_global_nq: float | None = None
    call_wall_global_dist_pts: float | None = None
    call_wall_global_dist_pct: float | None = None
    call_wall_is_outside_window: bool = False

    put_wall_useful_ndx: float | None = None
    put_wall_useful_nq: float | None = None
    put_wall_useful_dist_pts: float | None = None
    put_wall_useful_dist_pct: float | None = None
    put_wall_global_ndx: float | None = None
    put_wall_global_nq: float | None = None
    put_wall_global_dist_pts: float | None = None
    put_wall_global_dist_pct: float | None = None
    put_wall_is_outside_window: bool = False
    wall_window_pct: float = 0.03

    # Spot NQ : Fraîcheur réelle (Tâche 1)
    spot_nq_time_utc: datetime | None = None
    spot_nq_age_minutes: float | None = None
    spot_nq_is_stale: bool = False

    # CBOE métadonnées de rechargement (Tâche 2 / 3)
    cboe_request_time_utc: datetime | None = None
    cboe_http_status: int | None = None
    cboe_duration_ms: float | None = None
    cboe_internal_timestamp_utc: datetime | None = None
    cboe_reloaded: bool = True
    cboe_chain_age_minutes: float | None = None
    cboe_active_quote_delay_minutes: float | None = None

    # Base live et comparatif des 3 bases (Tâche 2)
    live_basis_value: float | None = None
    live_basis_nq_time_utc: datetime | None = None
    live_basis_ndx_time_utc: datetime | None = None
    live_basis_delta_t_minutes: float | None = None
    live_basis_status: DataStatus = DataStatus.DEGRADED
    live_basis_available: bool = False
    live_basis_unavailable_reason: str | None = None
    spread_live_vs_prev_basis: float | None = None
    spread_live_vs_parity_basis: float | None = None
    spread_prev_vs_parity_basis: float | None = None

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
                "spot_ndx_used": (
                    self.expected_move.spot_ndx_used if self.expected_move else 0.0
                ),
                "spot_nq_observed": (
                    self.expected_move.spot_nq_observed if self.expected_move else 0.0
                ),
                "spot_nq_converted": (
                    self.expected_move.spot_nq_converted if self.expected_move else 0.0
                ),
                "spread_nq_vs_converted": (
                    self.expected_move.spread_nq_vs_converted if self.expected_move else 0.0
                ),
                "straddle_diagnostic": (
                    {
                        "spot_ndx_used": self.expected_move.straddle_diagnostic.spot_ndx_used,
                        "atm_strike": self.expected_move.straddle_diagnostic.atm_strike,
                        "roots_match": self.expected_move.straddle_diagnostic.roots_match,
                        "expiries_match": self.expected_move.straddle_diagnostic.expiries_match,
                        "straddle_points": (
                            self.expected_move.straddle_diagnostic.straddle_points
                        ),
                        "implied_iv_straddle": (
                            self.expected_move.straddle_diagnostic.implied_iv_straddle
                        ),
                        "iv_atm_used": self.expected_move.straddle_diagnostic.iv_atm_used,
                        "spread_pct_vs_iv": (
                            self.expected_move.straddle_diagnostic.spread_pct_vs_iv
                        ),
                        "time_to_expiry_hours": (
                            self.expected_move.straddle_diagnostic.time_to_expiry_hours
                        ),
                        "time_to_expiry_years": (
                            self.expected_move.straddle_diagnostic.time_to_expiry_years
                        ),
                        "formula_move_1sigma": (
                            self.expected_move.straddle_diagnostic.formula_move_1sigma
                        ),
                        "straddle_move_1sigma_equiv": (
                            self.expected_move.straddle_diagnostic.straddle_move_1sigma_equiv
                        ),
                        "straddle_theo_from_iv": (
                            self.expected_move.straddle_diagnostic.straddle_theo_from_iv
                        ),
                        "calculated_cause": (
                            self.expected_move.straddle_diagnostic.calculated_cause
                        ),
                        "is_degraded": self.expected_move.straddle_diagnostic.is_degraded,
                        "degraded_reason": (
                            self.expected_move.straddle_diagnostic.degraded_reason
                        ),
                        "call_leg": {
                            "root": self.expected_move.straddle_diagnostic.call_leg.root,
                            "bid": self.expected_move.straddle_diagnostic.call_leg.bid,
                            "ask": self.expected_move.straddle_diagnostic.call_leg.ask,
                            "mid": self.expected_move.straddle_diagnostic.call_leg.mid,
                            "spread_rel_pct": (
                                self.expected_move.straddle_diagnostic.call_leg.spread_rel_pct
                            ),
                            "iv": self.expected_move.straddle_diagnostic.call_leg.iv,
                            "volume": self.expected_move.straddle_diagnostic.call_leg.volume,
                            "quote_time_et": (
                                self.expected_move.straddle_diagnostic.call_leg.quote_time_et
                            ),
                            "quote_time_algiers": (
                                self.expected_move.straddle_diagnostic.call_leg.quote_time_algiers
                            ),
                            "age_minutes": (
                                self.expected_move.straddle_diagnostic.call_leg.age_minutes
                            ),
                            "delta_t_vs_spot_nq_minutes": (
                                self.expected_move.straddle_diagnostic.call_leg.delta_t_vs_spot_nq_minutes
                            ),
                        },
                        "put_leg": {
                            "root": self.expected_move.straddle_diagnostic.put_leg.root,
                            "bid": self.expected_move.straddle_diagnostic.put_leg.bid,
                            "ask": self.expected_move.straddle_diagnostic.put_leg.ask,
                            "mid": self.expected_move.straddle_diagnostic.put_leg.mid,
                            "spread_rel_pct": (
                                self.expected_move.straddle_diagnostic.put_leg.spread_rel_pct
                            ),
                            "iv": self.expected_move.straddle_diagnostic.put_leg.iv,
                            "volume": self.expected_move.straddle_diagnostic.put_leg.volume,
                            "quote_time_et": (
                                self.expected_move.straddle_diagnostic.put_leg.quote_time_et
                            ),
                            "quote_time_algiers": (
                                self.expected_move.straddle_diagnostic.put_leg.quote_time_algiers
                            ),
                            "age_minutes": (
                                self.expected_move.straddle_diagnostic.put_leg.age_minutes
                            ),
                            "delta_t_vs_spot_nq_minutes": (
                                self.expected_move.straddle_diagnostic.put_leg.delta_t_vs_spot_nq_minutes
                            ),
                        },
                        "neighbors": [
                            {
                                "strike": n.strike,
                                "call_mid": n.call_mid,
                                "put_mid": n.put_mid,
                                "straddle_mid": n.straddle_mid,
                            }
                            for n in self.expected_move.straddle_diagnostic.neighbors
                        ],
                    }
                    if self.expected_move and self.expected_move.straddle_diagnostic
                    else None
                ),
            },
            "call_wall_useful_ndx": self.call_wall_useful_ndx,
            "call_wall_useful_nq": self.call_wall_useful_nq,
            "call_wall_useful_dist_pts": self.call_wall_useful_dist_pts,
            "call_wall_useful_dist_pct": self.call_wall_useful_dist_pct,
            "call_wall_global_ndx": self.call_wall_global_ndx,
            "call_wall_global_nq": self.call_wall_global_nq,
            "call_wall_is_outside_window": self.call_wall_is_outside_window,
            "put_wall_useful_ndx": self.put_wall_useful_ndx,
            "put_wall_useful_nq": self.put_wall_useful_nq,
            "put_wall_useful_dist_pts": self.put_wall_useful_dist_pts,
            "put_wall_useful_dist_pct": self.put_wall_useful_dist_pct,
            "put_wall_global_ndx": self.put_wall_global_ndx,
            "put_wall_global_nq": self.put_wall_global_nq,
            "put_wall_is_outside_window": self.put_wall_is_outside_window,
            "spot_nq_age_minutes": self.spot_nq_age_minutes,
            "spot_nq_is_stale": self.spot_nq_is_stale,
            "cboe_reloaded": self.cboe_reloaded,
            "cboe_http_status": self.cboe_http_status,
            "cboe_duration_ms": self.cboe_duration_ms,
            "cboe_chain_age_minutes": self.cboe_chain_age_minutes,
            "cboe_active_quote_delay_minutes": self.cboe_active_quote_delay_minutes,
            "live_basis": {
                "value": self.live_basis_value,
                "available": self.live_basis_available,
                "delta_t_minutes": self.live_basis_delta_t_minutes,
                "status": self.live_basis_status.value,
                "unavailable_reason": self.live_basis_unavailable_reason,
                "spread_vs_prev": self.spread_live_vs_prev_basis,
                "spread_vs_parity": self.spread_live_vs_parity_basis,
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
