"""Tests for yearly digest builder."""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.yearly import build_yearly_digest


def _day(
    d: str, mood: str | None = "💪", tags: list[str] | None = None, thumb: str | None = None
) -> DayInput:
    return DayInput(
        date=date.fromisoformat(d),
        mood=mood,
        tags=tags or [],
        photo_thumb=thumb,
        body_html="<p>x</p>",
    )


def test_subject_is_year_in_review() -> None:
    digest = build_yearly_digest(
        year=2026,
        days=[_day("2026-01-01")],
        web_base_url="https://x",
    )
    assert "2026" in digest.subject
    assert "review" in digest.subject.lower()


def test_html_includes_yearly_grid_and_streak_stats() -> None:
    days = [_day(f"2026-01-{i:02d}") for i in range(1, 11)]  # 10-day streak
    days += [_day("2026-06-15")]  # break in streak
    digest = build_yearly_digest(year=2026, days=days, web_base_url="https://x")
    assert "💪" in digest.html
    assert "Stats" in digest.html or "stats" in digest.html
    assert "11" in digest.html or "entries" in digest.html


def test_html_includes_one_photo_per_month_when_available() -> None:
    days = [
        _day(f"2026-{m:02d}-15", thumb=f"cid:photo-{m}", tags=["holiday" if m == 7 else "work"])
        for m in range(1, 13)
    ]
    digest = build_yearly_digest(year=2026, days=days, web_base_url="https://x")
    assert "cid:photo-1" in digest.html
    assert "cid:photo-12" in digest.html
