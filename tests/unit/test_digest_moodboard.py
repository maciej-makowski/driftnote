"""Tests for moodboard rendering helpers."""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.moodboard import (
    monthly_moodboard_grid,
    weekly_moodboard,
    yearly_moodboard_grid,
)


def _day(d: str, mood: str | None = "💪") -> DayInput:
    return DayInput(date=date.fromisoformat(d), mood=mood, tags=[], photo_thumb=None, body_html="")


def test_weekly_moodboard_seven_cells_with_emojis_or_dot() -> None:
    days = [_day("2026-04-27"), _day("2026-04-29", mood=None), _day("2026-05-03", mood="🎉")]
    cells = weekly_moodboard(week_start=date(2026, 4, 27), days=days)
    assert len(cells) == 7
    assert cells[0].emoji == "💪"
    assert cells[2].emoji is None  # Wed (no day with mood)
    assert cells[6].emoji == "🎉"
    assert cells[0].label == "Mon"


def test_monthly_moodboard_returns_calendar_rows() -> None:
    days = [_day("2026-05-01"), _day("2026-05-15", mood="🌧️"), _day("2026-05-31", mood="🎉")]
    rows = monthly_moodboard_grid(year=2026, month=5, days=days)
    # May 2026 spans 6 calendar weeks.
    assert len(rows) >= 5
    flat = [c for row in rows for c in row]
    moods = [c.emoji for c in flat if c.in_month and c.day_of_month == 1]
    assert moods == ["💪"]


def test_yearly_grid_53_weeks_max() -> None:
    days = [_day("2026-01-01"), _day("2026-12-31", mood="🌧️")]
    grid = yearly_moodboard_grid(year=2026, days=days)
    # 7 rows (Mon..Sun), <=53 columns
    assert len(grid) == 7
    assert all(len(row) <= 53 for row in grid)
    # Find the cell for 2026-01-01 and 2026-12-31; confirm emojis.
    cells = [c for row in grid for c in row if c.in_year]
    by_date = {c.date: c.emoji for c in cells}
    assert by_date[date(2026, 1, 1)] == "💪"
    assert by_date[date(2026, 12, 31)] == "🌧️"
