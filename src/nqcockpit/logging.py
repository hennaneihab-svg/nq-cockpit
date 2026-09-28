"""Structured logging with rotation for NQ Cockpit."""

from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from nqcockpit.env import KNOWN_SECRET_KEYS


class SecretMaskingFilter(logging.Filter):
    """Filter that prevents known secrets from leaking into log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.msg)
        for key in KNOWN_SECRET_KEYS:
            secret = os.getenv(key)
            if secret and len(secret) > 3 and secret in msg:
                msg = msg.replace(secret, "[REDACTED]")
        record.msg = msg
        return True


class JsonLinesFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging(
    level: int | str = logging.INFO,
    log_dir: str | Path = "logs",
    log_filename: str = "nqcockpit.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    enable_console: bool = True,
    enable_json_log: bool = True,
) -> logging.Logger:
    """Configures structured rotating file logging and console output."""
    root_logger = logging.getLogger("nqcockpit")

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    root_logger.handlers.clear()

    mask_filter = SecretMaskingFilter()
    root_logger.addFilter(mask_filter)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 1. Standard text rotating file handler
    text_handler = RotatingFileHandler(
        filename=log_path / log_filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    text_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    text_handler.setFormatter(text_formatter)
    text_handler.setLevel(level)
    text_handler.addFilter(mask_filter)
    root_logger.addHandler(text_handler)

    # 2. JSON-lines rotating file handler
    if enable_json_log:
        json_handler = RotatingFileHandler(
            filename=log_path / f"{Path(log_filename).stem}.json.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        json_handler.setFormatter(JsonLinesFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
        json_handler.setLevel(level)
        json_handler.addFilter(mask_filter)
        root_logger.addHandler(json_handler)

    # 3. Console handler
    if enable_console:
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(level)
        console_handler.addFilter(mask_filter)
        root_logger.addHandler(console_handler)

    return root_logger


def get_logger(name: str = "nqcockpit") -> logging.Logger:
    """Returns a named child logger under the nqcockpit hierarchy."""
    if not name.startswith("nqcockpit"):
        return logging.getLogger(f"nqcockpit.{name}")
    return logging.getLogger(name)
