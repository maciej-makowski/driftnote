"""Async APScheduler runner + a `job_run` context manager that records each
scheduled invocation as a row in `job_runs` (running → ok|error|warn)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.repository.jobs import finish_job_run, record_job_run


def _utcnow_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _RunHandle:
    """Returned by `job_run(...)`. Callers fill in `detail` / `error_kind`."""

    _detail: str | None = field(default=None)
    _error_kind: str | None = field(default=None)
    _status: str = field(default="ok")

    def detail(self, text: str) -> None:
        self._detail = text

    def set_error_kind(self, kind: str) -> None:
        self._error_kind = kind

    def warn(self) -> None:
        self._status = "warn"


@contextmanager
def job_run(engine: Engine, job: str) -> Iterator[_RunHandle]:
    """Wrap one scheduled-job invocation. Records `running` on enter; on exit
    records `ok`, `warn`, or `error` and captures any raised exception."""
    started_at = _utcnow_iso()
    with session_scope(engine) as session:
        run_id = record_job_run(session, job=job, started_at=started_at)

    handle = _RunHandle()
    try:
        yield handle
    except BaseException as exc:
        finished_at = _utcnow_iso()
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=finished_at,
                status="error",
                detail=handle._detail,
                error_kind=handle._error_kind,
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
            )
        raise
    else:
        finished_at = _utcnow_iso()
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=finished_at,
                status=handle._status,  # type: ignore[arg-type]
                detail=handle._detail,
                error_kind=handle._error_kind,
            )


def build_scheduler(*, timezone: str) -> AsyncIOScheduler:
    """Return a configured (but not started) AsyncIOScheduler in the given tz."""
    tz = ZoneInfo(timezone)
    return AsyncIOScheduler(timezone=tz)


def cron(expr: str, tz: str) -> CronTrigger:
    """Build a CronTrigger from a 5-field cron string in the given tz."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(
            f"cron expression must have 5 fields (minute hour day month dow), "
            f"got {len(fields)} in {expr!r}"
        )
    minute, hour, day, month, day_of_week = fields
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=ZoneInfo(tz),
    )
