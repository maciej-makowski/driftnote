"""Structured logging via structlog.

JSON output to stdout in prod (`json_output=True`); a friendlier
console renderer in dev. Secrets matched by name are redacted before
the renderer sees them.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

REDACTED = "***REDACTED***"

_SECRET_KEYS = frozenset(
    {
        "gmail_app_password",
        "app_password",
        "password",
        "secret",
        "token",
        "authorization",
        "cf_access_jwt_assertion",
    }
)


def redact_secrets(event_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of event_dict with values for known secret keys masked.

    Recursively walks nested mappings and lists so a secret nested inside
    a logged config dict (e.g. log.info("cfg", cfg=config.model_dump()))
    still gets masked.
    """
    return {k: _redact_value(k, v) for k, v in event_dict.items()}


def _redact_value(key: str, value: Any) -> Any:
    if key.lower() in _SECRET_KEYS:
        return REDACTED
    if isinstance(value, Mapping):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


def _redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    return redact_secrets(event_dict)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure stdlib + structlog. Idempotent."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="%(message)s",
        force=True,
    )

    renderer: Any
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
