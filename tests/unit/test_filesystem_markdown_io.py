"""Tests for entry.md read/write — YAML frontmatter + body."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pytest import TempPathFactory

from driftnote.filesystem.markdown_io import (
    EntryDocument,
    MalformedEntryError,
    PhotoRef,
    VideoRef,
    read_entry,
    write_entry,
)


def _doc(**overrides: object) -> EntryDocument:
    base = EntryDocument(
        date=date(2026, 5, 6),
        mood="💪",
        tags=["work", "cooking"],
        photos=[PhotoRef(filename="IMG_4521.heic", caption="")],
        videos=[VideoRef(filename="VID_4522.mov")],
        created_at="2026-05-06T21:30:15Z",
        updated_at="2026-05-06T21:30:15Z",
        sources=["raw/2026-05-06T21-30-15Z.eml"],
        body="Long day at work. #work\n",
    )
    return base.model_copy(update=overrides)


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    doc = _doc()
    write_entry(path, doc)
    loaded = read_entry(path)
    assert loaded == doc


def test_write_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "deeper" / "entry.md"
    write_entry(path, _doc())
    assert path.exists()


def test_write_is_atomic(tmp_path: Path) -> None:
    """write_entry replaces atomically (no half-written file visible)."""
    path = tmp_path / "entry.md"
    write_entry(path, _doc(body="first"))
    write_entry(path, _doc(body="second"))
    text = path.read_text()
    assert "second" in text
    # No leftover .tmp from os.replace pattern
    assert list(path.parent.glob("*.tmp")) == []


def test_read_handles_no_mood(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    write_entry(path, _doc(mood=None))
    loaded = read_entry(path)
    assert loaded.mood is None


def test_read_handles_empty_tags_and_media(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    write_entry(path, _doc(tags=[], photos=[], videos=[]))
    loaded = read_entry(path)
    assert loaded.tags == []
    assert loaded.photos == []
    assert loaded.videos == []


def test_read_rejects_missing_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    path.write_text("just a body, no frontmatter\n")
    with pytest.raises(MalformedEntryError):
        read_entry(path)


def test_read_rejects_unterminated_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    path.write_text("---\ndate: 2026-05-06\nbody never ends\n")
    with pytest.raises(MalformedEntryError):
        read_entry(path)


def test_read_rejects_bad_yaml(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    path.write_text("---\nfoo: : :\n---\nbody\n")
    with pytest.raises(MalformedEntryError):
        read_entry(path)


def test_body_separator_preserved_for_multi_section_entries(tmp_path: Path) -> None:
    """Multi-source entries put `---` between body sections; this is part of the
    body text (not a frontmatter delimiter) and must round-trip."""
    body = "First reply.\n\n---\n\nAfterthought.\n"
    path = tmp_path / "entry.md"
    write_entry(path, _doc(body=body))
    assert read_entry(path).body == body


@given(
    body=st.text(
        alphabet=st.characters(
            blacklist_categories=("Cs",),  # type: ignore[arg-type]  # exclude surrogates
            blacklist_characters="\x00",
        ),
        min_size=0,
        max_size=200,
    ),
    tags=st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=20),
        max_size=10,
    ),
    mood=st.one_of(st.none(), st.sampled_from(["💪", "🌧️", "☕", "🎉", "😴"])),
)
@settings(max_examples=30, deadline=None)
def test_round_trip_property(
    tmp_path_factory: TempPathFactory, body: str, tags: list[str], mood: str | None
) -> None:
    path = tmp_path_factory.mktemp("entry") / "entry.md"
    doc = _doc(body=body, tags=tags, mood=mood)
    write_entry(path, doc)
    loaded = read_entry(path)
    assert loaded == doc
