"""Weekly digest body builder.

Produces a `Digest(subject, html)` with:
- 7-emoji moodboard row at the top
- One section per day in chronological order with mood, tags, body HTML, optional thumbnail
- Footer with link to the web UI
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from driftnote.digest.inputs import DayInput
from driftnote.digest.moodboard import weekly_moodboard


@dataclass(frozen=True)
class Digest:
    subject: str
    html: str


def build_weekly_digest(
    *,
    week_start: date,
    days: list[DayInput],
    web_base_url: str,
) -> Digest:
    week_end = week_start + timedelta(days=6)
    subject = f"[Driftnote] Week of {week_start.isoformat()} → {week_end.isoformat()}"

    cells = weekly_moodboard(week_start=week_start, days=days)
    moodboard_html = "".join(
        f'<td style="text-align:center;padding:6px;font-size:24px">'
        f'<div style="font-size:11px;color:#888">{escape(c.label)}</div>'
        f"<div>{escape(c.emoji or '·')}</div>"
        f"</td>"
        for c in cells
    )

    days_sorted = sorted(days, key=lambda d: d.date)
    sections_html = "".join(_render_day_section(d, web_base_url=web_base_url) for d in days_sorted)

    footer_html = (
        f'<p style="margin-top:24px;color:#888">'
        f'<a href="{escape(web_base_url)}">Open in Driftnote</a></p>'
    )

    body_html = (
        f'<html><body style="font-family:system-ui,sans-serif;max-width:640px;margin:auto;padding:16px">\n'
        f'  <h1 style="margin-bottom:8px">Week of {escape(week_start.isoformat())} → {escape(week_end.isoformat())}</h1>\n'
        f'  <table cellspacing="0" cellpadding="0" style="margin:8px 0 24px"><tr>{moodboard_html}</tr></table>\n'
        f"  {sections_html}\n"
        f"  {footer_html}\n"
        f"</body></html>"
    )

    return Digest(subject=subject, html=body_html)


def _render_day_section(d: DayInput, *, web_base_url: str) -> str:
    mood = escape(d.mood) if d.mood else ""
    tags = " ".join(
        f'<span style="color:#888;margin-right:6px">#{escape(t)}</span>' for t in d.tags
    )
    thumb_html = (
        f'<img src="{escape(d.photo_thumb)}" style="max-width:100%;border-radius:8px;margin-top:8px"/>'
        if d.photo_thumb
        else ""
    )
    return (
        f'<section style="margin:16px 0;padding-top:12px;border-top:1px solid #eee">\n'
        f'  <h2 style="margin:0">\n'
        f'    <a href="{escape(web_base_url)}/entry/{escape(d.date.isoformat())}" style="color:#222;text-decoration:none">\n'
        f'      {escape(d.date.isoformat())} <span style="font-size:24px">{mood}</span>\n'
        f"    </a>\n"
        f"  </h2>\n"
        f'  <p style="margin:4px 0 8px">{tags}</p>\n'
        f"  <div>{d.body_html}</div>\n"
        f"  {thumb_html}\n"
        f"</section>"
    )
