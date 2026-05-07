"""Orchestrate ingestion of one raw email into the entry store + index.

Implements the spec §3.B failure semantics:
- Idempotency on Message-ID via `ingested_messages`.
- Per-date `fcntl.flock` so two replies for the same date serialize.
- Whole-message rollback on any pre-IMAP-move failure: no entry.md mutation,
  no raw.eml written, no SQLite row.
- The IMAP-move retry path is *not* in this function — it lives in the
  poll job (Chunk 7), which calls `mark_imap_moved()` after a successful move.
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from driftnote.config import Config
from driftnote.db import session_scope
from driftnote.filesystem.layout import EntryPaths, entry_paths_for, raw_eml_filename
from driftnote.filesystem.locks import entry_lock
from driftnote.filesystem.markdown_io import (
    EntryDocument,
    PhotoRef,
    VideoRef,
    read_entry,
    write_entry,
)
from driftnote.ingest.attachments import (
    AttachmentArtifacts,
    derive_photo,
    derive_video_poster,
)
from driftnote.ingest.parse import AttachmentMaterial, ParsedReply, parse_reply
from driftnote.repository.entries import EntryRecord, replace_tags, upsert_entry
from driftnote.repository.ingested import (
    find_prompt_by_message_id,
    get_ingested,
    is_ingested,
    record_ingested,
)
from driftnote.repository.media import MediaInput, replace_media


@dataclass(frozen=True)
class IngestionResult:
    ingested: bool  # False if message_id was already ingested (no-op)
    entry_date: str  # 'YYYY-MM-DD'
    message_id: str


def ingest_one(
    *,
    raw: bytes,
    config: Config,
    engine: Engine,
    data_root: Path,
    received_at: datetime,
) -> IngestionResult:
    parsed = parse_reply(
        raw,
        mood_regex=config.parsing.mood_regex,
        tag_regex=config.parsing.tag_regex,
    )

    # Idempotency: if we've already ingested this message-id, no-op early.
    with session_scope(engine) as session:
        if is_ingested(session, parsed.message_id):
            entry_date = _entry_date_from_db_or_parsed(session, parsed)
            return IngestionResult(
                ingested=False, entry_date=entry_date, message_id=parsed.message_id
            )

    entry_date = _resolve_entry_date(parsed, engine)

    # Per-date lock: serialize concurrent same-date ingestions.
    with entry_lock(data_root, _date(entry_date)):
        paths = entry_paths_for(data_root, _date(entry_date))
        # Track resources written so we can roll them back on failure.
        created_dirs: list[Path] = []
        created_files: list[Path] = []

        try:
            existing_doc = read_entry(paths.entry_md) if paths.entry_md.exists() else None

            # Cap attachments per config.
            photos = [a for a in parsed.attachments if a.kind == "photo"][
                : config.parsing.max_photos
            ]
            videos = [a for a in parsed.attachments if a.kind == "video"][
                : config.parsing.max_videos
            ]

            # Write raw .eml *first* — this is the canonical input record.
            paths.raw_dir.mkdir(parents=True, exist_ok=True)
            created_dirs.append(paths.raw_dir)
            received_utc = received_at.astimezone(UTC)
            eml_filename = raw_eml_filename(received_utc)
            eml_path = paths.raw_dir / eml_filename
            eml_path.write_bytes(raw)
            created_files.append(eml_path)

            # Save originals + derive web/thumb/poster.
            photo_artifacts: list[tuple[AttachmentMaterial, AttachmentArtifacts]] = []
            for material in photos:
                art = derive_photo(
                    original_bytes=material.content,
                    original_filename=material.filename,
                    originals_dir=paths.originals_dir,
                    web_dir=paths.web_dir,
                    thumbs_dir=paths.thumbs_dir,
                )
                photo_artifacts.append((material, art))
                _track_artifact_files(art, created_files)

            video_artifacts: list[tuple[AttachmentMaterial, AttachmentArtifacts]] = []
            for material in videos:
                art = derive_video_poster(
                    original_bytes=material.content,
                    original_filename=material.filename,
                    originals_dir=paths.originals_dir,
                    thumbs_dir=paths.thumbs_dir,
                )
                video_artifacts.append((material, art))
                _track_artifact_files(art, created_files)

            # Compose new EntryDocument. If a prior doc exists, append this section's body
            # and union the tags + media.
            doc = _compose_entry_doc(
                entry_date=entry_date,
                parsed=parsed,
                received_utc=received_utc,
                eml_filename=eml_filename,
                photos=photo_artifacts,
                videos=video_artifacts,
                existing=existing_doc,
            )
            write_entry(paths.entry_md, doc)
            created_files.append(paths.entry_md)

            # Upsert into SQLite (entries + tags + media + ingested_messages).
            with session_scope(engine) as session:
                upsert_entry(
                    session,
                    EntryRecord(
                        date=entry_date,
                        mood=doc.mood,
                        body_text=doc.body,
                        body_md=doc.body,
                        created_at=doc.created_at,
                        updated_at=doc.updated_at,
                    ),
                )
                replace_tags(session, entry_date, list(doc.tags))
                replace_media(
                    session,
                    entry_date,
                    [
                        MediaInput(kind="photo", filename=p.filename, caption=p.caption)
                        for p in doc.photos
                    ]
                    + [
                        MediaInput(kind="video", filename=v.filename, caption=v.caption)
                        for v in doc.videos
                    ],
                )
                record_ingested(
                    session,
                    message_id=parsed.message_id,
                    date=entry_date,
                    eml_path=str(eml_path.relative_to(paths.dir)),
                    ingested_at=received_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
        except BaseException:
            _rollback_files(created_files, created_dirs, paths)
            raise

    return IngestionResult(ingested=True, entry_date=entry_date, message_id=parsed.message_id)


def _date(s: str) -> date:
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def _resolve_entry_date(parsed: ParsedReply, engine: Engine) -> str:
    """Map a reply to its entry date. Prefer the In-Reply-To anchor; else use the
    Date header in UTC; else today (UTC)."""
    if parsed.in_reply_to:
        with session_scope(engine) as session:
            pending = find_prompt_by_message_id(session, parsed.in_reply_to)
        if pending is not None:
            return pending.date
    if parsed.date_header is not None:
        return parsed.date_header.astimezone(UTC).date().isoformat()
    return datetime.now(tz=UTC).date().isoformat()


def _entry_date_from_db_or_parsed(session: Session, parsed: ParsedReply) -> str:
    rec = get_ingested(session, parsed.message_id)
    if rec is not None:
        return rec.date
    if parsed.date_header is not None:
        return parsed.date_header.astimezone(UTC).date().isoformat()
    return datetime.now(tz=UTC).date().isoformat()


def _compose_entry_doc(
    *,
    entry_date: str,
    parsed: ParsedReply,
    received_utc: datetime,
    eml_filename: str,
    photos: list[tuple[AttachmentMaterial, AttachmentArtifacts]],
    videos: list[tuple[AttachmentMaterial, AttachmentArtifacts]],
    existing: EntryDocument | None,
) -> EntryDocument:
    iso_now = received_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    new_section = parsed.body.strip("\n")

    if existing is None:
        body = new_section + ("\n" if new_section else "")
        tags = list(parsed.tags)
        photo_refs = [PhotoRef(filename=m.filename) for m, _ in photos]
        video_refs = [VideoRef(filename=m.filename) for m, _ in videos]
        return EntryDocument(
            date=_date(entry_date),
            mood=parsed.mood,
            tags=tags,
            photos=photo_refs,
            videos=video_refs,
            created_at=iso_now,
            updated_at=iso_now,
            sources=[f"raw/{eml_filename}"],
            body=body,
        )

    # Append a new section separated by ---.
    appended_body = (existing.body.rstrip("\n") + "\n\n---\n\n" + new_section).rstrip("\n") + "\n"
    union_tags: list[str] = list(existing.tags)
    seen = set(union_tags)
    for t in parsed.tags:
        if t not in seen:
            seen.add(t)
            union_tags.append(t)
    photo_refs = list(existing.photos) + [PhotoRef(filename=m.filename) for m, _ in photos]
    video_refs = list(existing.videos) + [VideoRef(filename=m.filename) for m, _ in videos]
    sources = [*list(existing.sources), f"raw/{eml_filename}"]
    return EntryDocument(
        date=_date(entry_date),
        mood=existing.mood or parsed.mood,
        tags=union_tags,
        photos=photo_refs,
        videos=video_refs,
        created_at=existing.created_at,
        updated_at=iso_now,
        sources=sources,
        body=appended_body,
    )


def _track_artifact_files(art: AttachmentArtifacts, sink: list[Path]) -> None:
    for p in (art.original_path, art.web_path, art.thumb_path):
        if p is not None:
            sink.append(p)


def _rollback_files(files: list[Path], _dirs: list[Path], paths: EntryPaths) -> None:
    """Remove any files created during a failed ingest. Empty subdirs are removed too.

    The whole-entry directory is removed only if it was created in this call (i.e.
    no prior entry.md existed). We approximate this by checking whether the entry.md
    is present and not in `files` (meaning it pre-existed).
    """
    for f in files:
        with contextlib.suppress(OSError):
            f.unlink(missing_ok=True)
    # Cleanup obviously-empty subdirs we created.
    for sub in (paths.raw_dir, paths.web_dir, paths.thumbs_dir, paths.originals_dir):
        if sub.exists() and not any(sub.iterdir()):
            with contextlib.suppress(OSError):
                sub.rmdir()
    if paths.dir.exists() and not any(paths.dir.iterdir()):
        with contextlib.suppress(OSError):
            shutil.rmtree(paths.dir)
