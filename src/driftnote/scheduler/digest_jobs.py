"""Wire digest renderers into SMTP send. The scheduler module-level functions are
called by APScheduler once Chunk 10 wires them in via cron triggers."""

from __future__ import annotations

import re
from datetime import date as _date
from datetime import timedelta

from sqlalchemy import Engine

from driftnote.digest.monthly import build_monthly_digest
from driftnote.digest.queries import days_in_range
from driftnote.digest.weekly import build_weekly_digest
from driftnote.digest.yearly import build_yearly_digest
from driftnote.mail.smtp import send_email
from driftnote.mail.transport import SmtpTransport


async def run_weekly_digest(
    *,
    engine: Engine,
    smtp: SmtpTransport,
    recipient: str,
    week_start: _date,
    web_base_url: str,
) -> None:
    week_end = week_start + timedelta(days=6)
    days = days_in_range(engine, start=week_start, end=week_end)
    digest = build_weekly_digest(week_start=week_start, days=days, web_base_url=web_base_url)
    await send_email(
        smtp,
        recipient=recipient,
        subject=digest.subject,
        body_text=_html_to_text(digest.html),
        body_html=digest.html,
    )


async def run_monthly_digest(
    *,
    engine: Engine,
    smtp: SmtpTransport,
    recipient: str,
    year: int,
    month: int,
    web_base_url: str,
) -> None:
    start = _date(year, month, 1)
    end = _date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    days = days_in_range(engine, start=start, end=end)
    digest = build_monthly_digest(year=year, month=month, days=days, web_base_url=web_base_url)
    await send_email(
        smtp,
        recipient=recipient,
        subject=digest.subject,
        body_text=_html_to_text(digest.html),
        body_html=digest.html,
    )


async def run_yearly_digest(
    *,
    engine: Engine,
    smtp: SmtpTransport,
    recipient: str,
    year: int,
    web_base_url: str,
) -> None:
    start = _date(year, 1, 1)
    end = _date(year, 12, 31)
    days = days_in_range(engine, start=start, end=end)
    digest = build_yearly_digest(year=year, days=days, web_base_url=web_base_url)
    await send_email(
        smtp,
        recipient=recipient,
        subject=digest.subject,
        body_text=_html_to_text(digest.html),
        body_html=digest.html,
    )


def _html_to_text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()
