"""Pure computation helpers for the Coaching page.

Every function here is deterministic and side-effect free. It reads only the
fields that already exist on ``TradeEntry`` — no new database columns and no
migration. Statistics are always accompanied by their sample size so the UI can
flag low-sample segments instead of inventing significance.

Numbers are expressed in R (the initial stop distance of a trade). No money /
account-currency field exists in the journal schema, so these helpers never
synthesize a dollar value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from nqcockpit.config import AppConfig
from nqcockpit.journal.engine import (
    detect_violations,
    segment_performance,
)
from nqcockpit.journal.models import PerformanceStats, TradeEntry, TradeOutcome

# NY session hours shown on the heatmap (America/New_York), Monday..Friday.
NY_HOURS: list[int] = list(range(9, 17))  # 09:00 .. 16:00 ET
WEEKDAY_LABELS: list[str] = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# Minimum number of trades before a segment or cell is treated as reliable.
MIN_SEGMENT_SAMPLES: int = 12

# A time-of-day cell holds far fewer trades than a whole setup segment, so a
# lower bar is used to decide whether its colour is shown (vs muted).
HEATMAP_MIN_CELL_SAMPLES: int = 5


def trade_timestamp(trade: TradeEntry) -> datetime:
    """Best chronological anchor for a trade (entry time in NY, else recorded)."""
    return trade.entry_time_ny or trade.recorded_at


def sort_trades_chronologically(trades: list[TradeEntry]) -> list[TradeEntry]:
    """Stable chronological ordering, ignoring any caller-provided order."""
    return sorted(trades, key=lambda t: (trade_timestamp(t), t.trade_id))


# ---------------------------------------------------------------------------
# Drawdown series (cumulative R with underwater drawdown)
# ---------------------------------------------------------------------------


@dataclass
class DrawdownPoint:
    """One point on the equity curve: cumulative R and underwater drawdown."""

    trade_id: str
    timestamp: datetime
    session_date: str
    r: float
    cum_r: float
    peak_r: float
    underwater_r: float  # peak - cum, always >= 0


def compute_drawdown_series(trades: list[TradeEntry]) -> list[DrawdownPoint]:
    """Cumulative R and underwater drawdown for each trade, chronologically.

    The first point is always at time zero (peak == cumulative). Drawdown is
    measured from the running peak, so ``underwater_r`` is zero while at new
    highs and grows as the curve falls below its peak.
    """
    points: list[DrawdownPoint] = []
    cum = 0.0
    peak = 0.0
    for trade in sort_trades_chronologically(trades):
        cum += trade.r_realized
        if cum > peak:
            peak = cum
        points.append(
            DrawdownPoint(
                trade_id=trade.trade_id,
                timestamp=trade_timestamp(trade),
                session_date=trade.session_date,
                r=trade.r_realized,
                cum_r=round(cum, 4),
                peak_r=round(peak, 4),
                underwater_r=round(peak - cum, 4),
            )
        )
    return points


def compute_max_drawdown(trades: list[TradeEntry]) -> tuple[float, int]:
    """Return ``(max_drawdown_r, trough_index)`` for a trade list.

    ``trough_index`` is the position (in ``compute_drawdown_series`` order) of
    the deepest point, or ``-1`` when there are no trades.
    """
    points = compute_drawdown_series(trades)
    if not points:
        return 0.0, -1
    max_dd = 0.0
    trough_index = -1
    for index, point in enumerate(points):
        if point.underwater_r > max_dd:
            max_dd = point.underwater_r
            trough_index = index
    return round(max_dd, 4), trough_index


def current_loss_streak(trades: list[TradeEntry]) -> int:
    """Number of consecutive losses ending at the most recent trade."""
    streak = 0
    for trade in reversed(sort_trades_chronologically(trades)):
        if trade.outcome == TradeOutcome.LOSS:
            streak += 1
        else:
            break
    return streak


# ---------------------------------------------------------------------------
# Hour x weekday heatmap
# ---------------------------------------------------------------------------


@dataclass
class HeatmapCell:
    """Aggregated outcome for one (hour, weekday) bucket."""

    hour: int
    weekday: int  # Monday=0 .. Friday=4
    n: int = 0
    total_r: float = 0.0
    wins: int = 0
    losses: int = 0

    @property
    def expectancy_r(self) -> float:
        """Mean R for the bucket (0.0 when empty)."""
        return self.total_r / self.n if self.n else 0.0


def aggregate_heatmap(trades: list[TradeEntry]) -> dict[tuple[int, int], HeatmapCell]:
    """Bucket trades by (hour, weekday) using the NY entry time when available.

    Trades without a usable weekday (e.g. weekend timestamps) are ignored rather
    than invented.
    """
    cells: dict[tuple[int, int], HeatmapCell] = {}
    for trade in trades:
        timestamp = trade_timestamp(trade)
        weekday = timestamp.weekday()
        if weekday not in range(5):  # Saturday/Sunday are outside the session
            continue
        hour = timestamp.hour
        cell = cells.setdefault((hour, weekday), HeatmapCell(hour=hour, weekday=weekday))
        cell.n += 1
        cell.total_r += trade.r_realized
        if trade.outcome == TradeOutcome.WIN:
            cell.wins += 1
        elif trade.outcome == TradeOutcome.LOSS:
            cell.losses += 1
    return cells


def heatmap_grid(
    trades: list[TradeEntry],
) -> tuple[list[int], list[list[float]], list[list[int]], list[list[float]]]:
    """Return ``(hours, z_expectancy, z_count, z_total_r)`` matrices.

    ``z_expectancy`` / ``z_total_r`` are indexed ``[weekday][hour_index]`` and
    match ``NY_HOURS``; ``z_count`` holds the trade count per cell.
    """
    cells = aggregate_heatmap(trades)
    hours = list(NY_HOURS)
    z_expectancy: list[list[float]] = []
    z_count: list[list[int]] = []
    z_total: list[list[float]] = []
    for weekday in range(5):  # Monday..Friday
        exp_row: list[float] = []
        n_row: list[int] = []
        total_row: list[float] = []
        for hour in hours:
            cell = cells.get((hour, weekday))
            if cell is None:
                exp_row.append(0.0)
                n_row.append(0)
                total_row.append(0.0)
            else:
                exp_row.append(round(cell.expectancy_r, 3))
                n_row.append(cell.n)
                total_row.append(round(cell.total_r, 3))
        z_expectancy.append(exp_row)
        z_count.append(n_row)
        z_total.append(total_row)
    return hours, z_expectancy, z_count, z_total


# ---------------------------------------------------------------------------
# Segment table
# ---------------------------------------------------------------------------


@dataclass
class SegmentRow:
    """One row of the setup / regime table."""

    label: str
    n: int
    win_rate: float | None
    expectancy_r: float
    profit_factor: float | None
    avg_win_r: float | None
    avg_loss_r: float | None
    low_sample: bool


def segment_table_rows(
    segments: dict[str, PerformanceStats],
    min_samples: int = MIN_SEGMENT_SAMPLES,
) -> list[SegmentRow]:
    """Flatten ``segment_performance`` output into display rows, n-descending.

    Expectancy falls back to the empirical mean (``raw_mean_r``) when the sample
    is below the significance threshold. ``low_sample`` is set when ``n`` is
    below ``min_samples`` so the UI can mute the row.
    """
    rows: list[SegmentRow] = []
    for label, stats in segments.items():
        expectancy = (
            stats.expectancy_r
            if stats.expectancy_r is not None
            else (stats.raw_mean_r or 0.0)
        )
        rows.append(
            SegmentRow(
                label=label,
                n=stats.n_trades,
                win_rate=stats.win_rate,
                expectancy_r=expectancy,
                profit_factor=stats.profit_factor,
                avg_win_r=stats.avg_win_r,
                avg_loss_r=stats.avg_loss_r,
                low_sample=stats.n_trades < min_samples,
            )
        )
    rows.sort(key=lambda row: (-row.n, -(row.expectancy_r or 0.0)))
    return rows


# ---------------------------------------------------------------------------
# Cost of breaking rules
# ---------------------------------------------------------------------------


def classify_compliance(
    trades: list[TradeEntry],
    config: AppConfig | None,
) -> tuple[list[TradeEntry], list[TradeEntry]]:
    """Split trades into ``(compliant, non_compliant)`` using the engine rules.

    Mirrors ``compute_performance_stats``: a trade is non-compliant when
    ``detect_violations`` returns at least one flag for its session.
    """
    violated_ids: set[str] = set()
    if config is None:
        for trade in trades:
            if trade.sl_moved or trade.early_exit:
                violated_ids.add(trade.trade_id)
    else:
        by_session: dict[str, list[TradeEntry]] = {}
        for trade in trades:
            by_session.setdefault(trade.session_date, []).append(trade)
        for session_trades in by_session.values():
            for trade in session_trades:
                if detect_violations(trade, session_trades, config):
                    violated_ids.add(trade.trade_id)

    compliant = [t for t in trades if t.trade_id not in violated_ids]
    non_compliant = [t for t in trades if t.trade_id in violated_ids]
    return compliant, non_compliant


def _mean_r(trades: list[TradeEntry]) -> float | None:
    if not trades:
        return None
    return sum(t.r_realized for t in trades) / len(trades)


@dataclass
class RuleBreakCost:
    """Compliance economics: how much breaking the rules costs in R."""

    n_compliant: int = 0
    n_noncompliant: int = 0
    expectancy_compliant: float | None = None
    expectancy_noncompliant: float | None = None
    gap_per_trade_r: float | None = None  # compliant - non-compliant
    total_r_noncompliant: float = 0.0
    n_sl_moved: int = 0
    sl_moved_avg_r: float | None = None
    no_sl_moved_avg_r: float | None = None
    n_early_exit: int = 0
    early_exit_avg_r: float | None = None
    no_early_exit_avg_r: float | None = None


def compute_rule_break_cost(
    trades: list[TradeEntry],
    config: AppConfig | None = None,
) -> RuleBreakCost:
    """Compute compliant vs non-compliant expectancy and sl/exit effects.

    All means are descriptive; the caller decides whether the sample is large
    enough to state a conclusion.
    """
    compliant, non_compliant = classify_compliance(trades, config)
    exp_compliant = _mean_r(compliant)
    exp_noncompliant = _mean_r(non_compliant)
    gap: float | None = None
    if exp_compliant is not None and exp_noncompliant is not None:
        gap = exp_compliant - exp_noncompliant

    sl_moved = [t for t in trades if t.sl_moved]
    no_sl = [t for t in trades if not t.sl_moved]
    early_exit = [t for t in trades if t.early_exit]
    no_early = [t for t in trades if not t.early_exit]

    return RuleBreakCost(
        n_compliant=len(compliant),
        n_noncompliant=len(non_compliant),
        expectancy_compliant=exp_compliant,
        expectancy_noncompliant=exp_noncompliant,
        gap_per_trade_r=round(gap, 4) if gap is not None else None,
        total_r_noncompliant=round(sum(t.r_realized for t in non_compliant), 4),
        n_sl_moved=len(sl_moved),
        sl_moved_avg_r=_mean_r(sl_moved),
        no_sl_moved_avg_r=_mean_r(no_sl),
        n_early_exit=len(early_exit),
        early_exit_avg_r=_mean_r(early_exit),
        no_early_exit_avg_r=_mean_r(no_early),
    )


# ---------------------------------------------------------------------------
# Loss streaks
# ---------------------------------------------------------------------------


@dataclass
class StreakSegment:
    """A run of consecutive losses (length >= 2)."""

    start_ts: datetime
    end_ts: datetime
    length: int
    total_r: float


def compute_loss_streaks(trades: list[TradeEntry]) -> list[StreakSegment]:
    """Detect consecutive-loss runs (length >= 2) chronologically."""
    streaks: list[StreakSegment] = []
    current: list[TradeEntry] = []
    for trade in sort_trades_chronologically(trades):
        if trade.outcome == TradeOutcome.LOSS:
            current.append(trade)
        else:
            if len(current) >= 2:
                streaks.append(_streak_from(current))
            current = []
    if len(current) >= 2:
        streaks.append(_streak_from(current))
    return streaks


def _streak_from(trades: list[TradeEntry]) -> StreakSegment:
    return StreakSegment(
        start_ts=trade_timestamp(trades[0]),
        end_ts=trade_timestamp(trades[-1]),
        length=len(trades),
        total_r=round(sum(t.r_realized for t in trades), 4),
    )


# ---------------------------------------------------------------------------
# Insights (data-driven, plain and non-directional)
# ---------------------------------------------------------------------------


@dataclass
class Insight:
    """A single data-driven finding with a confidence tag from sample size."""

    kind: str
    value: float = 0.0
    n: int = 0
    label: str = ""
    confidence: str = "low"  # "high" | "medium" | "low"
    hour: int | None = None
    weekday: int | None = None
    extra: dict[str, float] = field(default_factory=dict)


def _confidence_for(n: int, min_samples: int, min_sessions: int) -> str:
    if n >= min_sessions:
        return "high"
    if n >= min_samples:
        return "medium"
    return "low"


def _segment_expectancy(stats: PerformanceStats) -> float:
    if stats.expectancy_r is not None:
        return stats.expectancy_r
    return stats.raw_mean_r or 0.0


def _best_worst_segment(
    segments: dict[str, PerformanceStats],
) -> tuple[tuple[str, PerformanceStats] | None, tuple[str, PerformanceStats] | None]:
    if not segments:
        return None, None
    best = max(segments.items(), key=lambda kv: _segment_expectancy(kv[1]))
    worst = min(segments.items(), key=lambda kv: _segment_expectancy(kv[1]))
    return best, worst


def _hour_insight(
    cells: dict[tuple[int, int], HeatmapCell],
    want_best: bool,
) -> Insight | None:
    qualified = {
        key: cell for key, cell in cells.items() if cell.n >= HEATMAP_MIN_CELL_SAMPLES
    }
    if not qualified:
        return None
    key = (
        max(qualified, key=lambda k: qualified[k].expectancy_r)
        if want_best
        else min(qualified, key=lambda k: qualified[k].expectancy_r)
    )
    cell = qualified[key]
    return Insight(
        kind="best_hour" if want_best else "worst_hour",
        value=round(cell.expectancy_r, 3),
        n=cell.n,
        hour=cell.hour,
        weekday=cell.weekday,
        confidence="low",
    )


def compute_insights(
    trades: list[TradeEntry],
    config: AppConfig | None = None,
    min_samples: int = MIN_SEGMENT_SAMPLES,
    min_sessions: int = 60,
) -> list[Insight]:
    """Compute up to five data-driven findings, ordered by usefulness.

    Returns an empty list when there are no trades. Each insight carries its
    supporting number, its sample size and a confidence tag; the UI renders the
    plain-language wording.
    """
    if not trades:
        return []

    setup_segments = segment_performance(trades, by="setup_tag", min_samples=min_samples)
    gamma_segments = segment_performance(
        trades, by="gamma_regime", min_samples=min_samples
    )
    vol_segments = segment_performance(trades, by="vol_regime", min_samples=min_samples)
    event_segments = segment_performance(trades, by="event_risk", min_samples=min_samples)
    cells = aggregate_heatmap(trades)
    rule_break = compute_rule_break_cost(trades, config)

    candidates: list[Insight | None] = []

    best, worst = _best_worst_segment(setup_segments)
    if best is not None:
        label, seg = best
        candidates.append(
            Insight(
                kind="best_setup",
                value=round(_segment_expectancy(seg), 3),
                n=seg.n_trades,
                label=label,
                confidence=_confidence_for(seg.n_trades, min_samples, min_sessions),
            )
        )
    if worst is not None:
        label, seg = worst
        candidates.append(
            Insight(
                kind="worst_setup",
                value=round(_segment_expectancy(seg), 3),
                n=seg.n_trades,
                label=label,
                confidence=_confidence_for(seg.n_trades, min_samples, min_sessions),
            )
        )

    if rule_break.n_noncompliant > 0 and rule_break.gap_per_trade_r is not None:
        candidates.append(
            Insight(
                kind="rule_break",
                value=round(rule_break.gap_per_trade_r, 3),
                n=rule_break.n_noncompliant,
                confidence=_confidence_for(
                    rule_break.n_noncompliant, min_samples, min_sessions
                ),
                extra={
                    "total_r": rule_break.total_r_noncompliant,
                    "compliant_exp": rule_break.expectancy_compliant or 0.0,
                    "noncompliant_exp": rule_break.expectancy_noncompliant or 0.0,
                },
            )
        )

    # Most negative regime across gamma / vol / event segments.
    negative_regime: Insight | None = None
    for kind, segments in (
        ("gamma_regime", gamma_segments),
        ("vol_regime", vol_segments),
        ("event_risk", event_segments),
    ):
        for label, seg in segments.items():
            exp = _segment_expectancy(seg)
            if exp < 0:
                candidate = Insight(
                    kind=kind,
                    value=round(exp, 3),
                    n=seg.n_trades,
                    label=label,
                    confidence=_confidence_for(
                        seg.n_trades, min_samples, min_sessions
                    ),
                )
                if negative_regime is None or candidate.value < negative_regime.value:
                    negative_regime = candidate
    if negative_regime is not None:
        candidates.append(negative_regime)

    candidates.append(_hour_insight(cells, want_best=True))

    return [c for c in candidates if c is not None][:5]
