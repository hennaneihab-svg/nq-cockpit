"""Configuration loading and validation for NQ Cockpit."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class ConfigError(ValueError):
    """Raised when configuration file is missing, malformed, or invalid."""


@dataclass(frozen=True)
class TimezoneConfig:
    display: str = "Africa/Algiers"
    market: str = "America/New_York"


@dataclass(frozen=True)
class TradingWindowConfig:
    name: str
    start: str
    end: str


@dataclass(frozen=True)
class RulesConfig:
    max_trades_per_day: int = 2
    cancel_trade2_if_trade1_loss: bool = True
    cooldown_after_sl_minutes: int = 15
    daily_loss_limit_r: float = 2.0


@dataclass(frozen=True)
class RiskConfig:
    instrument: str = "MNQ"
    risk_per_trade_pct: float = 0.5
    account_size: float = 0.0
    prop_profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventsConfig:
    post_event_buffer_minutes: int = 90
    stand_aside_before_minutes: int = 5
    wait_after_minutes: int = 3
    tier1: list[str] = field(default_factory=list)
    tier2: list[str] = field(default_factory=list)
    megacaps: list[str] = field(default_factory=list)
    horizon_days: int = 14
    cache_ttl_hours: int = 6
    fomc_minutes_lag_weeks: int = 3
    sources: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LevelsConfig:
    wall_proximity_points: float = 40.0
    stale_data_minutes: int = 30
    spot_max_age_minutes: float = 20.0
    cboe_max_median_delay_minutes: float = 30.0
    wall_window_pct: float = 0.03
    straddle_max_spread_pct: float = 0.20
    target_tolerance_minutes: float = 15.0
    straddle_max_discrepancy_pct: float = 25.0


@dataclass(frozen=True)
class ValidationConfig:
    min_sessions: int = 60
    min_event_samples: int = 12


@dataclass(frozen=True)
class SourcesConfig:
    bls_contact_email: str = "contact@nqcockpit.local"
    stale_data_threshold_minutes: int = 60
    cboe_ndx_url: str = "https://cdn.cboe.com/api/global/delayed_quotes/options/_NDX.json"


@dataclass(frozen=True)
class USEquitiesSessionConfig:
    timezone: str = "America/New_York"
    open: str = "09:30"
    close: str = "16:00"
    trading_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    symbols: list[str] = field(
        default_factory=lambda: ["^NDX", "^VIX", "^VXN", "CBOE NDX Options"]
    )


@dataclass(frozen=True)
class CMEFuturesSessionConfig:
    timezone: str = "America/New_York"
    open_sunday: str = "18:00"
    close_friday: str = "17:00"
    daily_halt_start: str = "17:00"
    daily_halt_end: str = "18:00"
    symbols: list[str] = field(default_factory=lambda: ["NQ=F"])


@dataclass(frozen=True)
class MarketSessionsConfig:
    us_equities: USEquitiesSessionConfig = field(default_factory=USEquitiesSessionConfig)
    cme_futures: CMEFuturesSessionConfig = field(default_factory=CMEFuturesSessionConfig)


@dataclass(frozen=True)
class DataConfig:
    db_path: str = "data/nqcockpit.db"
    cache_dir: str = "data/cache"
    intraday_intervals: list[str] = field(default_factory=lambda: ["1m", "5m"])
    basis_max_drift_seconds: float = 60.0
    stale_bar_threshold_minutes: int = 15
    symbols_expected_delay_minutes: dict[str, int] = field(
        default_factory=lambda: {"NQ=F": 15}
    )
    delay_margin_minutes: int = 10
    parity_basis_tolerance_points: float = 50.0
    target_tolerance_minutes: float = 15.0


@dataclass(frozen=True)
class AppConfig:
    timezones: TimezoneConfig
    trading_windows_algiers: list[TradingWindowConfig]
    snapshots_algiers: list[str]
    rules: RulesConfig
    risk: RiskConfig
    events: EventsConfig
    levels: LevelsConfig
    validation: ValidationConfig
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    market_sessions: MarketSessionsConfig = field(default_factory=MarketSessionsConfig)
    data: DataConfig = field(default_factory=DataConfig)
    snapshots_ny: list[str] = field(default_factory=lambda: ["08:00", "09:45", "15:45"])



TIME_REGEX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _validate_time_str(time_str: str, field_name: str) -> None:
    if not isinstance(time_str, str) or not TIME_REGEX.match(time_str):
        raise ConfigError(
            f"Invalid time format in '{field_name}': expected 'HH:MM', got {time_str!r}"
        )


def _validate_timezone(tz_name: str, field_name: str) -> None:
    if not isinstance(tz_name, str) or not tz_name.strip():
        raise ConfigError(f"Missing or invalid timezone in '{field_name}'.")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"Invalid timezone in '{field_name}': {tz_name!r}") from exc


def find_config_path(explicit_path: str | Path | None = None) -> Path:
    """Finds the configuration file path."""
    if explicit_path is not None:
        p = Path(explicit_path)
        if not p.is_file():
            raise ConfigError(f"Specified config file not found: {p}")
        return p

    env_path = os.getenv("NQ_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if not p.is_file():
            raise ConfigError(f"Config path from NQ_CONFIG_PATH not found: {p}")
        return p

    cwd = Path.cwd()
    candidate = cwd / "config.yaml"
    if candidate.is_file():
        return candidate

    # Search upwards for config.yaml up to 3 levels
    for parent in list(cwd.parents)[:3]:
        candidate = parent / "config.yaml"
        if candidate.is_file():
            return candidate

    raise ConfigError("No 'config.yaml' found in current or parent directories.")


def load_config(path: str | Path | None = None) -> AppConfig:
    """Loads and validates config.yaml."""
    cfg_path = find_config_path(path)
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML file at {cfg_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read config file at {cfg_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(data).__name__}")

    # 1. Timezones
    raw_tz = data.get("timezones")
    if not isinstance(raw_tz, dict):
        raise ConfigError("Missing or invalid 'timezones' section in config.")
    _validate_timezone(raw_tz.get("display", ""), "timezones.display")
    _validate_timezone(raw_tz.get("market", ""), "timezones.market")
    timezones = TimezoneConfig(
        display=str(raw_tz["display"]),
        market=str(raw_tz["market"]),
    )

    # 2. Trading windows
    raw_windows = data.get("trading_windows_algiers")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise ConfigError("Missing or empty 'trading_windows_algiers' in config.")
    trading_windows: list[TradingWindowConfig] = []
    for idx, win in enumerate(raw_windows):
        if not isinstance(win, dict) or "name" not in win or "start" not in win or "end" not in win:
            raise ConfigError(
                f"Invalid trading window item at index {idx}: must have name, start, end."
            )
        _validate_time_str(str(win["start"]), f"trading_windows_algiers[{idx}].start")
        _validate_time_str(str(win["end"]), f"trading_windows_algiers[{idx}].end")
        if win["start"] >= win["end"]:
            raise ConfigError(
                f"Trading window '{win['name']}' has start ({win['start']}) >= end ({win['end']})."
            )
        trading_windows.append(
            TradingWindowConfig(
                name=str(win["name"]),
                start=str(win["start"]),
                end=str(win["end"]),
            )
        )

    # 3. Snapshots
    raw_snapshots = data.get("snapshots_algiers")
    if not isinstance(raw_snapshots, list) or not raw_snapshots:
        raise ConfigError("Missing or empty 'snapshots_algiers' list in config.")
    snapshots: list[str] = []
    for idx, snap in enumerate(raw_snapshots):
        _validate_time_str(str(snap), f"snapshots_algiers[{idx}]")
        snapshots.append(str(snap))

    raw_snapshots_ny = data.get("snapshots_ny", ["08:00", "09:45", "15:45"])
    snapshots_ny: list[str] = []
    if isinstance(raw_snapshots_ny, list):
        for idx, snap in enumerate(raw_snapshots_ny):
            _validate_time_str(str(snap), f"snapshots_ny[{idx}]")
            snapshots_ny.append(str(snap))

    # 4. Rules
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, dict):
        raise ConfigError("Missing or invalid 'rules' section in config.")
    max_trades = raw_rules.get("max_trades_per_day", 2)
    if not isinstance(max_trades, int) or max_trades < 1:
        raise ConfigError("rules.max_trades_per_day must be an integer >= 1.")
    cooldown = raw_rules.get("cooldown_after_sl_minutes", 15)
    if not isinstance(cooldown, int) or cooldown < 0:
        raise ConfigError("rules.cooldown_after_sl_minutes must be an integer >= 0.")
    loss_limit = raw_rules.get("daily_loss_limit_r", 2.0)
    if not isinstance(loss_limit, (int, float)) or loss_limit <= 0:
        raise ConfigError("rules.daily_loss_limit_r must be a number > 0.")
    rules = RulesConfig(
        max_trades_per_day=max_trades,
        cancel_trade2_if_trade1_loss=bool(raw_rules.get("cancel_trade2_if_trade1_loss", True)),
        cooldown_after_sl_minutes=cooldown,
        daily_loss_limit_r=float(loss_limit),
    )

    # 5. Risk
    raw_risk = data.get("risk")
    if not isinstance(raw_risk, dict):
        raise ConfigError("Missing or invalid 'risk' section in config.")
    instrument = str(raw_risk.get("instrument", "MNQ")).upper()
    if instrument not in ("NQ", "MNQ"):
        raise ConfigError(f"risk.instrument must be 'NQ' or 'MNQ', got {instrument!r}")
    risk_pct = raw_risk.get("risk_per_trade_pct", 0.5)
    if not isinstance(risk_pct, (int, float)) or risk_pct <= 0:
        raise ConfigError("risk.risk_per_trade_pct must be a number > 0.")
    risk = RiskConfig(
        instrument=instrument,
        risk_per_trade_pct=float(risk_pct),
        account_size=float(raw_risk.get("account_size", 0.0)),
        prop_profile=dict(raw_risk.get("prop_profile", {})),
    )

    # 6. Events
    raw_events = data.get("events")
    if not isinstance(raw_events, dict):
        raise ConfigError("Missing or invalid 'events' section in config.")
    post_buffer = raw_events.get("post_event_buffer_minutes", 90)
    stand_aside = raw_events.get("stand_aside_before_minutes", 5)
    wait_after = raw_events.get("wait_after_minutes", 3)
    if any(not isinstance(v, int) or v < 0 for v in (post_buffer, stand_aside, wait_after)):
        raise ConfigError("events buffer/wait minutes must be non-negative integers.")
    events = EventsConfig(
        post_event_buffer_minutes=post_buffer,
        stand_aside_before_minutes=stand_aside,
        wait_after_minutes=wait_after,
        tier1=[str(x) for x in raw_events.get("tier1", [])],
        tier2=[str(x) for x in raw_events.get("tier2", [])],
        megacaps=[str(x) for x in raw_events.get("megacaps", [])],
        horizon_days=int(raw_events.get("horizon_days", 14)),
        cache_ttl_hours=int(raw_events.get("cache_ttl_hours", 6)),
        fomc_minutes_lag_weeks=int(raw_events.get("fomc_minutes_lag_weeks", 3)),
        sources=dict(raw_events.get("sources", {})),
    )

    # 7. Levels
    raw_levels = data.get("levels")
    if not isinstance(raw_levels, dict):
        raise ConfigError("Missing or invalid 'levels' section in config.")
    wall_prox = raw_levels.get("wall_proximity_points", 40)
    stale_min = raw_levels.get("stale_data_minutes", 30)
    spot_max_age = raw_levels.get("spot_max_age_minutes", 20.0)
    wall_win_pct = raw_levels.get("wall_window_pct", 0.03)
    straddle_spread = raw_levels.get("straddle_max_spread_pct", 0.20)
    cboe_median_delay = raw_levels.get("cboe_max_median_delay_minutes", 30.0)
    target_tol = raw_levels.get("target_tolerance_minutes", 15.0)
    straddle_disc = raw_levels.get("straddle_max_discrepancy_pct", 25.0)
    if not isinstance(wall_prox, (int, float)) or wall_prox <= 0:
        raise ConfigError("levels.wall_proximity_points must be a positive number.")
    if not isinstance(stale_min, int) or stale_min <= 0:
        raise ConfigError("levels.stale_data_minutes must be a positive integer.")
    if not isinstance(spot_max_age, (int, float)) or spot_max_age <= 0:
        raise ConfigError("levels.spot_max_age_minutes must be a positive number.")
    if not isinstance(cboe_median_delay, (int, float)) or cboe_median_delay <= 0:
        raise ConfigError("levels.cboe_max_median_delay_minutes must be a positive number.")
    if not isinstance(wall_win_pct, (int, float)) or wall_win_pct <= 0:
        raise ConfigError("levels.wall_window_pct must be a positive number.")
    if not isinstance(straddle_spread, (int, float)) or straddle_spread <= 0:
        raise ConfigError("levels.straddle_max_spread_pct must be a positive number.")
    if not isinstance(target_tol, (int, float)) or target_tol <= 0:
        raise ConfigError("levels.target_tolerance_minutes must be a positive number.")
    if not isinstance(straddle_disc, (int, float)) or straddle_disc <= 0:
        raise ConfigError("levels.straddle_max_discrepancy_pct must be a positive number.")
    levels = LevelsConfig(
        wall_proximity_points=float(wall_prox),
        stale_data_minutes=stale_min,
        spot_max_age_minutes=float(spot_max_age),
        cboe_max_median_delay_minutes=float(cboe_median_delay),
        wall_window_pct=float(wall_win_pct),
        straddle_max_spread_pct=float(straddle_spread),
        target_tolerance_minutes=float(target_tol),
        straddle_max_discrepancy_pct=float(straddle_disc),
    )

    # 8. Validation
    raw_val = data.get("validation")
    if not isinstance(raw_val, dict):
        raise ConfigError("Missing or invalid 'validation' section in config.")
    min_sess = raw_val.get("min_sessions", 60)
    min_event = raw_val.get("min_event_samples", 12)
    if not isinstance(min_sess, int) or min_sess < 1:
        raise ConfigError("validation.min_sessions must be >= 1.")
    if not isinstance(min_event, int) or min_event < 1:
        raise ConfigError("validation.min_event_samples must be >= 1.")
    val = ValidationConfig(
        min_sessions=min_sess,
        min_event_samples=min_event,
    )

    # 9. Sources
    raw_sources = data.get("sources", {})
    if not isinstance(raw_sources, dict):
        raise ConfigError("Invalid 'sources' section in config.")
    bls_email = str(raw_sources.get("bls_contact_email", "contact@nqcockpit.local"))
    stale_thresh = raw_sources.get("stale_data_threshold_minutes", 60)
    if not isinstance(stale_thresh, int) or stale_thresh <= 0:
        raise ConfigError("sources.stale_data_threshold_minutes must be a positive integer.")
    cboe_url = str(
        raw_sources.get(
            "cboe_ndx_url",
            "https://cdn.cboe.com/api/global/delayed_quotes/options/_NDX.json",
        )
    )
    sources = SourcesConfig(
        bls_contact_email=bls_email,
        stale_data_threshold_minutes=stale_thresh,
        cboe_ndx_url=cboe_url,
    )

    # 10. Market Sessions
    raw_sessions = data.get("market_sessions", {})
    if not isinstance(raw_sessions, dict):
        raise ConfigError("Invalid 'market_sessions' section in config.")

    us_eq_raw = raw_sessions.get("us_equities", {})
    if not isinstance(us_eq_raw, dict):
        raise ConfigError("Invalid 'market_sessions.us_equities' section in config.")
    us_tz = str(us_eq_raw.get("timezone", "America/New_York"))
    _validate_timezone(us_tz, "market_sessions.us_equities.timezone")
    us_open = str(us_eq_raw.get("open", "09:30"))
    _validate_time_str(us_open, "market_sessions.us_equities.open")
    us_close = str(us_eq_raw.get("close", "16:00"))
    _validate_time_str(us_close, "market_sessions.us_equities.close")
    us_days = list(us_eq_raw.get("trading_days", [0, 1, 2, 3, 4]))
    us_symbols = [
        str(s) for s in us_eq_raw.get("symbols", ["^NDX", "^VIX", "^VXN", "CBOE NDX Options"])
    ]
    us_eq_cfg = USEquitiesSessionConfig(
        timezone=us_tz,
        open=us_open,
        close=us_close,
        trading_days=us_days,
        symbols=us_symbols,
    )

    cme_raw = raw_sessions.get("cme_futures", {})
    if not isinstance(cme_raw, dict):
        raise ConfigError("Invalid 'market_sessions.cme_futures' section in config.")
    cme_tz = str(cme_raw.get("timezone", "America/New_York"))
    _validate_timezone(cme_tz, "market_sessions.cme_futures.timezone")
    cme_open_sun = str(cme_raw.get("open_sunday", "18:00"))
    _validate_time_str(cme_open_sun, "market_sessions.cme_futures.open_sunday")
    cme_close_fri = str(cme_raw.get("close_friday", "17:00"))
    _validate_time_str(cme_close_fri, "market_sessions.cme_futures.close_friday")
    cme_halt_start = str(cme_raw.get("daily_halt_start", "17:00"))
    _validate_time_str(cme_halt_start, "market_sessions.cme_futures.daily_halt_start")
    cme_halt_end = str(cme_raw.get("daily_halt_end", "18:00"))
    _validate_time_str(cme_halt_end, "market_sessions.cme_futures.daily_halt_end")
    cme_symbols = [str(s) for s in cme_raw.get("symbols", ["NQ=F"])]
    cme_cfg = CMEFuturesSessionConfig(
        timezone=cme_tz,
        open_sunday=cme_open_sun,
        close_friday=cme_close_fri,
        daily_halt_start=cme_halt_start,
        daily_halt_end=cme_halt_end,
        symbols=cme_symbols,
    )
    market_sessions = MarketSessionsConfig(
        us_equities=us_eq_cfg,
        cme_futures=cme_cfg,
    )

    # 11. Data
    raw_data = data.get("data", {})
    if not isinstance(raw_data, dict):
        raw_data = {}
    delays_raw = raw_data.get("symbols_expected_delay_minutes", {"NQ=F": 15})
    if isinstance(delays_raw, dict):
        delays_map = {str(k): int(v) for k, v in delays_raw.items()}
    else:
        delays_map = {"NQ=F": 15}
    margin = int(raw_data.get("delay_margin_minutes", 10))
    parity_tol = float(raw_data.get("parity_basis_tolerance_points", 50.0))

    data_cfg = DataConfig(
        db_path=str(raw_data.get("db_path", "data/nqcockpit.db")),
        cache_dir=str(raw_data.get("cache_dir", "data/cache")),
        intraday_intervals=list(raw_data.get("intraday_intervals", ["1m", "5m"])),
        basis_max_drift_seconds=float(raw_data.get("basis_max_drift_seconds", 60.0)),
        stale_bar_threshold_minutes=int(raw_data.get("stale_bar_threshold_minutes", 15)),
        symbols_expected_delay_minutes=delays_map,
        delay_margin_minutes=margin,
        parity_basis_tolerance_points=parity_tol,
    )

    return AppConfig(
        timezones=timezones,
        trading_windows_algiers=trading_windows,
        snapshots_algiers=snapshots,
        rules=rules,
        risk=risk,
        events=events,
        levels=levels,
        validation=val,
        sources=sources,
        market_sessions=market_sessions,
        data=data_cfg,
        snapshots_ny=snapshots_ny,
    )

