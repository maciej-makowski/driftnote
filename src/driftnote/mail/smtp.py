"""Async SMTP send. Builds a MIME message and dispatches via aiosmtplib.

Returns the outgoing Message-ID so callers can persist it (e.g. as the
prompt's anchor for matching incoming replies).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import aiosmtplib

from driftnote.mail.transport import SmtpTransport


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes
    mime_type: str  # e.g. "image/jpeg"
    content_id: str | None = None  # set + inline=True for CID-referenced inline images
    inline: bool = False


async def send_email(
    transport: SmtpTransport,
    *,
    recipient: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    attachments: list[Attachment] | None = None,
    in_reply_to: str | None = None,
) -> str:
    """Send an email and return the generated Message-ID (including angle brackets)."""
    msg = EmailMessage()
    msg["From"] = formataddr((transport.sender_name, transport.sender_address))
    msg["To"] = recipient
    if transport.reply_to:
        msg["Reply-To"] = transport.reply_to
    msg["Subject"] = subject
    msg["Date"] = formatdate(time.time(), localtime=True)
    domain = transport.sender_address.split("@", 1)[-1] or "driftnote"
    message_id = make_msgid(idstring=secrets.token_hex(8), domain=domain)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    for att in attachments or []:
        maintype, _, subtype = att.mime_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        if att.inline and att.content_id:
            msg.add_attachment(
                att.content,
                maintype=maintype,
                subtype=subtype,
                filename=att.filename,
                disposition="inline",
                cid=att.content_id,
            )
        else:
            msg.add_attachment(
                att.content,
                maintype=maintype,
                subtype=subtype,
                filename=att.filename,
            )

    await aiosmtplib.send(
        msg,
        hostname=transport.host,
        port=transport.port,
        use_tls=transport.tls,
        start_tls=transport.starttls,
        username=transport.username if transport.username else None,
        password=transport.password if transport.password else None,
    )
    return message_id
