"""Daily prompt job: render and send the prompt; record pending_prompts row."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as _date

from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.mail.smtp import send_email
from driftnote.mail.transport import SmtpTransport
from driftnote.repository.ingested import record_pending_prompt


async def run_prompt_job(
    *,
    engine: Engine,
    smtp: SmtpTransport,
    recipient: str,
    subject_template: str,
    body_template_text: str,
    today: _date,
) -> None:
    """Render the prompt for `today`, send it via SMTP, and persist the
    outgoing Message-ID as the date anchor for matching incoming replies."""
    iso = today.isoformat()
    subject = subject_template.format(date=iso)
    body = body_template_text.format(date=iso)

    message_id = await send_email(
        smtp,
        recipient=recipient,
        subject=subject,
        body_text=body,
    )

    with session_scope(engine) as session:
        record_pending_prompt(
            session,
            date=iso,
            message_id=message_id,
            sent_at=_iso_now_utc(),
        )


def _iso_now_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
