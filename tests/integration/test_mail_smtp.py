"""Integration test: SMTP send via GreenMail."""

from __future__ import annotations

import asyncio
import imaplib

from driftnote.mail.smtp import Attachment, send_email
from driftnote.mail.transport import SmtpTransport
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


def _fetch_via_imap(mail_server: MailServer) -> bytes:
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select("INBOX")
    typ, data = mb.search(None, "ALL")
    assert typ == "OK"
    ids = data[0].split()
    assert ids, "no message in INBOX"
    typ, msg_data = mb.fetch(ids[-1], "(RFC822)")
    assert typ == "OK"
    raw = msg_data[0][1]  # type: ignore[index]
    mb.logout()
    return raw  # type: ignore[return-value]


def test_send_plain_email(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    msg_id = asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="hi",
            body_text="hello there",
        )
    )
    assert msg_id.startswith("<") and msg_id.endswith(">")
    raw = _fetch_via_imap(mail_server)
    assert b"Subject: hi" in raw
    assert b"hello there" in raw
    assert msg_id.encode() in raw


def test_send_with_in_reply_to(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="re: weekly",
            body_text="thread reply",
            in_reply_to="<original-prompt-id@driftnote>",
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"In-Reply-To: <original-prompt-id@driftnote>" in raw
    assert b"References: <original-prompt-id@driftnote>" in raw


def test_send_with_html_alternative(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="alt",
            body_text="plain version",
            body_html="<p>HTML version</p>",
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"multipart/alternative" in raw
    assert b"plain version" in raw
    assert b"<p>HTML version</p>" in raw


def test_send_with_attachment(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="with photo",
            body_text="see attached",
            attachments=[
                Attachment(
                    filename="photo.jpg", content=b"\xff\xd8\xffJPEG-bytes", mime_type="image/jpeg"
                )
            ],
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"photo.jpg" in raw
    assert b"image/jpeg" in raw


def test_send_with_inline_image_cid(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="cid",
            body_text="see body",
            body_html='<img src="cid:photo1@driftnote">',
            attachments=[
                Attachment(
                    filename="photo.jpg",
                    content=b"jpegbytes",
                    mime_type="image/jpeg",
                    content_id="<photo1@driftnote>",
                    inline=True,
                )
            ],
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"Content-ID: <photo1@driftnote>" in raw
    assert b"Content-Disposition: inline" in raw


def test_send_with_reply_to_header(mail_server: MailServer) -> None:
    """When the transport carries a reply_to, the outgoing message has Reply-To set."""
    smtp = SmtpTransport(
        host=mail_server.host,
        port=mail_server.smtp_port,
        tls=False,
        starttls=False,
        username=mail_server.user,
        password=mail_server.password,
        sender_address=mail_server.address,
        sender_name="Driftnote",
        reply_to=f"you+driftnote@{mail_server.address.split('@', 1)[-1]}",
    )
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="reply-to",
            body_text="testing",
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"Reply-To: you+driftnote@" in raw, "Reply-To header expected on outgoing message"


def test_send_without_reply_to_omits_header(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)  # default transport: reply_to=None
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="no-reply-to",
            body_text="testing",
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"Reply-To:" not in raw
