"""Environment variables loading and secure access for NQ Cockpit."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

KNOWN_SECRET_KEYS = (
    "FRED_API_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


def load_environment(env_path: str | Path | None = None) -> bool:
    """Loads environment variables from .env file.

    Returns True if a .env file was located and loaded, False otherwise.
    Never logs or exposes the secret values.
    """
    if env_path is not None:
        p = Path(env_path)
        if p.is_file():
            load_dotenv(dotenv_path=p, override=True)
            return True
        return False

    cwd = Path.cwd()
    candidate = cwd / ".env"
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate, override=True)
        return True

    for parent in list(cwd.parents)[:3]:
        candidate = parent / ".env"
        if candidate.is_file():
            load_dotenv(dotenv_path=candidate, override=True)
            return True

    return False


def get_key(key: str, default: str | None = None) -> str | None:
    """Returns the value of an environment variable or default."""
    return os.getenv(key, default)


def has_key(key: str) -> bool:
    """Checks whether an environment variable is present and non-empty without exposing it."""
    val = os.getenv(key)
    return bool(val and val.strip())


def get_configured_keys_status() -> dict[str, bool]:
    """Returns a dictionary indicating whether known keys are configured, without leaking values."""
    return {k: has_key(k) for k in KNOWN_SECRET_KEYS}
