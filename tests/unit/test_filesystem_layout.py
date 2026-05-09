"""Tests for filesystem path layout helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from driftnote.filesystem.layout import (
    EntryPaths,
    entry_paths_for,
    parse_eml_received_at,
    raw_eml_filename,
)


def test_entry_paths_for_date(tmp_path: Path) -> None:
    paths = entry_paths_for(tmp_path, date(2026, 5, 6))
    assert isinstance(paths, EntryPaths)
    assert paths.dir == tmp_path / "entries" / "2026" / "05" / "06"
    assert paths.entry_md == paths.dir / "entry.md"
    assert paths.raw_dir == paths.dir / "raw"
    assert paths.originals_dir == paths.dir / "originals"
    assert paths.web_dir == paths.dir / "web"
    assert paths.thumbs_dir == paths.dir / "thumbs"


def test_raw_eml_filename_format() -> None:
    # 21:30:15 UTC on 2026-05-06
    from datetime import UTC, datetime

    received = datetime(2026, 5, 6, 21, 30, 15, tzinfo=UTC)
    name = raw_eml_filename(received)
    assert name == "2026-05-06T21-30-15Z.eml"


def test_raw_eml_filename_is_filesystem_safe() -> None:
    from datetime import UTC, datetime

    name = raw_eml_filename(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    forbidden = set(":/\\<>|?*")
    assert not (set(name) & forbidden)


def test_parse_eml_received_at_round_trip() -> None:
    from datetime import UTC, datetime

    original = datetime(2026, 5, 6, 21, 30, 15, tzinfo=UTC)
    name = raw_eml_filename(original)
    parsed = parse_eml_received_at(name)
    assert parsed == original


def test_parse_eml_received_at_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        parse_eml_received_at("not-a-date.eml")
