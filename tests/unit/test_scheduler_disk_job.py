"""Tests for disk-usage threshold tracking + alert triggering."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.alerts import AlertSender
from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.ingested import (
    get_threshold_crossed_at,
    record_threshold_crossed,
)
from driftnote.repository.jobs import last_run
from driftnote.scheduler.disk_job import run_disk_check


class _FakeSender(AlertSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, *, kind: str, subject: str, body: str) -> None:
        self.sent.append((kind, subject, body))


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def test_disk_check_no_alert_below_warn(engine: Engine) -> None:
    sender = _FakeSender()
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (1_000, 5_000),  # 20% used
            now="2026-05-06T22:00:00Z",
        )
    )
    assert sender.sent == []


def test_disk_check_alerts_on_warn_crossing(engine: Engine) -> None:
    sender = _FakeSender()
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (8_500, 10_000),  # 85%
            now="2026-05-06T22:00:00Z",
        )
    )
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == "disk_warn"


def test_disk_check_does_not_realert_after_warn_already_crossed(engine: Engine) -> None:
    sender = _FakeSender()
    with session_scope(engine) as session:
        record_threshold_crossed(session, threshold=80, at="2026-05-05T08:00:00Z")
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (8_500, 10_000),
            now="2026-05-06T22:00:00Z",
        )
    )
    assert sender.sent == []


def test_disk_check_clears_warn_state_after_drop_below(engine: Engine) -> None:
    sender = _FakeSender()
    with session_scope(engine) as session:
        record_threshold_crossed(session, threshold=80, at="2026-05-05T08:00:00Z")
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (5_000, 10_000),
            now="2026-05-06T22:00:00Z",
        )
    )
    with session_scope(engine) as session:
        assert get_threshold_crossed_at(session, 80) is None


def test_disk_check_records_job_run_with_detail(engine: Engine) -> None:
    sender = _FakeSender()
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (8_500, 10_000),
            now="2026-05-06T22:00:00Z",
        )
    )
    with session_scope(engine) as session:
        row = last_run(session, "disk_check")
    assert row is not None
    assert row.status == "ok"
    assert row.detail is not None
    assert "8500" in row.detail
    assert "10000" in row.detail
