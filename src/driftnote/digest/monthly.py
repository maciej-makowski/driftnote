"""Monthly digest builder.

Subject: `[Driftnote] Month YYYY` (e.g. "[Driftnote] May 2026")
Body:
- Calendar-grid moodboard.
- Stats line: count of entries, top mood, top tags.
- Up to 6 highlight days, target minimum 4. Selection is progressive:
  1) days with a photo AND at least one rare tag (used <3x this month);
  2) days with photo OR rare tag;
  3) days with the most photos (proxied by photo_thumb being non-null).
- Link to web UI.
"""

from __future__ import annotations

import re
from collections import Counter
from html import escape

from driftnote.digest.inputs import DayInput, HighlightInput
from driftnote.digest.moodboard import MonthlyCell, monthly_moodboard_grid
from driftnote.digest.weekly import Digest

_MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def select_highlights(days: list[DayInput], *, target: int = 4) -> list[HighlightInput]:
    if not days:
        return []
    tag_counts: Counter[str] = Counter()
    for d in days:
        tag_counts.update(d.tags)
    rare_tags = {t for t, c in tag_counts.items() if c < 3}

    def _has_photo(d: DayInput) -> bool:
        return d.photo_thumb is not None

    def _has_rare_tag(d: DayInput) -> bool:
        return any(t in rare_tags for t in d.tags)

    pass1 = [d for d in days if _has_photo(d) and _has_rare_tag(d)]
    if len(pass1) >= target:
        chosen = pass1
    else:
        pass2 = [d for d in days if _has_photo(d) or _has_rare_tag(d)]
        if len(pass2) >= target:
            chosen = pass2
        else:
            with_photo = [d for d in days if _has_photo(d)]
            chosen = with_photo if with_photo else days

    chosen = sorted(chosen, key=lambda d: d.date)[:target]
    return [
        HighlightInput(
            date=d.date,
            mood=d.mood,
            summary_html=_first_n_sentences(d.body_html, 2),
            photo_thumb=d.photo_thumb,
        )
        for d in chosen
    ]


def build_monthly_digest(
    *,
    year: int,
    month: int,
    days: list[DayInput],
    web_base_url: str,
) -> Digest:
    name = _MONTH_NAMES[month]
    subject = f"[Driftnote] {name} {year}"

    cells = monthly_moodboard_grid(year=year, month=month, days=days)
    grid_html = "".join(_row_html(row) for row in cells)

    moods: Counter[str] = Counter(d.mood for d in days if d.mood)
    tags: Counter[str] = Counter(t for d in days for t in d.tags)
    top_mood = moods.most_common(1)
    top_tags = tags.most_common(3)
    stats_html = (
        f"<p><strong>Stats:</strong> {len(days)} entries"
        + (f" • top emoji {escape(top_mood[0][0])} ({top_mood[0][1]})" if top_mood else "")
        + (" • top tags " + ", ".join(f"#{escape(t)}" for t, _ in top_tags) if top_tags else "")
        + "</p>"
    )

    highlights_html = "".join(
        _render_highlight(h, web_base_url=web_base_url) for h in select_highlights(days)
    )

    body_html = (
        f'<html><body style="font-family:system-ui,sans-serif;max-width:640px;margin:auto;padding:16px">\n'
        f"  <h1>{escape(name)} {year}</h1>\n"
        f'  <table cellspacing="0" cellpadding="2" style="border-collapse:collapse;margin:8px 0 16px">\n'
        f"    {grid_html}\n"
        f"  </table>\n"
        f"  {stats_html}\n"
        f"  {highlights_html}\n"
        f'  <p style="margin-top:24px;color:#888"><a href="{escape(web_base_url)}">Open in Driftnote</a></p>\n'
        f"</body></html>"
    )
    return Digest(subject=subject, html=body_html)


def _row_html(row: list[MonthlyCell]) -> str:
    return (
        "<tr>"
        + "".join(
            f'<td style="text-align:center;width:32px;height:32px;'
            f'color:{"#222" if c.in_month else "#ccc"};font-size:18px">'
            f"{escape(c.emoji or ('·' if c.in_month else ''))}"
            f"</td>"
            for c in row
        )
        + "</tr>"
    )


def _render_highlight(h: HighlightInput, *, web_base_url: str) -> str:
    thumb_html = (
        f'<img src="{escape(h.photo_thumb)}" style="max-width:100%;border-radius:8px"/>'
        if h.photo_thumb
        else ""
    )
    return (
        f'<section style="margin:16px 0;padding-top:12px;border-top:1px solid #eee">'
        f'<h3 style="margin:0">'
        f'<a href="{escape(web_base_url)}/entry/{escape(h.date.isoformat())}" style="color:#222;text-decoration:none">'
        f'{escape(h.date.isoformat())} <span style="font-size:20px">{escape(h.mood or "")}</span>'
        f"</a></h3>"
        f"{h.summary_html}"
        f"{thumb_html}"
        f"</section>"
    )


def _first_n_sentences(html: str, n: int) -> str:
    """Naive sentence trim: split on `. `, take first n, retain HTML wrapper."""
    text = re.sub(r"<[^>]+>", "", html).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    snippet = " ".join(parts[:n])
    return f"<p>{escape(snippet)}</p>"
