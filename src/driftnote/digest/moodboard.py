"""Moodboard renderers: weekly row, monthly calendar grid, yearly 7x53 grid."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from driftnote.digest.inputs import DayInput

_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class WeeklyCell:
    label: str  # "Mon" .. "Sun"
    date: date
    emoji: str | None


@dataclass(frozen=True)
class MonthlyCell:
    date: date
    in_month: bool  # False for grid pad cells outside this month
    day_of_month: int  # always populated; pad cells carry the actual prev/next-month day number
    emoji: str | None


@dataclass(frozen=True)
class YearlyCell:
    date: date
    in_year: bool
    emoji: str | None


def weekly_moodboard(*, week_start: date, days: list[DayInput]) -> list[WeeklyCell]:
    """Return 7 cells starting at `week_start` (which must be a Monday)."""
    by_date = {d.date: d.mood for d in days}
    out: list[WeeklyCell] = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        out.append(WeeklyCell(label=_WEEKDAY_LABELS[i], date=d, emoji=by_date.get(d)))
    return out


def monthly_moodboard_grid(
    *, year: int, month: int, days: list[DayInput]
) -> list[list[MonthlyCell]]:
    """Calendar grid: rows = weeks, columns = Mon..Sun. Always returns six
    rows for stable visual rhythm. Cells outside the target month carry
    `in_month=False` but still expose the prev/next-month day number for
    rendering as dimmed pad cells."""
    by_date = {d.date: d.mood for d in days}

    first = date(year, month, 1)

    # Snap to the Monday of the week containing the 1st.
    grid_start = first - timedelta(days=first.weekday())
    rows: list[list[MonthlyCell]] = []
    cur = grid_start
    for _ in range(6):
        row: list[MonthlyCell] = []
        for _ in range(7):
            in_month = cur.month == month and cur.year == year
            row.append(
                MonthlyCell(
                    date=cur,
                    in_month=in_month,
                    day_of_month=cur.day,
                    emoji=by_date.get(cur) if in_month else None,
                )
            )
            cur += timedelta(days=1)
        rows.append(row)
    return rows


def yearly_moodboard_grid(*, year: int, days: list[DayInput]) -> list[list[YearlyCell]]:
    """GitHub-style contribution grid: 7 rows (Mon..Sun) x up to 53 columns."""
    by_date = {d.date: d.mood for d in days}
    first = date(year, 1, 1)
    last = date(year, 12, 31)

    grid_start = first - timedelta(days=first.weekday())
    columns: list[list[YearlyCell]] = []
    cur = grid_start
    while cur <= last or cur.weekday() != 0:
        col: list[YearlyCell] = []
        for _ in range(7):
            in_year = cur.year == year
            col.append(
                YearlyCell(date=cur, in_year=in_year, emoji=by_date.get(cur) if in_year else None)
            )
            cur += timedelta(days=1)
        columns.append(col)
    # Transpose: rows = weekday (Mon..Sun), cols = week index.
    rows: list[list[YearlyCell]] = [[col[r] for col in columns] for r in range(7)]
    return rows
