"""Integration test: poll job fetches UNSEEN, ingests, then moves to Processed."""

from __future__ import annotations

import asyncio
import contextlib
import imaplib
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.mail.transport import ImapTransport
from driftnote.repository.entries import get_entry
from driftnote.repository.ingested import (
    get_ingested,
    record_pending_prompt,
)
from driftnote.scheduler.poll_job import run_poll_job
from tests.conftest import MailServer


def _imap(mail_server: MailServer) -> ImapTransport:
    return ImapTransport(
        host=mail_server.host,
        port=mail_server.imap_port,
        tls=False,
        username=mail_server.user,
        password=mail_server.password,
        inbox_folder="INBOX",
        processed_folder="INBOX.Processed",
    )


def _drop_reply(mail_server: MailServer, *, in_reply_to: str | None, body: str) -> str:
    msg = EmailMessage()
    msg["From"] = mail_server.address
    msg["To"] = mail_server.address
    msg["Subject"] = "Re: [Driftnote] How was 2026-05-06?"
    msg["Message-ID"] = make_msgid(domain="example")
    msg["Date"] = "Wed, 06 May 2026 21:30:15 +0000"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)

    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.append("INBOX", "", imaplib.Time2Internaldate(0), msg.as_bytes())
    mb.logout()
    return msg["Message-ID"]


@pytest.fixture(autouse=True)
def _clean_mailbox(mail_server: MailServer):  # type: ignore[return]
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    for folder in ("INBOX", "INBOX.Processed"):
        with contextlib.suppress(Exception):
            mb.select(folder)
            mb.store("1:*", "+FLAGS", r"\Deleted")
            mb.expunge()
    with contextlib.suppress(Exception):
        mb.create("INBOX.Processed")
    mb.logout()


@pytest.fixture
def engine_data(tmp_path: Path) -> tuple[Engine, Path]:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    return eng, tmp_path / "data"


def _make_config(mail_server: MailServer, data_root: Path):  # type: ignore[return]
    from pydantic import SecretStr

    from driftnote.config import (
        BackupConfig,
        Config,
        DigestsConfig,
        DiskConfig,
        EmailConfig,
        ParsingConfig,
        PromptConfig,
        ScheduleConfig,
        Secrets,
    )

    return Config(
        schedule=ScheduleConfig(
            daily_prompt="0 21 * * *",
            weekly_digest="0 8 * * 1",
            monthly_digest="0 8 1 * *",
            yearly_digest="0 8 1 1 *",
            imap_poll="*/5 * * * *",
            timezone="Europe/London",
        ),
        email=EmailConfig(
            imap_folder="INBOX",
            imap_processed_folder="INBOX.Processed",
            recipient=mail_server.address,
            sender_name="Driftnote",
            imap_host=mail_server.host,
            imap_port=mail_server.imap_port,
            imap_tls=False,
            smtp_host="x",
            smtp_port=587,
            smtp_tls=False,
            smtp_starttls=False,
        ),
        prompt=PromptConfig(subject_template="x", body_template="t.j2"),
        parsing=ParsingConfig(
            mood_regex=r"^\s*Mood:\s*(\S+)",
            tag_regex=r"#(\w+)",
            max_photos=4,
            max_videos=2,
        ),
        digests=DigestsConfig(weekly_enabled=True, monthly_enabled=True, yearly_enabled=True),
        backup=BackupConfig(retain_months=12, encrypt=False, age_key_path=""),
        disk=DiskConfig(
            warn_percent=80,
            alert_percent=95,
            check_cron="0 */6 * * *",
            data_path=str(data_root),
        ),
        secrets=Secrets(
            gmail_user=mail_server.user,
            gmail_app_password=SecretStr(mail_server.password),
            cf_access_aud="aud",
            cf_team_domain="t.example.com",
        ),
    )


def test_poll_ingests_message_and_moves_to_processed(
    mail_server: MailServer, engine_data: tuple[Engine, Path]
) -> None:
    engine, data_root = engine_data
    with session_scope(engine) as session:
        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="2026-05-06T21:00:00Z",
        )
    mid = _drop_reply(
        mail_server,
        in_reply_to="<prompt-2026-05-06@driftnote>",
        body="Mood: 💪\n\nGood day. #work",
    )

    cfg = _make_config(mail_server, data_root)
    asyncio.run(
        run_poll_job(config=cfg, engine=engine, data_root=data_root, imap=_imap(mail_server))
    )

    with session_scope(engine) as session:
        entry = get_entry(session, "2026-05-06")
        ing = get_ingested(session, mid)
    assert entry is not None
    assert ing is not None
    assert ing.imap_moved == 1

    # Message has moved out of Inbox into Processed.
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select("INBOX")
    _typ, data = mb.search(None, "ALL")
    assert data == [b""]  # empty INBOX
    mb.select("INBOX.Processed")
    _typ, data = mb.search(None, "ALL")
    assert data and data[0]
    mb.logout()


def test_poll_retries_imap_move_on_imap_moved_zero(
    mail_server: MailServer,
    engine_data: tuple[Engine, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a previous poll ingested but failed to move, the next poll should
    retry only the IMAP move without re-ingesting."""
    engine, data_root = engine_data
    with session_scope(engine) as session:
        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="t",
        )
    _drop_reply(
        mail_server,
        in_reply_to="<prompt-2026-05-06@driftnote>",
        body="Mood: 💪\n\nrecovered #work",
    )

    # First call: succeed at ingest, simulate failure on move.
    from driftnote.scheduler import poll_job as _poll

    async def _fail_move(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated IMAP move failure")

    real_move = _poll._move_to_processed
    monkeypatch.setattr(_poll, "_move_to_processed", _fail_move)

    cfg = _make_config(mail_server, data_root)

    with pytest.raises(RuntimeError):
        asyncio.run(
            run_poll_job(config=cfg, engine=engine, data_root=data_root, imap=_imap(mail_server))
        )

    # imap_moved still 0
    with session_scope(engine) as session:
        from driftnote.repository.ingested import pending_imap_moves

        pending = pending_imap_moves(session)
    assert len(pending) == 1

    # Second call: restore real move, message should be moved without re-ingesting.
    monkeypatch.setattr(_poll, "_move_to_processed", real_move)
    asyncio.run(
        run_poll_job(config=cfg, engine=engine, data_root=data_root, imap=_imap(mail_server))
    )

    with session_scope(engine) as session:
        from driftnote.repository.ingested import pending_imap_moves

        pending = pending_imap_moves(session)
    assert pending == []
