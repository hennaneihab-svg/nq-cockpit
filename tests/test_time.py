"""Tests for time and timezone utilities with rigorous DST testing."""

from datetime import datetime

from nqcockpit.time import (
    TZ_ALGIERS,
    TZ_NEW_YORK,
    get_ny_algiers_offset_hours,
    is_in_trading_window,
    next_algiers_time,
    to_algiers,
    to_ny,
)


def test_timezone_conversions():
    """Verify basic timezone conversion between America/New_York and Africa/Algiers."""
    dt_ny = datetime(2026, 6, 15, 9, 30, tzinfo=TZ_NEW_YORK)
    dt_algiers = to_algiers(dt_ny)

    assert dt_algiers.tzinfo == TZ_ALGIERS
    # In June (EDT), NY is UTC-4 and Algiers is UTC+1 (difference of 5 hours)
    assert dt_algiers.hour == 14
    assert dt_algiers.minute == 30

    back_to_ny = to_ny(dt_algiers)
    assert back_to_ny == dt_ny


def test_next_algiers_time_same_day():
    """Verify next_algiers_time for a target time later on the same day."""
    base = datetime(2026, 9, 29, 10, 0, tzinfo=TZ_ALGIERS)
    next_time = next_algiers_time("15:30", base_dt=base)

    assert next_time.tzinfo == TZ_ALGIERS
    assert next_time.year == 2026
    assert next_time.month == 9
    assert next_time.day == 29
    assert next_time.hour == 15
    assert next_time.minute == 30


def test_next_algiers_time_next_day():
    """Verify next_algiers_time for a target time that has already passed today."""
    base = datetime(2026, 9, 29, 16, 0, tzinfo=TZ_ALGIERS)
    next_time = next_algiers_time("15:30", base_dt=base)

    assert next_time.tzinfo == TZ_ALGIERS
    assert next_time.year == 2026
    assert next_time.month == 9
    assert next_time.day == 30
    assert next_time.hour == 15
    assert next_time.minute == 30


def test_is_in_trading_window():
    """Verify trading window detection for default kill zones."""
    # trade1: 15:30 - 17:00
    # trade2: 17:00 - 18:30

    # Before window: 14:45
    t_before = datetime(2026, 9, 29, 14, 45, tzinfo=TZ_ALGIERS)
    in_win, name = is_in_trading_window(t_before)
    assert in_win is False
    assert name is None

    # Exact start of trade1: 15:30
    t_trade1_start = datetime(2026, 9, 29, 15, 30, tzinfo=TZ_ALGIERS)
    in_win, name = is_in_trading_window(t_trade1_start)
    assert in_win is True
    assert name == "trade1"

    # Middle of trade1: 16:15
    t_trade1_mid = datetime(2026, 9, 29, 16, 15, tzinfo=TZ_ALGIERS)
    in_win, name = is_in_trading_window(t_trade1_mid)
    assert in_win is True
    assert name == "trade1"

    # Exact boundary / start of trade2: 17:00
    t_trade2_start = datetime(2026, 9, 29, 17, 0, tzinfo=TZ_ALGIERS)
    in_win, name = is_in_trading_window(t_trade2_start)
    assert in_win is True
    assert name == "trade2"

    # End boundary of trade2: 18:30 (half-open, should be outside)
    t_trade2_end = datetime(2026, 9, 29, 18, 30, tzinfo=TZ_ALGIERS)
    in_win, name = is_in_trading_window(t_trade2_end)
    assert in_win is False
    assert name is None


def test_us_dst_transition_november_2026():
    """Rigorous verification of the US Daylight Saving Time switch on November 1st, 2026.

    Before Nov 1, 2026: America/New_York is EDT (UTC-4). Algiers is UTC+1.
      Offset difference = +1 - (-4) = 5 hours.
      09:30 ET (US Open) = 14:30 Algiers.
      08:30 ET (Macro data) = 13:30 Algiers.
      14:00 ET (FOMC) = 19:00 Algiers.

    After Nov 1, 2026 02:00: America/New_York falls back to EST (UTC-5). Algiers stays UTC+1.
      Offset difference = +1 - (-5) = 6 hours.
      09:30 ET (US Open) = 15:30 Algiers! (Matches the exact start of trade1!)
      08:30 ET (Macro data) = 14:30 Algiers.
      14:00 ET (FOMC) = 20:00 Algiers.
    """
    # 1. Saturday, October 31, 2026 (Before switch - EDT: 2026-10-31)
    dt_oct31_ny = datetime(2026, 10, 31, 9, 30, tzinfo=TZ_NEW_YORK)
    dt_oct31_algiers = to_algiers(dt_oct31_ny)

    assert dt_oct31_ny.strftime("%Y-%m-%d") == "2026-10-31"
    assert dt_oct31_ny.tzname() == "EDT"
    assert get_ny_algiers_offset_hours(dt_oct31_ny) == 5.0
    assert dt_oct31_algiers.hour == 14
    assert dt_oct31_algiers.minute == 30

    # Before switch, 09:30 ET (14:30 Algiers) is NOT in trading window
    in_win, _ = is_in_trading_window(dt_oct31_algiers)
    assert in_win is False

    # 2. Sunday, November 1, 2026 (DST transition day: 2026-11-01)
    dt_nov01_switch = datetime(2026, 11, 1, 12, 0, tzinfo=TZ_NEW_YORK)
    assert dt_nov01_switch.strftime("%Y-%m-%d") == "2026-11-01"
    assert dt_nov01_switch.tzname() == "EST"

    # 3. Check macro release at 08:30 ET before switch -> 13:30 Algiers
    macro_before = datetime(2026, 10, 31, 8, 30, tzinfo=TZ_NEW_YORK)
    assert to_algiers(macro_before).hour == 13
    assert to_algiers(macro_before).minute == 30

    # 4. Monday, November 2, 2026 (After switch - EST: 2026-11-02)
    dt_nov02_ny = datetime(2026, 11, 2, 9, 30, tzinfo=TZ_NEW_YORK)
    dt_nov02_algiers = to_algiers(dt_nov02_ny)

    assert dt_nov02_ny.strftime("%Y-%m-%d") == "2026-11-02"
    assert dt_nov02_ny.tzname() == "EST"
    assert get_ny_algiers_offset_hours(dt_nov02_ny) == 6.0
    assert dt_nov02_algiers.hour == 15
    assert dt_nov02_algiers.minute == 30

    # After switch, 09:30 ET (15:30 Algiers) coincides EXACTLY with trade1 start!
    in_win, win_name = is_in_trading_window(dt_nov02_algiers)
    assert in_win is True
    assert win_name == "trade1"

    # 4. Check macro release at 08:30 ET after switch -> 14:30 Algiers
    macro_after = datetime(2026, 11, 2, 8, 30, tzinfo=TZ_NEW_YORK)
    assert to_algiers(macro_after).hour == 14
    assert to_algiers(macro_after).minute == 30

    # 5. Check FOMC release at 14:00 ET after switch -> 20:00 Algiers
    fomc_after = datetime(2026, 11, 2, 14, 0, tzinfo=TZ_NEW_YORK)
    assert to_algiers(fomc_after).hour == 20
    assert to_algiers(fomc_after).minute == 0
