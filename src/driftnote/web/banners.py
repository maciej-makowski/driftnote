"""Banner state derived from job_runs + disk_state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.repository.ingested import get_threshold_crossed_at
from driftnote.repository.jobs import last_successful_run, recent_failures


@dataclass(frozen=True)
class Banner:
    level: str  # 'error' | 'warn'
    message: str
    link: str | None = None


def compute_banners(engine: Engine, *, now: str) -> list[Banner]:
    out: list[Banner] = []

    with session_scope(engine) as session:
        unack = recent_failures(session, now=now, days=7, only_unacknowledged=True)
    if unack:
        out.append(
            Banner(
                level="error",
                message=f"{len(unack)} unacknowledged failure(s) in the last 7 days.",
                link="/admin",
            )
        )

    with session_scope(engine) as session:
        last_backup = last_successful_run(session, "backup")
    if last_backup is not None and _days_since(last_backup.started_at, now) > 35:
        out.append(
            Banner(
                level="warn", message="Last successful backup is older than 35 days.", link="/admin"
            )
        )

    with session_scope(engine) as session:
        warn_at = get_threshold_crossed_at(session, 80)
        alert_at = get_threshold_crossed_at(session, 95)
    if alert_at is not None:
        out.append(Banner(level="error", message="Disk usage above 95%.", link="/admin"))
    elif warn_at is not None:
        out.append(Banner(level="warn", message="Disk usage above 80%.", link="/admin"))

    return out


def _days_since(iso: str, now: str) -> float:
    a = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    b = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return (b - a).total_seconds() / 86400.0
