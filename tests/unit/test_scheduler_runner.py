"""Tests for the job_run context manager + APScheduler bootstrap."""

from __future__ import annotations

from pathlib import Path

import freezegun
import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import last_run
from driftnote.scheduler.runner import build_scheduler, cron, job_run


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def test_job_run_records_ok_on_success(engine: Engine) -> None:
    with freezegun.freeze_time("2026-05-06T21:00:00Z"), job_run(engine, "imap_poll") as run:
        run.detail("ingested 1")
    with session_scope(engine) as session:
        row = last_run(session, "imap_poll")
    assert row is not None
    assert row.status == "ok"
    assert row.detail == "ingested 1"
    assert row.finished_at is not None


def test_job_run_records_error_on_exception(engine: Engine) -> None:
    with freezegun.freeze_time("2026-05-06T21:00:00Z"), pytest.raises(RuntimeError):  # noqa: SIM117
        with job_run(engine, "imap_poll") as run:
            run.set_error_kind("imap_auth")
            raise RuntimeError("boom")
    with session_scope(engine) as session:
        row = last_run(session, "imap_poll")
    assert row is not None
    assert row.status == "error"
    assert row.error_kind == "imap_auth"
    assert "boom" in (row.error_message or "")


def test_build_scheduler_uses_configured_timezone() -> None:
    sched = build_scheduler(timezone="Europe/London")
    assert str(sched.timezone) == "Europe/London"


def test_build_scheduler_starts_paused() -> None:
    """build_scheduler returns a configured but not-yet-running scheduler."""
    sched = build_scheduler(timezone="Europe/London")
    assert sched.running is False


def test_cron_raises_clear_error_on_wrong_field_count() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="cron expression must have 5 fields"):
        cron("0 21 * * * *", "Europe/London")  # 6 fields: minute hour day month dow EXTRA

    with _pytest.raises(ValueError, match="cron expression must have 5 fields"):
        cron("0 21 *", "Europe/London")  # 3 fields
