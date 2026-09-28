"""Tests for environment variable handling and secret safety."""

from nqcockpit.env import get_configured_keys_status, get_key, has_key, load_environment


def test_load_environment(tmp_path):
    """Verify loading from custom .env file without leaking secrets."""
    env_file = tmp_path / ".env"
    env_file.write_text("FRED_API_KEY=test_fred_12345\n", encoding="utf-8")

    assert load_environment(env_file) is True
    assert has_key("FRED_API_KEY") is True
    assert get_key("FRED_API_KEY") == "test_fred_12345"

    status = get_configured_keys_status()
    assert isinstance(status, dict)
    assert status["FRED_API_KEY"] is True
    # Values themselves are boolean indicators, avoiding leakage
    assert all(isinstance(v, bool) for v in status.values())


def test_load_environment_missing(tmp_path):
    """Verify behavior when file does not exist."""
    missing = tmp_path / ".env.missing"
    assert load_environment(missing) is False
