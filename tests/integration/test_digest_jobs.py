"""Integration test: digest jobs query DB, render HTML, send via SMTP."""

from __future__ import annotations

import asyncio
import imaplib
from datetime import date as _date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.mail.transport import SmtpTransport
from driftnote.repository.entries import EntryRecord, replace_tags, upsert_entry
from driftnote.scheduler.digest_jobs import (
    run_monthly_digest,
    run_weekly_digest,
    run_yearly_digest,
)
from tests.conftest import MailServer


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


@pytest.fixture
def engine_with_data(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        for d, mood, tags in [
            ("2026-04-27", "💪", ["work"]),
            ("2026-04-30", "🎉", ["birthday"]),
            ("2026-05-01", "☕", ["work", "rest"]),
        ]:
            upsert_entry(
                session,
                EntryRecord(
                    date=d,
                    mood=mood,
                    body_text="t",
                    body_md="t",
                    created_at="t",
                    updated_at="t",
                ),
            )
            replace_tags(session, d, tags)
    return eng


@pytest.fixture(autouse=True)
def _clean_mailbox(mail_server: MailServer) -> None:
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    try:
        mb.select("INBOX")
        mb.store("1:*", "+FLAGS", r"\Deleted")
        mb.expunge()
    except Exception:  # noqa: S110
        pass  # mailbox may be empty; ignore
    mb.logout()


def _last_subject(mail_server: MailServer) -> bytes:
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select("INBOX")
    _typ, data = mb.search(None, "ALL")
    ids = data[0].split()
    _typ, hdr = mb.fetch(ids[-1], "(BODY[HEADER.FIELDS (SUBJECT)])")
    mb.logout()
    return hdr[0][1]  # type: ignore[index,return-value]


def test_weekly_digest_sends(mail_server: MailServer, engine_with_data: Engine) -> None:
    asyncio.run(
        run_weekly_digest(
            engine=engine_with_data,
            smtp=_smtp(mail_server),
            recipient=mail_server.address,
            week_start=_date(2026, 4, 27),
            web_base_url="https://x",
        )
    )
    assert b"Week of 2026-04-27" in _last_subject(mail_server)


def test_monthly_digest_sends(mail_server: MailServer, engine_with_data: Engine) -> None:
    asyncio.run(
        run_monthly_digest(
            engine=engine_with_data,
            smtp=_smtp(mail_server),
            recipient=mail_server.address,
            year=2026,
            month=4,
            web_base_url="https://x",
        )
    )
    assert b"April 2026" in _last_subject(mail_server)


def test_yearly_digest_sends(mail_server: MailServer, engine_with_data: Engine) -> None:
    asyncio.run(
        run_yearly_digest(
            engine=engine_with_data,
            smtp=_smtp(mail_server),
            recipient=mail_server.address,
            year=2026,
            web_base_url="https://x",
        )
    )
    assert b"2026 in review" in _last_subject(mail_server)
