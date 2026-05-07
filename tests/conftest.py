"""Shared pytest fixtures for Driftnote tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Iterator[Path]:
    """A temp data directory matching the prod layout."""
    data = tmp_path / "data"
    (data / "entries").mkdir(parents=True)
    yield data
