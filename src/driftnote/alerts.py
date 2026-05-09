"""Self-emailing alerts with 24h dedup keyed on `error_kind`.

Callers pass an `AlertSender` so tests can substitute an in-memory fake while
production wires in an SMTP-backed sender.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.repository.jobs import (
    finish_job_run,
    recent_alerts_of_kind,
    record_job_run,
)


class AlertSender(Protocol):
    async def send(self, *, kind: str, subject: str, body: str) -> None: ...


async def dispatch_alert(
    *,
    engine: Engine,
    sender: AlertSender,
    kind: str,
    subject: str,
    body: str,
    now: str,
) -> None:
    """Send an alert email, deduplicated against any prior alert of the same `kind`
    within the last 24 hours. Always records a job_runs row with job='alert'."""
    with session_scope(engine) as session:
        recent = recent_alerts_of_kind(session, error_kind=kind, now=now, hours=24)

    run_id: int
    with session_scope(engine) as session:
        run_id = record_job_run(session, job="alert", started_at=now)

    if recent:
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=now,
                status="ok",
                detail="deduped",
                error_kind=kind,
            )
        return

    try:
        await sender.send(kind=kind, subject=subject, body=body)
    except Exception as exc:
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=now,
                status="error",
                error_kind=kind,
                error_message=str(exc)[:2000],
            )
        raise

    with session_scope(engine) as session:
        finish_job_run(
            session,
            run_id=run_id,
            finished_at=now,
            status="ok",
            detail="sent",
            error_kind=kind,
        )
