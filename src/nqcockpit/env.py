"""Environment variables loading and secure access for NQ Cockpit."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

KNOWN_SECRET_KEYS = (
    "FRED_API_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "MT5_LOGIN",
    "MT5_PASSWORD",
    "MT5_SERVER",
    "MT5_PATH",
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


def resolve_env_path(env_path: str | Path | None = None) -> Path:
    """Finds or resolves target .env path."""
    if env_path is not None:
        return Path(env_path)

    cwd = Path.cwd()
    candidate = cwd / ".env"
    if candidate.is_file():
        return candidate

    for parent in list(cwd.parents)[:3]:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate

    return cwd / ".env"


def update_env_file(updates: dict[str, str], env_path: str | Path | None = None) -> bool:
    """Updates targeted keys in .env file while preserving all other lines and comments.

    Never logs secret values.
    """
    p = resolve_env_path(env_path)
    lines: list[str] = []
    if p.is_file():
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            lines = []

    pending = dict(updates)
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        matched_key = None
        for k in list(pending.keys()):
            if (
                stripped.startswith(f"{k}=")
                or stripped.startswith(f"{k} =")
                or stripped.startswith(f"# {k}=")
                or stripped.startswith(f"#{k}=")
                or stripped.startswith(f"# {k} =")
                or stripped.startswith(f"#{k} =")
            ):
                matched_key = k
                break
        if matched_key is not None:
            new_lines.append(f"{matched_key}={pending.pop(matched_key)}\n")
        else:
            new_lines.append(line)

    for k, val in pending.items():
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{k}={val}\n")

    p.parent.mkdir(parents=True, exist_ok=True)
    temp_p = p.parent / f"{p.name}.tmp_{os.getpid()}"
    try:
        with open(temp_p, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        os.replace(temp_p, p)
    except OSError:
        if temp_p.is_file():
            temp_p.unlink(missing_ok=True)
        return False

    for k, val in updates.items():
        os.environ[k] = str(val)

    return True


def get_mt5_credentials(env_path: str | Path | None = None) -> dict[str, Any]:
    """Returns MT5 configured credentials status with masked password information.

    Safe for UI and diagnostic reporting — never exposes password.
    """
    load_environment(env_path)
    login_str = get_key("MT5_LOGIN", "")
    login_val: int | None = None
    if login_str and login_str.strip().isdigit():
        try:
            login_val = int(login_str.strip())
        except ValueError:
            login_val = None

    return {
        "login": login_val,
        "server": get_key("MT5_SERVER", "") or "",
        "path": get_key("MT5_PATH", "") or "",
        "broker_tz": get_key("MT5_BROKER_TZ", "UTC") or "UTC",
        "has_password": has_key("MT5_PASSWORD"),
    }


def get_mt5_raw_credentials(env_path: str | Path | None = None) -> dict[str, Any]:
    """Returns raw credentials for internal MT5 IPC authentication without logging."""
    load_environment(env_path)
    login_str = get_key("MT5_LOGIN", "")
    login_val: int | None = None
    if login_str and login_str.strip().isdigit():
        try:
            login_val = int(login_str.strip())
        except ValueError:
            login_val = None

    return {
        "login": login_val,
        "password": get_key("MT5_PASSWORD", "") or "",
        "server": get_key("MT5_SERVER", "") or "",
        "path": get_key("MT5_PATH", "") or "",
        "broker_tz": get_key("MT5_BROKER_TZ", "UTC") or "UTC",
    }


def save_mt5_credentials(
    login: str | int,
    password: str,
    server: str,
    path: str = "",
    broker_tz: str = "UTC",
    env_path: str | Path | None = None,
) -> bool:
    """Saves MT5 credentials to .env file preserving all other variables and comments.

    If password is empty and MT5_PASSWORD already exists, the existing password
    is preserved. Never logs secret values.
    """
    updates: dict[str, str] = {
        "MT5_LOGIN": str(login).strip(),
        "MT5_SERVER": str(server).strip(),
    }
    cleaned_pw = str(password).strip()
    if cleaned_pw:
        updates["MT5_PASSWORD"] = cleaned_pw
    else:
        existing_pw = os.getenv("MT5_PASSWORD")
        if existing_pw is not None:
            updates["MT5_PASSWORD"] = existing_pw

    if path is not None and str(path).strip():
        updates["MT5_PATH"] = str(path).strip()
    if broker_tz is not None and str(broker_tz).strip():
        updates["MT5_BROKER_TZ"] = str(broker_tz).strip()

    return update_env_file(updates, env_path=env_path)
