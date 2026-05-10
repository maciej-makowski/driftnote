"""job_runs CRUD + helpers used by the scheduler runner and admin/banner code."""

from __future__ import annotations

from datetime import UTC
from typing import Any, Literal, cast

from pydantic import BaseModel
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from driftnote.models import JobRun

JobName = Literal[
    "daily_prompt",
    "imap_poll",
    "digest_weekly",
    "digest_monthly",
    "digest_yearly",
    "backup",
    "disk_check",
]
RunStatus = Literal["running", "ok", "warn", "error"]


class JobRunRecord(BaseModel):
    id: int
    job: str
    started_at: str
    finished_at: str | None = None
    status: str
    detail: str | None = None
    error_kind: str | None = None
    error_message: str | None = None
    acknowledged_at: str | None = None


def _to_record(r: JobRun) -> JobRunRecord:
    return JobRunRecord(
        id=r.id,
        job=r.job,
        started_at=r.started_at,
        finished_at=r.finished_at,
        status=r.status,
        detail=r.detail,
        error_kind=r.error_kind,
        error_message=r.error_message,
        acknowledged_at=r.acknowledged_at,
    )


def record_job_run(session: Session, *, job: str, started_at: str) -> int:
    row = JobRun(job=job, started_at=started_at, status="running")
    session.add(row)
    session.flush()
    return row.id


def finish_job_run(
    session: Session,
    *,
    run_id: int,
    finished_at: str,
    status: RunStatus,
    detail: str | None = None,
    error_kind: str | None = None,
    error_message: str | None = None,
) -> None:
    session.execute(
        update(JobRun)
        .where(JobRun.id == run_id)
        .values(
            finished_at=finished_at,
            status=status,
            detail=detail,
            error_kind=error_kind,
            error_message=error_message,
        )
    )


def acknowledge_run(session: Session, *, run_id: int, at: str) -> None:
    session.execute(update(JobRun).where(JobRun.id == run_id).values(acknowledged_at=at))


def acknowledge_all_for_job(session: Session, *, job: str, now: str) -> int:
    """Bulk-acknowledge every unacked error/warn row for `job` started by `now`.

    Returns the number of rows updated. Already-acknowledged rows and rows that
    started after `now` are not touched, which keeps "ack all" idempotent and
    safe against runs that begin between the user's click and the request.
    """
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(JobRun)
            .where(
                JobRun.job == job,
                JobRun.status.in_(["error", "warn"]),
                JobRun.acknowledged_at.is_(None),
                JobRun.started_at <= now,
            )
            .values(acknowledged_at=now)
        ),
    )
    return result.rowcount or 0


def last_run(session: Session, job: str) -> JobRunRecord | None:
    stmt = select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(1)
    r = session.scalar(stmt)
    return _to_record(r) if r else None


def last_successful_run(session: Session, job: str) -> JobRunRecord | None:
    stmt = (
        select(JobRun)
        .where(JobRun.job == job, JobRun.status == "ok")
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    r = session.scalar(stmt)
    return _to_record(r) if r else None


def recent_failures(
    session: Session,
    *,
    now: str,
    days: int = 7,
    only_unacknowledged: bool = False,
) -> list[JobRunRecord]:
    """Return error/warn rows started within `days` of `now`, newest first."""
    cutoff = _shift_iso(now, days_delta=-days)
    stmt = (
        select(JobRun)
        .where(JobRun.status.in_(["error", "warn"]))
        .where(JobRun.started_at >= cutoff)
        .order_by(JobRun.started_at.desc())
    )
    if only_unacknowledged:
        stmt = stmt.where(JobRun.acknowledged_at.is_(None))
    return [_to_record(r) for r in session.scalars(stmt)]


def recent_alerts_of_kind(
    session: Session,
    *,
    error_kind: str,
    now: str,
    hours: int = 24,
) -> list[JobRunRecord]:
    cutoff = _shift_iso(now, hours_delta=-hours)
    stmt = (
        select(JobRun)
        .where(JobRun.error_kind == error_kind)
        .where(JobRun.started_at >= cutoff)
        .order_by(JobRun.started_at.desc())
    )
    return [_to_record(r) for r in session.scalars(stmt)]


def recent_runs_for_job(session: Session, job: str, *, limit: int = 100) -> list[JobRunRecord]:
    """Most-recent-first runs for a single job, capped at `limit`."""
    stmt = select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(limit)
    return [_to_record(r) for r in session.scalars(stmt)]


def _shift_iso(iso: str, *, days_delta: int = 0, hours_delta: int = 0) -> str:
    """Return iso shifted by the given delta. Centralized so callers don't reimplement parsing."""
    from datetime import datetime, timedelta

    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    out = dt + timedelta(days=days_delta, hours=hours_delta)
    return out.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
