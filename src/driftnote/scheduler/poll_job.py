"""IMAP poll job: fetch UNSEEN replies, ingest each, then move to Processed.

Two paths:
- Normal: per-message UNSEEN → ingest → IMAP-move → set imap_moved=1.
- Retry: at job start, drain any rows with imap_moved=0 from prior polls and
  attempt the IMAP move again. This implements the spec §3.B retry path
  cleanly without the ingest pipeline needing to know about it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from driftnote.config import Config
from driftnote.db import session_scope
from driftnote.ingest.pipeline import ingest_one
from driftnote.mail.imap import RawMessage, poll_unseen
from driftnote.mail.imap import move_to_processed as _move_to_processed
from driftnote.mail.transport import ImapTransport
from driftnote.repository.ingested import (
    is_ingested,
    mark_imap_moved,
    pending_imap_moves,
)


async def run_poll_job(
    *,
    config: Config,
    engine: Engine,
    data_root: Path,
    imap: ImapTransport,
) -> None:
    # Step 1: retry any prior IMAP-move failures.
    with session_scope(engine) as session:
        retry_targets = pending_imap_moves(session)
    for row in retry_targets:
        await _move_to_processed(imap, message_id=row.message_id)
        with session_scope(engine) as session:
            mark_imap_moved(session, row.message_id)

    # Step 2: poll new UNSEEN messages.
    async for raw_msg in poll_unseen(imap):
        await _handle_one(raw_msg, config=config, engine=engine, data_root=data_root, imap=imap)


async def _handle_one(
    raw_msg: RawMessage,
    *,
    config: Config,
    engine: Engine,
    data_root: Path,
    imap: ImapTransport,
) -> None:
    # Idempotency check upfront — if already ingested, skip directly to IMAP move
    # (the ingest pipeline also no-ops, but this avoids re-parsing).
    with session_scope(engine) as session:
        already = is_ingested(session, raw_msg.message_id)

    if not already:
        ingest_one(
            raw=raw_msg.raw_bytes,
            config=config,
            engine=engine,
            data_root=data_root,
            received_at=datetime.now(tz=UTC),
        )

    await _move_to_processed(imap, message_id=raw_msg.message_id)
    with session_scope(engine) as session:
        mark_imap_moved(session, raw_msg.message_id)
