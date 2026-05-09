"""Tests for SQLAlchemy ORM models — table names, columns, constraints."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, create_engine, inspect

from driftnote.models import (
    Base,
    DiskState,
    Entry,
    IngestedMessage,
    JobRun,
    Media,
    PendingPrompt,
    Tag,
)


@pytest.fixture
def engine() -> Engine:
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_all_tables_created(engine: Engine) -> None:
    expected = {
        "entries",
        "tags",
        "media",
        "ingested_messages",
        "pending_prompts",
        "job_runs",
        "disk_state",
    }
    insp = inspect(engine)
    assert set(insp.get_table_names()) >= expected


def test_entries_has_id_and_unique_date(engine: Engine) -> None:
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("entries")}
    assert {"id", "date", "mood", "body_text", "body_md", "created_at", "updated_at"} <= cols
    uniques = insp.get_unique_constraints("entries")
    assert any({c for c in u["column_names"]} == {"date"} for u in uniques)


def test_ingested_messages_has_imap_moved_default_zero(engine: Engine) -> None:
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("ingested_messages")}
    assert "imap_moved" in cols
    # SQLAlchemy reflects server_default; it should be '0'.
    default = cols["imap_moved"].get("default")
    assert default in ("0", 0, "'0'")


def test_models_constructible() -> None:
    Entry(
        date="2026-05-06",
        mood="💪",
        body_text="hi",
        body_md="hi",
        created_at="2026-05-06T21:00:00Z",
        updated_at="2026-05-06T21:00:00Z",
    )
    Tag(date="2026-05-06", tag="work")
    Media(date="2026-05-06", kind="photo", filename="a.jpg", ord=0)
    IngestedMessage(message_id="m1", date="2026-05-06", eml_path="raw/x.eml", ingested_at="t")
    PendingPrompt(date="2026-05-06", message_id="m2", sent_at="t")
    JobRun(job="imap_poll", started_at="t", status="running")
    DiskState(threshold_percent=80, crossed_at="t")
