"""Media (photo/video) row management. One row per media file per entry, with display order."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from driftnote.models import Media


class MediaInput(BaseModel):
    kind: Literal["photo", "video"]
    filename: str
    caption: str = ""


class MediaRecord(BaseModel):
    date: str
    kind: Literal["photo", "video"]
    filename: str
    ord: int
    caption: str


def _to_record(m: Media) -> MediaRecord:
    return MediaRecord(
        date=m.date,
        kind=m.kind,
        filename=m.filename,
        ord=m.ord,
        caption=m.caption,
    )


def replace_media(session: Session, date: str, items: list[MediaInput]) -> None:
    """Drop and re-insert all media rows for `date` in the given order."""
    session.execute(delete(Media).where(Media.date == date))
    for ord_, item in enumerate(items):
        session.add(
            Media(
                date=date,
                kind=item.kind,
                filename=item.filename,
                ord=ord_,
                caption=item.caption,
            )
        )


def list_media(session: Session, date: str) -> list[MediaRecord]:
    stmt = select(Media).where(Media.date == date).order_by(Media.ord)
    return [_to_record(m) for m in session.scalars(stmt)]
