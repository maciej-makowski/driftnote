"""ingested_messages, pending_prompts, disk_state — the email-flow + disk state tables."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from driftnote.models import DiskState, IngestedMessage, PendingPrompt


class IngestedMessageRecord(BaseModel):
    message_id: str
    date: str
    eml_path: str
    ingested_at: str
    imap_moved: int


class PendingPromptRecord(BaseModel):
    date: str
    message_id: str
    sent_at: str


def record_ingested(
    session: Session,
    *,
    message_id: str,
    date: str,
    eml_path: str,
    ingested_at: str,
) -> None:
    session.add(
        IngestedMessage(
            message_id=message_id,
            date=date,
            eml_path=eml_path,
            ingested_at=ingested_at,
            imap_moved=0,
        )
    )


def is_ingested(session: Session, message_id: str) -> bool:
    return (
        session.scalar(
            select(IngestedMessage.message_id).where(IngestedMessage.message_id == message_id)
        )
        is not None
    )


def get_ingested(session: Session, message_id: str) -> IngestedMessageRecord | None:
    row = session.scalar(select(IngestedMessage).where(IngestedMessage.message_id == message_id))
    if row is None:
        return None
    return IngestedMessageRecord(
        message_id=row.message_id,
        date=row.date,
        eml_path=row.eml_path,
        ingested_at=row.ingested_at,
        imap_moved=row.imap_moved,
    )


def mark_imap_moved(session: Session, message_id: str) -> None:
    session.execute(
        update(IngestedMessage).where(IngestedMessage.message_id == message_id).values(imap_moved=1)
    )


def pending_imap_moves(session: Session) -> list[IngestedMessageRecord]:
    rows = session.scalars(select(IngestedMessage).where(IngestedMessage.imap_moved == 0))
    return [
        IngestedMessageRecord(
            message_id=r.message_id,
            date=r.date,
            eml_path=r.eml_path,
            ingested_at=r.ingested_at,
            imap_moved=r.imap_moved,
        )
        for r in rows
    ]


def record_pending_prompt(
    session: Session,
    *,
    date: str,
    message_id: str,
    sent_at: str,
) -> None:
    """Idempotent on `date` (the PK)."""
    stmt = (
        sqlite_insert(PendingPrompt)
        .values(date=date, message_id=message_id, sent_at=sent_at)
        .on_conflict_do_update(
            index_elements=["date"],
            set_={"message_id": message_id, "sent_at": sent_at},
        )
    )
    session.execute(stmt)


def find_prompt_by_message_id(session: Session, message_id: str) -> PendingPromptRecord | None:
    row = session.scalar(select(PendingPrompt).where(PendingPrompt.message_id == message_id))
    if row is None:
        return None
    return PendingPromptRecord(date=row.date, message_id=row.message_id, sent_at=row.sent_at)


def get_threshold_crossed_at(session: Session, threshold: int) -> str | None:
    row = session.scalar(select(DiskState).where(DiskState.threshold_percent == threshold))
    return row.crossed_at if row else None


def record_threshold_crossed(session: Session, *, threshold: int, at: str) -> None:
    stmt = (
        sqlite_insert(DiskState)
        .values(threshold_percent=threshold, crossed_at=at)
        .on_conflict_do_update(
            index_elements=["threshold_percent"],
            set_={"crossed_at": at},
        )
    )
    session.execute(stmt)


def clear_threshold_crossed(session: Session, threshold: int) -> None:
    session.execute(delete(DiskState).where(DiskState.threshold_percent == threshold))
