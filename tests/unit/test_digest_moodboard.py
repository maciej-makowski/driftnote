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


def test_monthly_moodboard_returns_six_rows_always() -> None:
    """Every month renders as exactly 6 weeks for stable visual rhythm."""
    days = [_day("2026-05-01"), _day("2026-05-15", mood="🌧️"), _day("2026-05-31", mood="🎉")]
    rows = monthly_moodboard_grid(year=2026, month=5, days=days)
    assert len(rows) == 6
    flat = [c for row in rows for c in row]
    moods = [c.emoji for c in flat if c.in_month and c.day_of_month == 1]
    assert moods == ["💪"]


def test_monthly_moodboard_pads_to_six_rows_for_short_months() -> None:
    """February 2026 is a short month — naturally fits in 5 rows. Must still pad to 6."""
    rows = monthly_moodboard_grid(year=2026, month=2, days=[])
    assert len(rows) == 6


def test_monthly_moodboard_pad_cells_carry_day_of_month() -> None:
    """Prev/next-month pad cells render their actual day number (dimmed in the UI)."""
    rows = monthly_moodboard_grid(year=2026, month=5, days=[])
    flat = [c for row in rows for c in row]
    pad = [c for c in flat if not c.in_month]
    assert pad, "May 2026 starts on a Friday so there must be pad cells"
    # Every pad cell carries a real calendar day number 1..31, not None.
    assert all(isinstance(c.day_of_month, int) for c in pad)
    assert all(1 <= c.day_of_month <= 31 for c in pad)
    # No emoji on pad cells (we don't carry mood data outside the target month).
    assert all(c.emoji is None for c in pad)
    # Concrete pad-date pins: May 2026 starts Fri so week 1 leads with
    # Apr 27..30, and trailing pad cells in week 6 are early June.
    pad_dates = sorted(c.date for c in pad)
    assert pad_dates[0] == date(2026, 4, 27)
    assert pad_dates[-1].month == 6 and pad_dates[-1].year == 2026


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
