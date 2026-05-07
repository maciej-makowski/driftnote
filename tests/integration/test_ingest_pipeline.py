"""End-to-end tests for ingestion pipeline (no real IMAP/SMTP)."""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine

from driftnote.config import (
    BackupConfig,
    Config,
    DigestsConfig,
    DiskConfig,
    EmailConfig,
    ParsingConfig,
    PromptConfig,
    ScheduleConfig,
    Secrets,
)
from driftnote.db import init_db, make_engine, session_scope
from driftnote.ingest.pipeline import IngestionResult, ingest_one
from driftnote.repository.entries import get_entry, list_entries_by_tag
from driftnote.repository.ingested import get_ingested, is_ingested
from driftnote.repository.media import list_media


def _eml_bytes(
    *,
    subject: str = "[Driftnote] How was 2026-05-06?",
    body_text: str = "Mood: 💪\n\nLong day at work. #work",
    in_reply_to: str | None = "<prompt-2026-05-06@driftnote>",
    attachments: list[tuple[str, str, bytes]] | None = None,
    message_id: str | None = None,
) -> tuple[bytes, str]:
    msg = EmailMessage()
    msg["From"] = "you@gmail.com"
    msg["To"] = "you@gmail.com"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id or make_msgid(domain="driftnote")
    msg["Date"] = "Wed, 06 May 2026 21:30:15 +0000"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body_text)
    for filename, mime, payload in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes(), msg["Message-ID"]


def _config(*, mood_regex: str = r"^\s*Mood:\s*(\S+)", tag_regex: str = r"#(\w+)") -> Config:
    return Config(
        schedule=ScheduleConfig(
            daily_prompt="0 21 * * *",
            weekly_digest="0 8 * * 1",
            monthly_digest="0 8 1 * *",
            yearly_digest="0 8 1 1 *",
            imap_poll="*/5 * * * *",
            timezone="Europe/London",
        ),
        email=EmailConfig(
            imap_folder="INBOX",
            imap_processed_folder="INBOX.Processed",
            recipient="you@gmail.com",
            sender_name="Driftnote",
            imap_host="x",
            imap_port=993,
            imap_tls=True,
            smtp_host="x",
            smtp_port=587,
            smtp_tls=False,
            smtp_starttls=True,
        ),
        prompt=PromptConfig(subject_template="[Driftnote] {date}", body_template="t.j2"),
        parsing=ParsingConfig(
            mood_regex=mood_regex, tag_regex=tag_regex, max_photos=4, max_videos=2
        ),
        digests=DigestsConfig(weekly_enabled=True, monthly_enabled=True, yearly_enabled=True),
        backup=BackupConfig(retain_months=12, encrypt=False, age_key_path=""),
        disk=DiskConfig(
            warn_percent=80,
            alert_percent=95,
            check_cron="0 */6 * * *",
            data_path="/var/driftnote/data",
        ),
        secrets=Secrets(
            gmail_user="you@gmail.com",
            gmail_app_password=SecretStr("p"),
            cf_access_aud="aud",
            cf_team_domain="t.example.com",
        ),
    )


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Engine, Path, Config]:
    engine = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(engine)
    data_root = tmp_path / "data"
    cfg = _config()
    return engine, data_root, cfg


def test_ingest_creates_entry_and_db_row(setup: tuple[Engine, Path, Config]) -> None:
    engine, data_root, cfg = setup
    raw, mid = _eml_bytes()

    with session_scope(engine) as session:
        # Pre-record the prompt that this is in reply to, so the date anchor works.
        from driftnote.repository.ingested import record_pending_prompt

        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="2026-05-06T21:00:00Z",
        )

    result = ingest_one(
        raw=raw,
        config=cfg,
        engine=engine,
        data_root=data_root,
        received_at=datetime(2026, 5, 6, 21, 30, 15, tzinfo=UTC),
    )

    assert isinstance(result, IngestionResult)
    assert result.ingested is True
    assert result.entry_date == "2026-05-06"
    assert (data_root / "entries" / "2026" / "05" / "06" / "entry.md").exists()
    assert (
        data_root / "entries" / "2026" / "05" / "06" / "raw" / "2026-05-06T21-30-15Z.eml"
    ).exists()

    with session_scope(engine) as session:
        entry = get_entry(session, "2026-05-06")
        ing = get_ingested(session, mid)
        tagged = list_entries_by_tag(session, "work")
    assert entry is not None
    assert entry.mood == "💪"
    assert ing is not None and ing.imap_moved == 0
    assert [e.date for e in tagged] == ["2026-05-06"]


def test_ingest_is_idempotent_on_message_id(setup: tuple[Engine, Path, Config]) -> None:
    engine, data_root, cfg = setup
    raw, _mid = _eml_bytes()

    with session_scope(engine) as session:
        from driftnote.repository.ingested import record_pending_prompt

        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="t",
        )

    received_at = datetime(2026, 5, 6, 21, 30, 15, tzinfo=UTC)
    r1 = ingest_one(
        raw=raw, config=cfg, engine=engine, data_root=data_root, received_at=received_at
    )
    r2 = ingest_one(
        raw=raw, config=cfg, engine=engine, data_root=data_root, received_at=received_at
    )
    assert r1.ingested is True
    assert r2.ingested is False  # second call short-circuits — already ingested
    # Only one raw .eml file exists (no duplicate).
    raws = list((data_root / "entries" / "2026" / "05" / "06" / "raw").glob("*.eml"))
    assert len(raws) == 1


def test_ingest_appends_for_second_reply_same_date(setup: tuple[Engine, Path, Config]) -> None:
    engine, data_root, cfg = setup

    with session_scope(engine) as session:
        from driftnote.repository.ingested import record_pending_prompt

        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="t",
        )

    raw1, _ = _eml_bytes(body_text="Mood: 💪\n\nfirst section #work")
    raw2, _ = _eml_bytes(body_text="afterthought #cooking")

    ingest_one(
        raw=raw1,
        config=cfg,
        engine=engine,
        data_root=data_root,
        received_at=datetime(2026, 5, 6, 21, 30, 15, tzinfo=UTC),
    )
    ingest_one(
        raw=raw2,
        config=cfg,
        engine=engine,
        data_root=data_root,
        received_at=datetime(2026, 5, 7, 2, 15, 22, tzinfo=UTC),
    )

    entry_md = (data_root / "entries" / "2026" / "05" / "06" / "entry.md").read_text()
    assert "first section" in entry_md
    assert "afterthought" in entry_md
    # After stripping frontmatter (split off at first \n---\n), the body should contain
    # a section separator (---) between the two diary sections.
    _frontmatter, _sep, body = entry_md.partition("\n---\n")
    assert "---" in body  # body separator between sections

    with session_scope(engine) as session:
        tagged_work = list_entries_by_tag(session, "work")
        tagged_cook = list_entries_by_tag(session, "cooking")
    assert tagged_work and tagged_cook  # tags accumulate across sections


def test_ingest_falls_back_to_date_header_when_no_matching_prompt(
    setup: tuple[Engine, Path, Config],
) -> None:
    engine, data_root, cfg = setup
    raw, _ = _eml_bytes(in_reply_to=None)
    received_at = datetime(2026, 5, 6, 21, 30, 15, tzinfo=UTC)

    result = ingest_one(
        raw=raw, config=cfg, engine=engine, data_root=data_root, received_at=received_at
    )

    assert result.ingested is True
    # Entry date taken from the message Date header (Wed, 06 May 2026 21:30:15 +0000)
    assert result.entry_date == "2026-05-06"


def test_ingest_drops_attachments_over_limits(setup: tuple[Engine, Path, Config]) -> None:
    engine, data_root, cfg = setup
    cfg = cfg.model_copy(update={"parsing": cfg.parsing.model_copy(update={"max_photos": 1})})
    raw, _ = _eml_bytes(
        attachments=[
            ("a.jpg", "image/jpeg", b"\xff\xd8\xff\xd9"),
            ("b.jpg", "image/jpeg", b"\xff\xd8\xff\xd9"),
        ],
    )

    with session_scope(engine) as session:
        from driftnote.repository.ingested import record_pending_prompt

        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="t",
        )

    received_at = datetime(2026, 5, 6, 21, 30, 15, tzinfo=UTC)
    ingest_one(raw=raw, config=cfg, engine=engine, data_root=data_root, received_at=received_at)

    with session_scope(engine) as session:
        media_rows = list_media(session, "2026-05-06")
    assert [m.filename for m in media_rows] == ["a.jpg"]


def test_ingest_rolls_back_on_filesystem_failure(
    setup: tuple[Engine, Path, Config], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, data_root, cfg = setup
    raw, mid = _eml_bytes()

    with session_scope(engine) as session:
        from driftnote.repository.ingested import record_pending_prompt

        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="t",
        )

    # Simulate a filesystem failure in markdown write.
    # Patch the name as imported in the pipeline module so the reference is replaced.
    import driftnote.ingest.pipeline as _pipeline

    def _explode(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(_pipeline, "write_entry", _explode)

    with pytest.raises(OSError):
        ingest_one(
            raw=raw,
            config=cfg,
            engine=engine,
            data_root=data_root,
            received_at=datetime(2026, 5, 6, 21, 30, 15, tzinfo=UTC),
        )

    with session_scope(engine) as session:
        assert not is_ingested(session, mid)
    # No partial entry.md or raw/*.eml left behind.
    entry_dir = data_root / "entries" / "2026" / "05" / "06"
    assert not entry_dir.exists() or not any(entry_dir.iterdir())
