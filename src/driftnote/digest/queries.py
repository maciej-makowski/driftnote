"""Queries that hydrate digest renderers from SQLite."""

from __future__ import annotations

from datetime import date as _date
from html import escape

from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.digest.inputs import DayInput
from driftnote.repository.entries import list_entries_in_range, tags_by_date_in_range
from driftnote.repository.media import list_media


def days_in_range(engine: Engine, *, start: _date, end: _date) -> list[DayInput]:
    with session_scope(engine) as session:
        entries = list_entries_in_range(session, start.isoformat(), end.isoformat())

    out: list[DayInput] = []
    for e in entries:
        with session_scope(engine) as session:
            media = list_media(session, e.date)
        thumb = next((m.filename for m in media if m.kind == "photo"), None)
        photo_thumb = f"cid:{thumb}" if thumb else None
        # Body HTML = naive paragraph wrap of stored body_md.
        body_html = "".join(
            f"<p>{escape(line)}</p>" for line in e.body_md.split("\n\n") if line.strip()
        )
        out.append(
            DayInput(
                date=_date.fromisoformat(e.date),
                mood=e.mood,
                tags=[],  # tags filled below
                photo_thumb=photo_thumb,
                body_html=body_html,
            )
        )

    # Backfill tags via a single query.
    with session_scope(engine) as session:
        tags_by_date = tags_by_date_in_range(session, start.isoformat(), end.isoformat())

    return [
        DayInput(
            date=d.date,
            mood=d.mood,
            tags=tags_by_date.get(d.date.isoformat(), []),
            photo_thumb=d.photo_thumb,
            body_html=d.body_html,
        )
        for d in out
    ]
