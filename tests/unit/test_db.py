"""Tests for DB engine, session, and FTS5 trigger setup."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from driftnote.db import init_db, make_engine, session_scope


def test_init_db_applies_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with engine.connect() as conn:
        names = [
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        ]
    assert "entries" in names
    assert "entries_fts" in names


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    init_db(engine)  # second call must not raise


def test_wal_mode_enabled(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar_one()
    assert str(mode).lower() == "wal"


def test_fts_inserts_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with session_scope(engine) as session:
        session.execute(
            text(
                "INSERT INTO entries(date, body_text, body_md, created_at, updated_at) "
                "VALUES (:d, :t, :m, :c, :u)"
            ),
            {
                "d": "2026-05-06",
                "t": "the quick brown fox",
                "m": "the **quick** brown fox",
                "c": "2026-05-06T21:00:00Z",
                "u": "2026-05-06T21:00:00Z",
            },
        )
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT date FROM entries WHERE rowid IN "
                "(SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'fox')"
            )
        ).all()
    assert [tuple(r) for r in rows] == [("2026-05-06",)]


def test_fts_updates_on_body_text_change(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with session_scope(engine) as session:
        session.execute(
            text(
                "INSERT INTO entries(date, body_text, body_md, created_at, updated_at) "
                "VALUES ('2026-05-06', 'cats are fine', 'cats are fine', 't', 't')"
            ),
        )
        session.execute(
            text("UPDATE entries SET body_text = 'dogs are fine' WHERE date = '2026-05-06'"),
        )
    with engine.connect() as conn:
        cats = conn.execute(
            text(
                "SELECT date FROM entries WHERE rowid IN "
                "(SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'cats')"
            )
        ).all()
        dogs = conn.execute(
            text(
                "SELECT date FROM entries WHERE rowid IN "
                "(SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'dogs')"
            )
        ).all()
    assert cats == []
    assert [tuple(r) for r in dogs] == [("2026-05-06",)]


def test_session_scope_commits_on_success(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with session_scope(engine) as session:
        session.execute(
            text("INSERT INTO disk_state(threshold_percent, crossed_at) VALUES (80, 't')"),
        )
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT threshold_percent FROM disk_state")).all()
    assert [tuple(r) for r in rows] == [(80,)]


def test_session_scope_rolls_back_on_error(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)

    with pytest.raises(RuntimeError), session_scope(engine) as session:
        session.execute(
            text("INSERT INTO disk_state(threshold_percent, crossed_at) VALUES (80, 't')"),
        )
        raise RuntimeError("boom")

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT threshold_percent FROM disk_state")).all()
    assert len(rows) == 0
