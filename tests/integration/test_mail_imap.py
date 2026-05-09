"""Integration test: IMAP poll + move via GreenMail."""

from __future__ import annotations

import asyncio
import contextlib
import imaplib
from email.message import EmailMessage
from email.utils import make_msgid

import pytest

from driftnote.mail.imap import RawMessage, move_to_processed, poll_unseen
from driftnote.mail.transport import ImapTransport
from tests.conftest import MailServer


def _imap(
    mail_server: MailServer, *, inbox: str = "INBOX", processed: str = "INBOX.Processed"
) -> ImapTransport:
    return ImapTransport(
        host=mail_server.host,
        port=mail_server.imap_port,
        tls=False,
        username=mail_server.user,
        password=mail_server.password,
        inbox_folder=inbox,
        processed_folder=processed,
    )


def _drop_into_inbox(
    mail_server: MailServer, *, subject: str, message_id: str | None = None
) -> str:
    """Use raw IMAP APPEND to inject a test message into the user's INBOX."""
    msg = EmailMessage()
    msg["From"] = mail_server.address
    msg["To"] = mail_server.address
    msg["Subject"] = subject
    if message_id is None:
        message_id = make_msgid(domain="driftnote")
    msg["Message-ID"] = message_id
    msg.set_content("body of " + subject)

    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.append("INBOX", "", imaplib.Time2Internaldate(0), msg.as_bytes())
    mb.logout()
    return message_id


def _list_inbox_subjects(mail_server: MailServer, folder: str = "INBOX") -> list[bytes]:
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select(folder)
    _typ, data = mb.search(None, "ALL")
    out: list[bytes] = []
    for ident in data[0].split():
        _typ, hdr = mb.fetch(ident, "(BODY[HEADER.FIELDS (SUBJECT)])")
        out.append(hdr[0][1])  # type: ignore[index,arg-type]
    mb.logout()
    return out


@pytest.fixture(autouse=True)
def _clean_mailbox(mail_server: MailServer) -> None:
    """Empty INBOX + Processed before each test so order-dependent ones don't leak state."""
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    for folder in ("INBOX", "INBOX.Processed"):
        with contextlib.suppress(Exception):
            mb.select(folder)
            mb.store("1:*", "+FLAGS", r"\Deleted")
            mb.expunge()
    # Ensure Processed exists (GreenMail auto-creates on append, but explicit create is safer).
    with contextlib.suppress(Exception):
        mb.create("INBOX.Processed")
    mb.logout()


def test_poll_unseen_returns_raw_messages(mail_server: MailServer) -> None:
    msg_id = _drop_into_inbox(mail_server, subject="hello driftnote")
    transport = _imap(mail_server)
    messages: list[RawMessage] = asyncio.run(_collect(transport))
    assert len(messages) == 1
    assert messages[0].message_id == msg_id
    assert b"Subject: hello driftnote" in messages[0].raw_bytes


def test_poll_skips_already_seen_messages(mail_server: MailServer) -> None:
    _drop_into_inbox(mail_server, subject="first")
    transport = _imap(mail_server)
    asyncio.run(_collect(transport))  # first poll marks them \Seen
    second = asyncio.run(_collect(transport))
    assert second == []


def test_move_to_processed(mail_server: MailServer) -> None:
    msg_id = _drop_into_inbox(mail_server, subject="movable")
    transport = _imap(mail_server)
    asyncio.run(move_to_processed(transport, message_id=msg_id))
    inbox = _list_inbox_subjects(mail_server, "INBOX")
    processed = _list_inbox_subjects(mail_server, "INBOX.Processed")
    assert all(b"movable" not in s for s in inbox)
    assert any(b"movable" in s for s in processed)


async def _collect(transport: ImapTransport) -> list[RawMessage]:
    out: list[RawMessage] = []
    async for msg in poll_unseen(transport):
        out.append(msg)
    return out
