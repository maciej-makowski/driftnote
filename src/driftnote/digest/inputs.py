"""Pydantic-friendly inputs for digest rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DayInput:
    """One day's worth of data needed for digest rendering."""

    date: date
    mood: str | None
    tags: list[str]
    photo_thumb: str | None  # URL fragment / "cid:..." reference
    body_html: str  # rendered markdown → safe HTML


@dataclass(frozen=True)
class HighlightInput:
    date: date
    mood: str | None
    summary_html: str  # first ~2 sentences as HTML
    photo_thumb: str | None  # CID reference for inline image
