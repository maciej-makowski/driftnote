"""CRUD and queries for entries + tags. ORM types do not leak above this layer.

All public functions take an open SQLAlchemy `Session` and return Pydantic
records (`EntryRecord`) — never `Entry` ORM instances.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from driftnote.models import Entry, Tag


class EntryRecord(BaseModel):
    date: str
    mood: str | None = None
    body_text: str
    body_md: str
    created_at: str
    updated_at: str


def _to_record(e: Entry) -> EntryRecord:
    return EntryRecord(
        date=e.date,
        mood=e.mood,
        body_text=e.body_text,
        body_md=e.body_md,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def upsert_entry(session: Session, record: EntryRecord) -> None:
    """Insert-or-update by primary key `date`. Idempotent."""
    stmt = (
        sqlite_insert(Entry)
        .values(
            date=record.date,
            mood=record.mood,
            body_text=record.body_text,
            body_md=record.body_md,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        .on_conflict_do_update(
            index_elements=["date"],
            set_={
                "mood": record.mood,
                "body_text": record.body_text,
                "body_md": record.body_md,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            },
        )
    )
    session.execute(stmt)


def get_entry(session: Session, date: str) -> EntryRecord | None:
    e = session.scalar(select(Entry).where(Entry.date == date))
    return _to_record(e) if e else None


def list_entries_by_month(session: Session, year: int, month: int) -> list[EntryRecord]:
    prefix = f"{year:04d}-{month:02d}-"
    stmt = select(Entry).where(Entry.date.like(f"{prefix}%")).order_by(Entry.date)
    return [_to_record(e) for e in session.scalars(stmt)]


def list_entries_in_range(session: Session, start: str, end: str) -> list[EntryRecord]:
    stmt = select(Entry).where(Entry.date.between(start, end)).order_by(Entry.date)
    return [_to_record(e) for e in session.scalars(stmt)]


def list_entries_by_tag(session: Session, tag: str) -> list[EntryRecord]:
    stmt = (
        select(Entry)
        .join(Tag, Tag.date == Entry.date)
        .where(Tag.tag == tag.lower())
        .order_by(Entry.date.desc())
    )
    return [_to_record(e) for e in session.scalars(stmt)]


def count_entries_in_range(session: Session, start: str, end: str) -> int:
    from sqlalchemy import func

    stmt = select(func.count()).select_from(Entry).where(Entry.date.between(start, end))
    return session.scalar(stmt) or 0


def tag_frequencies_in_range(session: Session, start: str, end: str) -> dict[str, int]:
    """Tag.date is the FK to entries.date, so we don't need to join Entry."""
    stmt = select(Tag.tag).where(Tag.date.between(start, end))
    counter: Counter[str] = Counter(session.scalars(stmt))
    return dict(counter)


def replace_tags(session: Session, date: str, tags: list[str]) -> None:
    """Replace all tags for `date` with the given list (lowercased, deduplicated)."""
    session.execute(delete(Tag).where(Tag.date == date))
    seen: set[str] = set()
    for raw in tags:
        normalized = raw.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        session.add(Tag(date=date, tag=normalized))


def search_fts(session: Session, query: str) -> list[EntryRecord]:
    """Full-text search via FTS5. Returns most-recently-dated matches first."""
    rows = session.execute(
        text(
            "SELECT date FROM entries "
            "WHERE id IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH :q) "
            "ORDER BY date DESC"
        ),
        {"q": query},
    ).all()
    if not rows:
        return []
    dates = [r[0] for r in rows]
    stmt = select(Entry).where(Entry.date.in_(dates)).order_by(Entry.date.desc())
    return [_to_record(e) for e in session.scalars(stmt)]


def delete_entry(session: Session, date: str) -> None:
    session.execute(delete(Entry).where(Entry.date == date))


def list_tags_for_date(session: Session, date: str) -> list[str]:
    """Return tag names (lowercase) for the given date in stable order."""
    stmt = select(Tag.tag).where(Tag.date == date).order_by(Tag.tag)
    return list(session.scalars(stmt))


def tags_by_date_in_range(session: Session, start: str, end: str) -> dict[str, list[str]]:
    """Return tag lists keyed by date, for dates with at least one tag in [start, end] (inclusive)."""
    stmt = select(Tag).where(Tag.date.between(start, end)).order_by(Tag.date, Tag.tag)
    out: dict[str, list[str]] = {}
    for t in session.scalars(stmt):
        out.setdefault(t.date, []).append(t.tag)
    return out
