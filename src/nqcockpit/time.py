"""Time and timezone utilities for NQ Cockpit.

Enforces:
- Market logic in America/New_York
- Display and trading windows in Africa/Algiers
- Exact DST transitions via Python standard zoneinfo (no hardcoded offsets)
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Sequence
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from nqcockpit.config import TradingWindowConfig

TZ_ALGIERS = ZoneInfo("Africa/Algiers")
TZ_NEW_YORK = ZoneInfo("America/New_York")
TZ_UTC = ZoneInfo("UTC")


def now_algiers() -> datetime:
    """Returns the current aware datetime in Africa/Algiers."""
    return datetime.now(TZ_ALGIERS)


def now_ny() -> datetime:
    """Returns the current aware datetime in America/New_York."""
    return datetime.now(TZ_NEW_YORK)


def parse_time_str(time_str: str) -> time:
    """Parses 'HH:MM' string into a datetime.time object."""
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected time string in 'HH:MM' format, got {time_str!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    return time(hour=hour, minute=minute)


def to_algiers(dt: datetime, assume_tz: ZoneInfo | None = None) -> datetime:
    """Converts a datetime to Africa/Algiers timezone.

    If dt is naive, it assumes `assume_tz` (defaults to America/New_York).
    """
    if dt.tzinfo is None:
        src_tz = assume_tz if assume_tz is not None else TZ_NEW_YORK
        dt = dt.replace(tzinfo=src_tz)
    return dt.astimezone(TZ_ALGIERS)


def to_ny(dt: datetime, assume_tz: ZoneInfo | None = None) -> datetime:
    """Converts a datetime to America/New_York timezone.

    If dt is naive, it assumes `assume_tz` (defaults to Africa/Algiers).
    """
    if dt.tzinfo is None:
        src_tz = assume_tz if assume_tz is not None else TZ_ALGIERS
        dt = dt.replace(tzinfo=src_tz)
    return dt.astimezone(TZ_NEW_YORK)


def convert_tz(
    dt: datetime,
    target_tz: str | ZoneInfo,
    source_tz: str | ZoneInfo | None = None,
) -> datetime:
    """Converts datetime to target timezone, attaching source_tz if naive."""
    target_zi = ZoneInfo(target_tz) if isinstance(target_tz, str) else target_tz
    if dt.tzinfo is None:
        if source_tz is None:
            raise ValueError("Naive datetime passed without source_tz")
        src_zi = ZoneInfo(source_tz) if isinstance(source_tz, str) else source_tz
        dt = dt.replace(tzinfo=src_zi)
    return dt.astimezone(target_zi)


def get_ny_algiers_offset_hours(dt: datetime | None = None) -> float:
    """Returns the difference in hours between Algiers and New York at datetime dt.

    Algiers offset minus New York offset.
    Before US DST change (EDT, UTC-4): +1 - (-4) = 5 hours.
    After US DST change (EST, UTC-5): +1 - (-5) = 6 hours.
    """
    if dt is None:
        dt = datetime.now(TZ_UTC)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)

    ny_dt = dt.astimezone(TZ_NEW_YORK)
    algiers_dt = dt.astimezone(TZ_ALGIERS)

    ny_offset = ny_dt.utcoffset()
    algiers_offset = algiers_dt.utcoffset()

    if ny_offset is None or algiers_offset is None:
        raise ValueError("Failed to compute timezone offset")

    diff_seconds = (algiers_offset - ny_offset).total_seconds()
    return diff_seconds / 3600.0


def next_algiers_time(time_str: str, base_dt: datetime | None = None) -> datetime:
    """Calculates the next occurrence of a time ('HH:MM') in Africa/Algiers.

    If base_dt is omitted, defaults to current time in Africa/Algiers.
    If the time today is already strictly passed, returns tomorrow at that time.
    """
    target_t = parse_time_str(time_str)

    if base_dt is None:
        ref_dt = now_algiers()
    elif base_dt.tzinfo is None:
        ref_dt = base_dt.replace(tzinfo=TZ_ALGIERS)
    else:
        ref_dt = base_dt.astimezone(TZ_ALGIERS)

    candidate = ref_dt.replace(
        hour=target_t.hour,
        minute=target_t.minute,
        second=0,
        microsecond=0,
    )

    if candidate <= ref_dt:
        candidate = candidate + timedelta(days=1)

    return candidate


def is_in_trading_window(
    dt: datetime,
    windows: Sequence[TradingWindowConfig | dict[str, str]] | None = None,
) -> tuple[bool, str | None]:
    """Tests if datetime falls within any trading window (evaluated in Algiers time).

    Default windows if none provided:
      - trade1: 15:30 -> 17:00
      - trade2: 17:00 -> 18:30

    Interval is half-open: [start, end) so boundary at 17:00 cleanly belongs to trade2.
    Returns (True, window_name) or (False, None).
    """
    algiers_dt = to_algiers(dt)
    cur_time = algiers_dt.time()

    if windows is None:
        active_windows: list[tuple[str, time, time]] = [
            ("trade1", time(15, 30), time(17, 0)),
            ("trade2", time(17, 0), time(18, 30)),
        ]
    else:
        active_windows = []
        for w in windows:
            if hasattr(w, "name"):
                name = getattr(w, "name")
                start_s = getattr(w, "start")
                end_s = getattr(w, "end")
            else:
                name = str(w["name"])
                start_s = str(w["start"])
                end_s = str(w["end"])
            active_windows.append((name, parse_time_str(start_s), parse_time_str(end_s)))

    for name, start_t, end_t in active_windows:
        if start_t <= cur_time < end_t:
            return True, name

    return False, None
