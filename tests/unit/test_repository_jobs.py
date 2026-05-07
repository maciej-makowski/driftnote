"""Tests for the job_runs repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import (
    JobRunRecord,
    acknowledge_run,
    finish_job_run,
    last_run,
    last_successful_run,
    recent_alerts_of_kind,
    recent_failures,
    recent_runs_for_job,
    record_job_run,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def test_record_then_finish_run(engine: Engine) -> None:
    with session_scope(engine) as session:
        run_id = record_job_run(session, job="imap_poll", started_at="2026-05-06T21:00:00Z")
    with session_scope(engine) as session:
        finish_job_run(
            session,
            run_id=run_id,
            finished_at="2026-05-06T21:00:05Z",
            status="ok",
            detail="ingested 1",
        )
    with session_scope(engine) as session:
        latest = last_run(session, "imap_poll")
    assert latest is not None
    assert latest.status == "ok"
    assert latest.detail == "ingested 1"


def test_last_successful_run_skips_errors(engine: Engine) -> None:
    with session_scope(engine) as session:
        ok_id = record_job_run(session, job="imap_poll", started_at="2026-05-06T20:00:00Z")
        finish_job_run(session, run_id=ok_id, finished_at="2026-05-06T20:00:01Z", status="ok")
        err_id = record_job_run(session, job="imap_poll", started_at="2026-05-06T21:00:00Z")
        finish_job_run(
            session,
            run_id=err_id,
            finished_at="2026-05-06T21:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    with session_scope(engine) as session:
        ok = last_successful_run(session, "imap_poll")
        any_run = last_run(session, "imap_poll")
    assert ok is not None and ok.status == "ok"
    assert any_run is not None and any_run.status == "error"


def test_recent_failures_within_days(engine: Engine) -> None:
    with session_scope(engine) as session:
        old = record_job_run(session, job="backup", started_at="2026-04-01T00:00:00Z")
        finish_job_run(session, run_id=old, finished_at="2026-04-01T00:00:01Z", status="error")
        new = record_job_run(session, job="backup", started_at="2026-05-05T00:00:00Z")
        finish_job_run(session, run_id=new, finished_at="2026-05-05T00:00:01Z", status="error")
    with session_scope(engine) as session:
        within_7 = recent_failures(session, now="2026-05-06T00:00:00Z", days=7)
    assert [r.id for r in within_7] == [new]


def test_recent_alerts_of_kind_for_dedup(engine: Engine) -> None:
    with session_scope(engine) as session:
        a = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(
            session,
            run_id=a,
            finished_at="2026-05-06T08:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    with session_scope(engine) as session:
        in_24h = recent_alerts_of_kind(
            session,
            error_kind="imap_auth",
            now="2026-05-06T20:00:00Z",
            hours=24,
        )
        old = recent_alerts_of_kind(
            session,
            error_kind="imap_auth",
            now="2026-05-08T20:00:00Z",
            hours=24,
        )
    assert len(in_24h) == 1
    assert old == []


def test_acknowledge_run(engine: Engine) -> None:
    with session_scope(engine) as session:
        a = record_job_run(session, job="imap_poll", started_at="t")
        finish_job_run(session, run_id=a, finished_at="t", status="error")
    with session_scope(engine) as session:
        acknowledge_run(session, run_id=a, at="2026-05-06T22:00:00Z")
    with session_scope(engine) as session:
        unack = recent_failures(
            session, now="2026-05-06T23:00:00Z", days=7, only_unacknowledged=True
        )
    assert unack == []


def test_record_returns_running_record(engine: Engine) -> None:
    with session_scope(engine) as session:
        run_id = record_job_run(session, job="imap_poll", started_at="t")
        latest = last_run(session, "imap_poll")
    assert latest is not None
    assert latest.id == run_id
    assert latest.status == "running"
    assert isinstance(latest, JobRunRecord)


def test_recent_runs_for_job_returns_most_recent_first(engine: Engine) -> None:
    with session_scope(engine) as session:
        a = record_job_run(session, job="backup", started_at="2026-05-01T00:00:00Z")
        finish_job_run(session, run_id=a, finished_at="2026-05-01T00:00:01Z", status="ok")
        b = record_job_run(session, job="backup", started_at="2026-05-03T00:00:00Z")
        finish_job_run(session, run_id=b, finished_at="2026-05-03T00:00:01Z", status="error")
        # Different job — should not appear.
        c = record_job_run(session, job="imap_poll", started_at="2026-05-04T00:00:00Z")
        finish_job_run(session, run_id=c, finished_at="2026-05-04T00:00:01Z", status="ok")
    with session_scope(engine) as session:
        rows = recent_runs_for_job(session, "backup")
    assert [r.id for r in rows] == [b, a]
    assert all(r.job == "backup" for r in rows)


def test_recent_runs_for_job_respects_limit(engine: Engine) -> None:
    with session_scope(engine) as session:
        ids = []
        for i in range(5):
            rid = record_job_run(
                session, job="disk_check", started_at=f"2026-05-0{i + 1}T00:00:00Z"
            )
            finish_job_run(
                session, run_id=rid, finished_at=f"2026-05-0{i + 1}T00:00:01Z", status="ok"
            )
            ids.append(rid)
    with session_scope(engine) as session:
        rows = recent_runs_for_job(session, "disk_check", limit=3)
    assert len(rows) == 3
    # Most recent first.
    assert rows[0].id == ids[-1]
