"""Snapshot-style assertions for the monthly digest's polished light theme.

These tests don't compare against a committed HTML fixture (palette tweaks
should not require fixture refreshes). Instead we assert the digest contains
the spec's load-bearing palette tokens and renders pad-cell day numbers.
"""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.monthly import build_monthly_digest


def _day(d: str, *, mood: str = "💪") -> DayInput:
    return DayInput(
        date=date.fromisoformat(d),
        mood=mood,
        tags=[],
        photo_thumb=None,
        body_html="<p>body</p>",
    )


def test_digest_uses_polished_light_palette() -> None:
    digest = build_monthly_digest(
        year=2026, month=5, days=[_day("2026-05-15")], web_base_url="https://x"
    )
    # Accent (deeper purple, readable on white).
    assert "#6c4fc4" in digest.html
    # Pad-cell muted text colour.
    assert "#c4c2cc" in digest.html


def test_digest_grid_has_six_rows_with_pad_day_numbers() -> None:
    """May 2026 starts Friday → April 27..30 are pad days at the start. June 1..7
    occupy the trailing pad row (always six rows total)."""
    digest = build_monthly_digest(
        year=2026, month=5, days=[_day("2026-05-15")], web_base_url="https://x"
    )
    # Six body rows.
    assert digest.html.count("<tr>") == 6
    # Pad cells render their actual day number.
    assert ">30<" in digest.html
    assert ">1<" in digest.html  # June 1 in the trailing row
