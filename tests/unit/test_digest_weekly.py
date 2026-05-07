"""Tests for weekly digest body composition (HTML)."""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.weekly import build_weekly_digest


def _day(
    d: str,
    body: str = "<p>hi</p>",
    mood: str = "💪",
    tags: list[str] | None = None,
    thumb: str | None = None,
) -> DayInput:
    return DayInput(
        date=date.fromisoformat(d),
        mood=mood,
        tags=tags or [],
        photo_thumb=thumb,
        body_html=body,
    )


def test_subject_includes_week_range() -> None:
    digest = build_weekly_digest(
        week_start=date(2026, 4, 27),
        days=[_day("2026-04-27")],
        web_base_url="https://driftnote.example.com",
    )
    assert "2026-04-27" in digest.subject
    assert "2026-05-03" in digest.subject


def test_html_lists_every_day_section_in_order() -> None:
    digest = build_weekly_digest(
        week_start=date(2026, 4, 27),
        days=[_day("2026-04-29"), _day("2026-04-27"), _day("2026-05-02")],
        web_base_url="https://driftnote.example.com",
    )
    html = digest.html
    i_27 = html.index("2026-04-27")
    i_29 = html.index("2026-04-29")
    i_02 = html.index("2026-05-02")
    assert i_27 < i_29 < i_02


def test_html_includes_moodboard_row_with_emojis() -> None:
    digest = build_weekly_digest(
        week_start=date(2026, 4, 27),
        days=[_day("2026-04-27", mood="💪"), _day("2026-05-03", mood="🎉")],
        web_base_url="https://driftnote.example.com",
    )
    assert "💪" in digest.html
    assert "🎉" in digest.html


def test_html_links_to_web_ui() -> None:
    digest = build_weekly_digest(
        week_start=date(2026, 4, 27),
        days=[_day("2026-04-27")],
        web_base_url="https://driftnote.example.com",
    )
    assert "https://driftnote.example.com/entry/2026-04-27" in digest.html
