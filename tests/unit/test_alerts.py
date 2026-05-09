"""Tests for alert dispatch with 24h dedup."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.alerts import AlertSender, dispatch_alert
from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import finish_job_run, record_job_run


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


class _FakeSender(AlertSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []  # (kind, subject, body)

    async def send(self, *, kind: str, subject: str, body: str) -> None:
        self.sent.append((kind, subject, body))


def test_dispatch_alert_sends_first_time(engine: Engine) -> None:
    sender = _FakeSender()
    import asyncio

    asyncio.run(
        dispatch_alert(
            engine=engine,
            sender=sender,
            kind="imap_auth",
            subject="IMAP login failing",
            body="repeated failure",
            now="2026-05-06T20:00:00Z",
        )
    )
    assert sender.sent == [("imap_auth", "IMAP login failing", "repeated failure")]


def test_dispatch_alert_dedups_within_24h(engine: Engine) -> None:
    # Pre-populate a recent alert of the same kind.
    with session_scope(engine) as session:
        rid = record_job_run(session, job="alert", started_at="2026-05-06T08:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-05-06T08:00:01Z",
            status="error",
            error_kind="imap_auth",
            error_message="prior alert",
        )

    sender = _FakeSender()
    import asyncio

    asyncio.run(
        dispatch_alert(
            engine=engine,
            sender=sender,
            kind="imap_auth",
            subject="again",
            body="dup",
            now="2026-05-06T20:00:00Z",
        )
    )
    assert sender.sent == []  # deduped


def test_dispatch_alert_records_a_job_run_row(engine: Engine) -> None:
    sender = _FakeSender()
    import asyncio

    asyncio.run(
        dispatch_alert(
            engine=engine,
            sender=sender,
            kind="disk_warn",
            subject="disk 80%",
            body="...",
            now="2026-05-06T22:00:00Z",
        )
    )
    from driftnote.repository.jobs import last_run

    with session_scope(engine) as session:
        row = last_run(session, "alert")
    assert row is not None
    assert row.error_kind == "disk_warn"
    assert row.status == "ok"
