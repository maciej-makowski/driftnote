"""Shared pytest fixtures for Driftnote tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class MailServer:
    """Connection details for a running mail server (GreenMail in tests)."""

    host: str
    smtp_port: int
    imap_port: int
    user: str
    password: str
    address: str


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Iterator[Path]:
    """A temp data directory matching the prod layout."""
    data = tmp_path / "data"
    (data / "entries").mkdir(parents=True)
    yield data
