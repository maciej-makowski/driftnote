"""Tests for structured logging setup."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import structlog

from driftnote.logging import REDACTED, configure_logging, redact_secrets


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()


def test_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)
    log = structlog.get_logger("test")
    log.info("hello", entry_date="2026-05-06", count=3)

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["entry_date"] == "2026-05-06"
    assert payload["count"] == 3
    assert payload["level"] == "info"


def test_redacts_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)
    log = structlog.get_logger("test")
    log.info("auth", gmail_app_password="hunter2", token="abc", user="u@example.com")

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert payload["gmail_app_password"] == REDACTED
    assert payload["token"] == REDACTED
    assert payload["user"] == "u@example.com"


def test_redact_secrets_helper_keeps_non_secret_keys() -> None:
    out = redact_secrets({"gmail_user": "u", "gmail_app_password": "p", "extra": 1})
    assert out == {"gmail_user": "u", "gmail_app_password": REDACTED, "extra": 1}


def test_redact_secrets_helper_redacts_secret_key() -> None:
    out = redact_secrets({"secret": "x"})
    assert out == {"secret": REDACTED}


def test_pretty_output_when_json_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="DEBUG", json_output=False)
    log = structlog.get_logger("test")
    log.debug("dev")
    out = capsys.readouterr().out
    assert "dev" in out
    # Pretty output is not JSON — line should not parse.
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip().splitlines()[-1])


def test_logging_level_respected(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="WARNING", json_output=True)
    log = structlog.get_logger("test")
    log.info("filtered")
    log.warning("kept")
    out = capsys.readouterr().out
    assert "kept" in out
    assert "filtered" not in out
