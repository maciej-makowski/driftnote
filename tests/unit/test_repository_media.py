"""Tests for the media repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.entries import EntryRecord, upsert_entry
from driftnote.repository.media import MediaInput, list_media, replace_media


@pytest.fixture
def engine_with_entry(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-05-06",
                mood="💪",
                body_text="hi",
                body_md="hi",
                created_at="t",
                updated_at="t",
            ),
        )
    return eng


def test_replace_media_inserts_in_order(engine_with_entry: Engine) -> None:
    eng = engine_with_entry
    with session_scope(eng) as session:
        replace_media(
            session,
            "2026-05-06",
            [
                MediaInput(kind="photo", filename="a.heic"),
                MediaInput(kind="photo", filename="b.jpg"),
                MediaInput(kind="video", filename="v.mov", caption="walk"),
            ],
        )
    with session_scope(eng) as session:
        items = list_media(session, "2026-05-06")
    assert [(m.ord, m.kind, m.filename) for m in items] == [
        (0, "photo", "a.heic"),
        (1, "photo", "b.jpg"),
        (2, "video", "v.mov"),
    ]
    assert items[2].caption == "walk"


def test_replace_media_overwrites_previous(engine_with_entry: Engine) -> None:
    eng = engine_with_entry
    with session_scope(eng) as session:
        replace_media(session, "2026-05-06", [MediaInput(kind="photo", filename="old.heic")])
        replace_media(session, "2026-05-06", [MediaInput(kind="photo", filename="new.heic")])
    with session_scope(eng) as session:
        items = list_media(session, "2026-05-06")
    assert [m.filename for m in items] == ["new.heic"]


def test_list_media_for_unknown_date_is_empty(engine_with_entry: Engine) -> None:
    with session_scope(engine_with_entry) as session:
        assert list_media(session, "2099-01-01") == []
