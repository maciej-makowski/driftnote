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

# Polished light palette for the email digest. Intentionally not shared with
# the web UI's dark CSS variables — emails inline their styles and live in
# light-default inboxes (Gmail, Apple Mail). Visual coherence comes from the
# shared accent family (purple), not from shared tokens. See
# docs/superpowers/specs/2026-05-09-issue-4-dark-redesign-design.md.
_DIGEST_PALETTE: dict[str, str] = {
    "bg": "#ffffff",
    "bg_raised": "#f7f6fb",
    "fg": "#1f1d2b",
    "fg_muted": "#6c6a78",
    "fg_dim": "#c4c2cc",
    "accent": "#6c4fc4",
    "border": "#e5e4ed",
}


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
    p = _DIGEST_PALETTE
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
        f'<html><body style="font-family:system-ui,sans-serif;max-width:640px;margin:auto;'
        f'padding:16px;background:{p["bg"]};color:{p["fg"]}">\n'
        f'  <h1 style="font-size:24px;font-weight:600;margin:0 0 12px">{escape(name)} {year}</h1>\n'
        f'  <table cellspacing="0" cellpadding="2" '
        f'style="border-collapse:collapse;margin:8px 0 16px;background:{p["bg_raised"]}">\n'
        f"    {grid_html}\n"
        f"  </table>\n"
        f"  {stats_html}\n"
        f"  {highlights_html}\n"
        f'  <p style="margin-top:24px"><a href="{escape(web_base_url)}" '
        f'style="color:{p["accent"]};text-decoration:none">Open in Driftnote</a></p>\n'
        f"</body></html>"
    )
    return Digest(subject=subject, html=body_html)


def _row_html(row: list[MonthlyCell]) -> str:
    p = _DIGEST_PALETTE
    return (
        "<tr>"
        + "".join(
            f'<td style="text-align:center;width:32px;height:32px;font-size:18px;'
            f'color:{p["fg"] if c.in_month else p["fg_dim"]}">'
            f'<div style="font-size:10px;color:{p["fg_muted"] if c.in_month else p["fg_dim"]}">'
            f"{c.day_of_month}"
            f"</div>"
            f"<div>{escape(c.emoji or ('·' if c.in_month else ''))}</div>"
            f"</td>"
            for c in row
        )
        + "</tr>"
    )


def _render_highlight(h: HighlightInput, *, web_base_url: str) -> str:
    p = _DIGEST_PALETTE
    thumb_html = (
        f'<img src="{escape(h.photo_thumb)}" style="max-width:100%"/>' if h.photo_thumb else ""
    )
    return (
        f'<section style="margin:16px 0;padding:12px 0 0 16px;'
        f'border-top:1px solid {p["border"]};border-left:4px solid {p["accent"]}">'
        f'<h3 style="margin:0;font-size:16px">'
        f'<a href="{escape(web_base_url)}/entry/{escape(h.date.isoformat())}" '
        f'style="color:{p["fg"]};text-decoration:none">'
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
