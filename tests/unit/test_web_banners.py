"""Tests for banner state derivation."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.ingested import record_threshold_crossed
from driftnote.repository.jobs import finish_job_run, record_job_run
from driftnote.web.banners import compute_banners


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def test_no_banners_for_clean_state(engine: Engine) -> None:
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    assert banners == []


def test_unacknowledged_failure_in_last_7_days(engine: Engine) -> None:
    with session_scope(engine) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-05T12:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-05-05T12:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    levels = [b.level for b in banners]
    assert "error" in levels


def test_old_failure_outside_window_does_not_show(engine: Engine) -> None:
    with session_scope(engine) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-04-01T12:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-04-01T12:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    assert all(b.level != "error" for b in banners)


def test_disk_threshold_crossed_shows_warning(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_threshold_crossed(session, threshold=80, at="2026-05-06T03:00:00Z")
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    assert any(b.level == "warn" and "disk" in b.message.lower() for b in banners)


def test_no_recent_backup_warning(engine: Engine) -> None:
    """If backup hasn't succeeded in >35 days, surface an amber banner."""
    with session_scope(engine) as session:
        rid = record_job_run(session, job="backup", started_at="2026-03-01T03:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-03-01T03:00:10Z", status="ok")
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    assert any(b.level == "warn" and "backup" in b.message.lower() for b in banners)


def test_no_banners_when_no_backup_history(engine: Engine) -> None:
    """A fresh install with no backup runs at all should NOT show the banner."""
    banners = compute_banners(engine, now="2026-05-09T12:00:00Z")
    assert banners == []


def test_warn_banner_when_last_backup_is_stale(engine: Engine) -> None:
    """A backup ran 40 days ago, no recent run since → amber banner."""
    with session_scope(engine) as session:
        rid = record_job_run(session, job="backup", started_at="2026-03-01T03:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-03-01T03:00:10Z",
            status="ok",
        )
    banners = compute_banners(engine, now="2026-05-09T12:00:00Z")
    assert any("backup" in b.message.lower() and b.level == "warn" for b in banners)
