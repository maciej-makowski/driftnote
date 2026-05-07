"""SQLAlchemy ORM models matching the SQLite schema in the design spec.

The `entries` table uses an explicit INTEGER PRIMARY KEY `id` (with a UNIQUE
constraint on `date`) so that FTS5 can reference rows via `content_rowid='id'`.
This is a deliberate refinement of spec §2 — the spec's prose treats `date` as
the natural key, but FTS5 requires a true rowid alias. Foreign keys throughout
still reference `entries.date`, preserving the natural-key relationships.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("date", name="uq_entries_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    mood: Mapped[str | None] = mapped_column(String(16))
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (Index("idx_tags_tag", "tag"),)

    date: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("entries.date", ondelete="CASCADE"),
        primary_key=True,
    )
    tag: Mapped[str] = mapped_column(String(64), primary_key=True)


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (
        CheckConstraint("kind IN ('photo','video')", name="ck_media_kind"),
        Index("idx_media_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("entries.date", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class IngestedMessage(Base):
    __tablename__ = "ingested_messages"
    __table_args__ = (
        Index(
            "idx_ingested_imap_moved",
            "imap_moved",
            sqlite_where=text("imap_moved = 0"),
        ),
    )

    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    date: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("entries.date"),
        nullable=False,
    )
    eml_path: Mapped[str] = mapped_column(String(255), nullable=False)
    ingested_at: Mapped[str] = mapped_column(String(32), nullable=False)
    imap_moved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class PendingPrompt(Base):
    __tablename__ = "pending_prompts"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    sent_at: Mapped[str] = mapped_column(String(32), nullable=False)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (Index("idx_job_runs_job_started", "job", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[str] = mapped_column(String(32), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[str | None] = mapped_column(String(32))


class DiskState(Base):
    __tablename__ = "disk_state"

    threshold_percent: Mapped[int] = mapped_column(Integer, primary_key=True)
    crossed_at: Mapped[str] = mapped_column(String(32), nullable=False)
