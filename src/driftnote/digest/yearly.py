"""Yearly digest builder.

Body:
- 7x~53 contribution-grid moodboard
- Stats: total entries, longest streak, top 10 emojis, top 10 tags
- One photo per month (most-tagged day's first photo, fallback any photo)
- Link to web UI
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from datetime import date, timedelta
from html import escape

from driftnote.digest.inputs import DayInput
from driftnote.digest.moodboard import yearly_moodboard_grid
from driftnote.digest.weekly import Digest


def build_yearly_digest(*, year: int, days: list[DayInput], web_base_url: str) -> Digest:
    subject = f"[Driftnote] {year} in review"

    grid = yearly_moodboard_grid(year=year, days=days)
    grid_html = "<table cellspacing='1' cellpadding='0' style='border-collapse:separate'>"
    for row in grid:
        grid_html += (
            "<tr>"
            + "".join(
                f'<td style="width:14px;height:14px;font-size:11px;text-align:center;'
                f'color:{"#222" if c.in_year else "#ddd"}">{escape(c.emoji or "")}</td>'
                for c in row
            )
            + "</tr>"
        )
    grid_html += "</table>"

    moods: Counter[str] = Counter(d.mood for d in days if d.mood)
    tags: Counter[str] = Counter(t for d in days for t in d.tags)
    top10_moods = ", ".join(f"{escape(m)} ({n})" for m, n in moods.most_common(10))
    top10_tags = ", ".join(f"#{escape(t)} ({n})" for t, n in tags.most_common(10))
    streak = _longest_streak({d.date for d in days})

    stats_html = (
        f"<p><strong>Stats</strong>: {len(days)} entries • longest streak {streak} days<br>"
        f"Top emojis: {top10_moods}<br>"
        f"Top tags: {top10_tags}</p>"
    )

    monthly_photos = _one_photo_per_month(days)
    photo_strip = "".join(
        f'<img src="{escape(thumb)}" style="max-width:100px;border-radius:6px;margin:4px"/>'
        for thumb in monthly_photos.values()
    )

    body_html = (
        f'<html><body style="font-family:system-ui,sans-serif;max-width:640px;margin:auto;padding:16px">\n'
        f"  <h1>{year} in review</h1>\n"
        f"  {grid_html}\n"
        f"  {stats_html}\n"
        f"  <p>{photo_strip}</p>\n"
        f'  <p style="margin-top:24px;color:#888"><a href="{escape(web_base_url)}">Open in Driftnote</a></p>\n'
        f"</body></html>"
    )
    return Digest(subject=subject, html=body_html)


def _longest_streak(dates: set[date]) -> int:
    if not dates:
        return 0
    sorted_dates = sorted(dates)
    longest = 1
    cur = 1
    for prev, nxt in itertools.pairwise(sorted_dates):
        if nxt == prev + timedelta(days=1):
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 1
    return longest


def _one_photo_per_month(days: list[DayInput]) -> dict[int, str]:
    """Return a month-keyed dict of thumbnail URLs, in month order (1..12)."""
    grouped: dict[int, list[DayInput]] = defaultdict(list)
    for d in days:
        if d.photo_thumb is None:
            continue
        grouped[d.date.month].append(d)
    by_month: dict[int, str] = {}
    for month in sorted(grouped.keys()):
        ds_sorted = sorted(grouped[month], key=lambda x: (-len(x.tags), x.date))
        by_month[month] = ds_sorted[0].photo_thumb  # type: ignore[assignment]
    return by_month
