"""Disk-usage check job: measure usage, manage threshold-state edges, alert on crossing."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable

from sqlalchemy import Engine

from driftnote.alerts import AlertSender, dispatch_alert
from driftnote.db import session_scope
from driftnote.repository.ingested import (
    clear_threshold_crossed,
    get_threshold_crossed_at,
    record_threshold_crossed,
)
from driftnote.repository.jobs import finish_job_run, record_job_run

DiskMeasure = Callable[[str], tuple[int, int]]
"""Returns (used_bytes, total_bytes) for the given path. Defaults to shutil.disk_usage."""


def _default_measure(path: str) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.used, usage.total


async def run_disk_check(
    *,
    engine: Engine,
    sender: AlertSender,
    data_path: str,
    warn_percent: int,
    alert_percent: int,
    measure: DiskMeasure | None = None,
    now: str,
) -> None:
    measure_fn = measure or _default_measure
    used, total = measure_fn(data_path)
    percent = (used / total) * 100 if total else 0.0
    detail = json.dumps({"used_bytes": used, "total_bytes": total, "percent": round(percent, 2)})

    with session_scope(engine) as session:
        run_id = record_job_run(session, job="disk_check", started_at=now)

    try:
        await _maybe_alert(
            engine=engine,
            sender=sender,
            threshold=warn_percent,
            kind="disk_warn",
            percent=percent,
            used=used,
            total=total,
            now=now,
        )
        await _maybe_alert(
            engine=engine,
            sender=sender,
            threshold=alert_percent,
            kind="disk_alert",
            percent=percent,
            used=used,
            total=total,
            now=now,
        )
    except Exception as exc:
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=now,
                status="error",
                detail=detail,
                error_kind="disk_check",
                error_message=str(exc)[:2000],
            )
        raise

    with session_scope(engine) as session:
        finish_job_run(session, run_id=run_id, finished_at=now, status="ok", detail=detail)


async def _maybe_alert(
    *,
    engine: Engine,
    sender: AlertSender,
    threshold: int,
    kind: str,
    percent: float,
    used: int,
    total: int,
    now: str,
) -> None:
    with session_scope(engine) as session:
        prior = get_threshold_crossed_at(session, threshold)

    if percent >= threshold:
        if prior is not None:
            return  # already alerted; don't re-alert until the level drops below
        with session_scope(engine) as session:
            record_threshold_crossed(session, threshold=threshold, at=now)
        await dispatch_alert(
            engine=engine,
            sender=sender,
            kind=kind,
            subject=f"Driftnote disk usage at {percent:.1f}%",
            body=f"used={used}B total={total}B percent={percent:.1f}% threshold={threshold}%",
            now=now,
        )
    elif prior is not None:
        with session_scope(engine) as session:
            clear_threshold_crossed(session, threshold)
