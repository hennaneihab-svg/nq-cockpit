"""Tests for structured logging and rotating file handlers."""

import json
import logging
import os

from nqcockpit.logging import get_logger, setup_logging


def test_setup_logging(tmp_path):
    """Verify logging setup creates both standard text and json files."""
    log_dir = tmp_path / "logs"
    setup_logging(
        level=logging.DEBUG,
        log_dir=log_dir,
        log_filename="test_cockpit.log",
        enable_console=False,
    )

    child = get_logger("test_module")
    child.info("Test message for structured logger")

    text_log = log_dir / "test_cockpit.log"
    json_log = log_dir / "test_cockpit.json.log"

    assert text_log.is_file()
    assert json_log.is_file()

    text_content = text_log.read_text(encoding="utf-8")
    assert "Test message for structured logger" in text_content
    assert "nqcockpit.test_module" in text_content

    json_lines = json_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(json_lines) >= 1
    last_record = json.loads(json_lines[-1])
    assert last_record["message"] == "Test message for structured logger"
    assert last_record["level"] == "INFO"
    assert last_record["logger"] == "nqcockpit.test_module"


def test_secret_masking(tmp_path):
    """Verify that known secrets are masked in log records."""
    log_dir = tmp_path / "logs_mask"
    os.environ["FRED_API_KEY"] = "super_secret_fred_key"

    logger = setup_logging(
        level=logging.INFO,
        log_dir=log_dir,
        log_filename="mask_test.log",
        enable_console=False,
    )
    logger.info("Attempting to connect with key super_secret_fred_key in query")

    text_log = log_dir / "mask_test.log"
    content = text_log.read_text(encoding="utf-8")
    assert "super_secret_fred_key" not in content
    assert "[REDACTED]" in content
