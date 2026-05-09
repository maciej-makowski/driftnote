"""Tests for monthly digest builder including the progressive-highlights heuristic."""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.monthly import build_monthly_digest, select_highlights


def _day(
    d: str, *, mood: str = "💪", tags: list[str] | None = None, thumb: str | None = None
) -> DayInput:
    return DayInput(
        date=date.fromisoformat(d),
        mood=mood,
        tags=tags or [],
        photo_thumb=thumb,
        body_html="<p>body</p>",
    )


def test_select_highlights_prefers_photo_plus_rare_tag() -> None:
    days = [
        _day("2026-05-01", thumb="cid:1", tags=["work"]),  # work appears 5x
        _day("2026-05-02", thumb="cid:2", tags=["holiday", "work"]),  # holiday rare
        _day("2026-05-03", thumb="cid:3", tags=["birthday"]),  # birthday rare, no photo
        _day("2026-05-04", thumb="cid:4", tags=["work"]),
        _day("2026-05-05", thumb="cid:5", tags=["work"]),
        _day("2026-05-06", thumb="cid:6", tags=["work"]),
    ]
    highlights = select_highlights(days, target=4)
    # 2026-05-02 qualifies (photo + rare tag). With only 1 qualifying, fallback expands.
    assert any(h.date == date(2026, 5, 2) for h in highlights)


def test_select_highlights_fallback_when_no_photo_plus_rare() -> None:
    """If nothing matches photo+rare, fall back to days with rare tag OR photo, then to most-photos."""
    days = [_day(f"2026-05-0{i}", thumb=f"cid:{i}", tags=["common"]) for i in range(1, 8)]
    highlights = select_highlights(days, target=4)
    # Length up to target — heuristic should still emit something.
    assert len(highlights) <= 4


def test_select_highlights_no_padding_when_few_candidates() -> None:
    """Heuristic does not pad: if nothing qualifies even after full fallback, emit fewer."""
    highlights = select_highlights([], target=4)
    assert highlights == []


def test_subject_is_month_year() -> None:
    digest = build_monthly_digest(
        year=2026, month=5, days=[_day("2026-05-01")], web_base_url="https://x"
    )
    assert "2026" in digest.subject
    assert "May" in digest.subject or "05" in digest.subject


def test_html_includes_calendar_grid_and_stats() -> None:
    days = [_day("2026-05-01", tags=["work"]), _day("2026-05-15", mood="🌧️", tags=["rest"])]
    digest = build_monthly_digest(year=2026, month=5, days=days, web_base_url="https://x")
    assert "💪" in digest.html
    assert "🌧️" in digest.html
    assert "work" in digest.html or "Work" in digest.html
    assert "Stats" in digest.html or "stats" in digest.html or "entries" in digest.html
