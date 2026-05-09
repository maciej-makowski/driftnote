"""Tests for ingested_messages, pending_prompts, and disk_state repositories."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.entries import EntryRecord, upsert_entry
from driftnote.repository.ingested import (
    PendingPromptRecord,
    clear_threshold_crossed,
    find_prompt_by_message_id,
    get_ingested,
    get_threshold_crossed_at,
    is_ingested,
    mark_imap_moved,
    pending_imap_moves,
    record_ingested,
    record_pending_prompt,
    record_threshold_crossed,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-05-06",
                mood=None,
                body_text="x",
                body_md="x",
                created_at="t",
                updated_at="t",
            ),
        )
    return eng


def test_ingested_round_trip(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_ingested(
            session,
            message_id="<m1@gmail>",
            date="2026-05-06",
            eml_path="raw/2026-05-06T21-30-15Z.eml",
            ingested_at="2026-05-06T21:30:20Z",
        )
    with session_scope(engine) as session:
        assert is_ingested(session, "<m1@gmail>")
        rec = get_ingested(session, "<m1@gmail>")
    assert rec is not None
    assert rec.message_id == "<m1@gmail>"
    assert rec.imap_moved == 0


def test_mark_imap_moved_and_pending_query(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_ingested(
            session,
            message_id="<m1@gmail>",
            date="2026-05-06",
            eml_path="raw/x.eml",
            ingested_at="t",
        )
        record_ingested(
            session,
            message_id="<m2@gmail>",
            date="2026-05-06",
            eml_path="raw/y.eml",
            ingested_at="t",
        )
        mark_imap_moved(session, "<m1@gmail>")
    with session_scope(engine) as session:
        pending = pending_imap_moves(session)
    assert {r.message_id for r in pending} == {"<m2@gmail>"}


def test_record_pending_prompt_and_lookup(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="2026-05-06T21:00:00Z",
        )
    with session_scope(engine) as session:
        rec = find_prompt_by_message_id(session, "<prompt-2026-05-06@driftnote>")
    assert isinstance(rec, PendingPromptRecord)
    assert rec.date == "2026-05-06"


def test_disk_state_threshold_lifecycle(engine: Engine) -> None:
    with session_scope(engine) as session:
        assert get_threshold_crossed_at(session, 80) is None
        record_threshold_crossed(session, threshold=80, at="2026-05-06T03:00:00Z")
    with session_scope(engine) as session:
        assert get_threshold_crossed_at(session, 80) == "2026-05-06T03:00:00Z"
    with session_scope(engine) as session:
        clear_threshold_crossed(session, 80)
    with session_scope(engine) as session:
        assert get_threshold_crossed_at(session, 80) is None


def test_pending_prompt_unique_message_id(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_pending_prompt(session, date="2026-05-06", message_id="<m@x>", sent_at="t")
    with session_scope(engine) as session:
        # Re-recording the same date with the same message_id is an upsert (idempotent on the date PK).
        record_pending_prompt(session, date="2026-05-06", message_id="<m@x>", sent_at="t2")
    with session_scope(engine) as session:
        rec = find_prompt_by_message_id(session, "<m@x>")
    assert rec is not None
    assert rec.sent_at == "t2"
