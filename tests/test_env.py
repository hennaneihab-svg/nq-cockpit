"""Tests for environment variable handling and secret safety."""

import logging

from nqcockpit.env import (
    get_configured_keys_status,
    get_key,
    has_key,
    load_environment,
    save_mt5_credentials,
)


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


class _FakeKeyring:
    """Minimal keyring backend double (no extra dependency in tests)."""

    def __init__(self, secret: str | None = None) -> None:
        self.secret = secret
        self.stored: str | None = None

    def get_password(self, service: str, key: str) -> str | None:
        return self.secret

    def set_password(self, service: str, key: str, value: str) -> None:
        self.stored = value
        self.secret = value


def test_mt5_password_prefers_keyring(monkeypatch):
    """keyring (s'il est installé) est prioritaire sur MT5_PASSWORD en clair."""
    import nqcockpit.env as env_mod

    fake = _FakeKeyring(secret="FromKeyring!123")
    monkeypatch.setattr(env_mod, "_keyring_backend", lambda: fake)
    monkeypatch.setattr(env_mod, "_mt5_fallback_warning_emitted", False)
    monkeypatch.setenv("MT5_PASSWORD", "FromEnv!123")

    assert env_mod.get_mt5_password() == "FromKeyring!123"
    assert env_mod._mt5_fallback_warning_emitted is False


def test_mt5_password_keyring_installed_ignores_env(monkeypatch):
    """Keyring installé mais vide : .env n'est pas lu (plus de secret en clair)."""
    import nqcockpit.env as env_mod

    monkeypatch.setattr(env_mod, "_keyring_backend", lambda: _FakeKeyring())
    monkeypatch.setattr(env_mod, "_mt5_fallback_warning_emitted", False)
    monkeypatch.setenv("MT5_PASSWORD", "FromEnv!123")

    assert env_mod.get_mt5_password() == ""
    assert env_mod._mt5_fallback_warning_emitted is False


def test_mt5_password_env_fallback_warns_once(monkeypatch, caplog):
    """Sans keyring, repli .env avec un avertissement unique et sans fuite du secret."""
    import nqcockpit.env as env_mod

    monkeypatch.setattr(env_mod, "_keyring_backend", lambda: None)
    monkeypatch.setattr(env_mod, "_mt5_fallback_warning_emitted", False)
    monkeypatch.setenv("MT5_PASSWORD", "SecretFromEnv!123")

    with caplog.at_level(logging.WARNING):
        assert env_mod.get_mt5_password() == "SecretFromEnv!123"
        assert env_mod.get_mt5_password() == "SecretFromEnv!123"

    fallback_warnings = [
        r for r in caplog.records if "lu depuis .env en clair" in r.message
    ]
    assert len(fallback_warnings) == 1
    assert all("SecretFromEnv!123" not in r.message for r in caplog.records)


def test_save_mt5_password_uses_keyring_when_available(monkeypatch, tmp_path):
    """keyring disponible : le mot de passe n'est pas écrit en clair dans .env."""
    import nqcockpit.env as env_mod

    fake = _FakeKeyring()
    monkeypatch.setattr(env_mod, "_keyring_backend", lambda: fake)
    monkeypatch.setenv("MT5_PASSWORD", "")
    env_file = tmp_path / "keyring.env"

    assert save_mt5_credentials(
        login=1234567,
        password="SecretKeyring!123",
        server="Broker-Demo",
        env_path=env_file,
    )
    assert fake.stored == "SecretKeyring!123"
    content = env_file.read_text(encoding="utf-8")
    assert "MT5_PASSWORD=\n" in content
    assert "SecretKeyring!123" not in content
