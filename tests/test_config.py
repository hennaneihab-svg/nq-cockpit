"""Tests for configuration loading and validation."""

import pytest
import yaml

from nqcockpit.config import ConfigError, load_config


def test_load_default_config():
    """Verify that root config.yaml loads and validates successfully."""
    cfg = load_config()
    assert cfg.timezones.display == "Africa/Algiers"
    assert cfg.timezones.market == "America/New_York"
    assert len(cfg.trading_windows_algiers) >= 2
    assert cfg.trading_windows_algiers[0].name == "trade1"
    assert cfg.trading_windows_algiers[0].start == "15:30"
    assert cfg.trading_windows_algiers[0].end == "17:00"
    assert cfg.rules.max_trades_per_day == 2
    assert cfg.rules.cancel_trade2_if_trade1_loss is True
    assert cfg.rules.cooldown_after_sl_minutes == 15
    assert cfg.rules.daily_loss_limit_r == 2.0
    assert cfg.risk.instrument in ("NQ", "MNQ")
    assert cfg.levels.wall_proximity_points == 40.0
    assert cfg.levels.stale_data_minutes == 30
    assert cfg.validation.min_sessions == 60
    assert cfg.validation.min_event_samples == 12


def test_config_missing_file(tmp_path):
    """Verify that a missing config file raises ConfigError."""
    missing_file = tmp_path / "does_not_exist.yaml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(missing_file)


def test_config_invalid_yaml(tmp_path):
    """Verify that malformed YAML raises ConfigError."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("timezones: [unclosed list", encoding="utf-8")
    with pytest.raises(ConfigError, match="Failed to parse YAML"):
        load_config(bad_yaml)


def test_config_invalid_timezone(tmp_path):
    """Verify that unknown timezone names raise ConfigError."""
    bad_tz = tmp_path / "bad_tz.yaml"
    data = {
        "timezones": {"display": "Invalid/Timezone", "market": "America/New_York"},
        "trading_windows_algiers": [{"name": "t1", "start": "15:30", "end": "17:00"}],
        "snapshots_algiers": ["13:00"],
        "rules": {"max_trades_per_day": 2, "daily_loss_limit_r": 2.0},
        "risk": {"instrument": "MNQ", "risk_per_trade_pct": 0.5},
        "events": {"post_event_buffer_minutes": 90},
        "levels": {"wall_proximity_points": 40, "stale_data_minutes": 30},
        "validation": {"min_sessions": 60, "min_event_samples": 12},
    }
    bad_tz.write_text(yaml.dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid timezone"):
        load_config(bad_tz)


def test_config_invalid_trading_window_times(tmp_path):
    """Verify trading window with start >= end raises ConfigError."""
    bad_win = tmp_path / "bad_win.yaml"
    data = {
        "timezones": {"display": "Africa/Algiers", "market": "America/New_York"},
        "trading_windows_algiers": [{"name": "inverted", "start": "17:00", "end": "15:30"}],
        "snapshots_algiers": ["13:00"],
        "rules": {"max_trades_per_day": 2, "daily_loss_limit_r": 2.0},
        "risk": {"instrument": "MNQ", "risk_per_trade_pct": 0.5},
        "events": {"post_event_buffer_minutes": 90},
        "levels": {"wall_proximity_points": 40, "stale_data_minutes": 30},
        "validation": {"min_sessions": 60, "min_event_samples": 12},
    }
    bad_win.write_text(yaml.dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="start .* >= end"):
        load_config(bad_win)


def test_config_invalid_instrument(tmp_path):
    """Verify invalid instrument raises ConfigError."""
    bad_inst = tmp_path / "bad_inst.yaml"
    data = {
        "timezones": {"display": "Africa/Algiers", "market": "America/New_York"},
        "trading_windows_algiers": [{"name": "t1", "start": "15:30", "end": "17:00"}],
        "snapshots_algiers": ["13:00"],
        "rules": {"max_trades_per_day": 2, "daily_loss_limit_r": 2.0},
        "risk": {"instrument": "ES", "risk_per_trade_pct": 0.5},
        "events": {"post_event_buffer_minutes": 90},
        "levels": {"wall_proximity_points": 40, "stale_data_minutes": 30},
        "validation": {"min_sessions": 60, "min_event_samples": 12},
    }
    bad_inst.write_text(yaml.dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="risk.instrument must be 'NQ' or 'MNQ'"):
        load_config(bad_inst)
