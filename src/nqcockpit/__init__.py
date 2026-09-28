"""NQ Cockpit — Cockpit local de préparation, discipline et mesure pour le trading NQ."""

from __future__ import annotations

from nqcockpit.config import AppConfig, ConfigError, load_config
from nqcockpit.env import get_key, has_key, load_environment
from nqcockpit.logging import get_logger, setup_logging
from nqcockpit.time import (
    TZ_ALGIERS,
    TZ_NEW_YORK,
    TZ_UTC,
    convert_tz,
    get_ny_algiers_offset_hours,
    is_in_trading_window,
    next_algiers_time,
    now_algiers,
    now_ny,
    to_algiers,
    to_ny,
)

__version__ = "0.1.0"

__all__ = [
    "AppConfig",
    "ConfigError",
    "load_config",
    "load_environment",
    "get_key",
    "has_key",
    "setup_logging",
    "get_logger",
    "TZ_ALGIERS",
    "TZ_NEW_YORK",
    "TZ_UTC",
    "now_algiers",
    "now_ny",
    "to_algiers",
    "to_ny",
    "convert_tz",
    "get_ny_algiers_offset_hours",
    "next_algiers_time",
    "is_in_trading_window",
]
