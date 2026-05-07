"""Integration test: the daily prompt job sends a prompt and records pending_prompts."""

from __future__ import annotations

import asyncio
from datetime import date as _date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.mail.transport import SmtpTransport
from driftnote.repository.ingested import find_prompt_by_message_id
from driftnote.scheduler.prompt_job import run_prompt_job
from tests.conftest import MailServer


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def _smtp(mail_server: MailServer) -> SmtpTransport:
    return SmtpTransport(
        host=mail_server.host,
        port=mail_server.smtp_port,
        tls=False,
        starttls=False,
        username=mail_server.user,
        password=mail_server.password,
        sender_address=mail_server.address,
        sender_name="Driftnote",
    )


def test_run_prompt_job_sends_and_anchors(mail_server: MailServer, engine: Engine) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        run_prompt_job(
            engine=engine,
            smtp=smtp,
            recipient=mail_server.address,
            subject_template="[Driftnote] How was {date}?",
            body_template_text="Hi! Reply with `Mood: <emoji>` and your day. — {date}",
            today=_date(2026, 5, 6),
        )
    )
    with session_scope(engine) as session:
        # We don't know the message-id ahead of time; look up by date instead.
        from sqlalchemy import select

        from driftnote.models import PendingPrompt

        rec = session.scalar(select(PendingPrompt).where(PendingPrompt.date == "2026-05-06"))
    assert rec is not None
    msg_id = rec.message_id
    found = _find_prompt_by_message_id(engine, msg_id)
    assert found is not None
    assert found.date == "2026-05-06"


def _find_prompt_by_message_id(engine: Engine, mid: str):  # type: ignore[return]
    with session_scope(engine) as session:
        return find_prompt_by_message_id(session, mid)
