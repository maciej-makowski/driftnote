"""Tests for the CLI commands."""

from __future__ import annotations

import contextlib
import imaplib
from datetime import date as _date
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftnote.cli import app as cli_app
from driftnote.db import init_db, make_engine, session_scope
from driftnote.filesystem.layout import entry_paths_for
from driftnote.filesystem.markdown_io import EntryDocument, write_entry
from driftnote.repository.entries import get_entry
from driftnote.repository.ingested import record_pending_prompt
from tests.conftest import MailServer


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_filesystem_only(
    data_root: Path, *, day: str = "2026-05-06", body: str = "from disk\n"
) -> None:
    paths = entry_paths_for(data_root, _date.fromisoformat(day))
    paths.dir.mkdir(parents=True, exist_ok=True)
    write_entry(
        paths.entry_md,
        EntryDocument(
            date=_date.fromisoformat(day),
            mood="💪",
            tags=["work"],
            created_at="2026-05-06T21:00:00Z",
            updated_at="2026-05-06T21:00:00Z",
            sources=["raw/x.eml"],
            body=body,
        ),
    )


def test_reindex_rebuilds_sqlite_from_filesystem(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    db_path = data_root / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = make_engine(db_path)
    init_db(eng)
    _seed_filesystem_only(data_root)

    monkeypatch.setenv("DRIFTNOTE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("DRIFTNOTE_DB_PATH", str(db_path))

    result = runner.invoke(cli_app, ["reindex"])
    assert result.exit_code == 0, result.output

    eng2 = make_engine(db_path)
    with session_scope(eng2) as session:
        entry = get_entry(session, "2026-05-06")
    assert entry is not None
    assert entry.body_md == "from disk\n"
    assert entry.mood == "💪"


def test_reindex_warns_on_uiedited_entries_without_force(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    db_path = data_root / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    make_engine(db_path)  # creates dir
    init_db(make_engine(db_path))
    paths = entry_paths_for(data_root, _date(2026, 5, 6))
    paths.dir.mkdir(parents=True, exist_ok=True)
    write_entry(
        paths.entry_md,
        EntryDocument(
            date=_date(2026, 5, 6),
            mood="💪",
            tags=[],
            created_at="2026-05-06T21:00:00Z",
            updated_at="2026-05-07T08:00:00Z",  # updated > created => UI edit
            sources=["raw/x.eml"],
            body="hand-edited\n",
        ),
    )

    monkeypatch.setenv("DRIFTNOTE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("DRIFTNOTE_DB_PATH", str(db_path))

    result = runner.invoke(cli_app, ["reindex", "--from-raw"])
    assert result.exit_code != 0
    assert "force" in result.output.lower()


def _write_min_config(path: Path) -> None:
    """Minimal valid TOML for CLI tests; IMAP/SMTP host/port overridden via env."""
    path.write_text(
        "[schedule]\n"
        'daily_prompt   = "0 21 * * *"\n'
        'weekly_digest  = "0 8 * * 1"\n'
        'monthly_digest = "0 8 1 * *"\n'
        'yearly_digest  = "0 8 1 1 *"\n'
        'imap_poll      = "*/5 * * * *"\n'
        'timezone       = "Europe/London"\n'
        "[email]\n"
        'imap_folder            = "INBOX"\n'
        'imap_processed_folder  = "INBOX.Processed"\n'
        'recipient              = "you@example.com"\n'
        'sender_name            = "Driftnote"\n'
        'imap_host              = "x"\n'
        "imap_port              = 993\n"
        "imap_tls               = true\n"
        'smtp_host              = "x"\n'
        "smtp_port              = 587\n"
        "smtp_tls               = false\n"
        "smtp_starttls          = true\n"
        "[prompt]\n"
        'subject_template = "[Driftnote] How was {date}?"\n'
        'body_template    = "templates/emails/prompt.txt.j2"\n'
        "[parsing]\n"
        "mood_regex = '^\\\\s*Mood:\\\\s*(\\\\S+)'\n"
        "tag_regex  = '#(\\\\w+)'\n"
        "max_photos = 4\n"
        "max_videos = 2\n"
        "[digests]\n"
        "weekly_enabled  = true\n"
        "monthly_enabled = true\n"
        "yearly_enabled  = true\n"
        "[backup]\n"
        "retain_months = 12\n"
        "encrypt       = false\n"
        'age_key_path  = ""\n'
        "[disk]\n"
        "warn_percent  = 80\n"
        "alert_percent = 95\n"
        'check_cron    = "0 */6 * * *"\n'
        'data_path     = "/tmp"\n'
    )


def test_poll_responses_help_lists_command(runner: CliRunner) -> None:
    """Sanity: the new CLI command is registered and shows up in --help."""
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "poll-responses" in result.output


def test_poll_responses_ingests_pending_reply(
    mail_server: MailServer,
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: a reply in GreenMail's INBOX is ingested by `poll-responses`."""
    cfg_path = tmp_path / "config.toml"
    _write_min_config(cfg_path)
    data_root = tmp_path / "data"
    db_path = data_root / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = make_engine(db_path)
    init_db(eng)

    # Wipe any state left by other integration tests sharing the session-scoped
    # GreenMail container.
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    for folder in ("INBOX", "INBOX.Processed"):
        with contextlib.suppress(Exception):
            mb.select(folder)
            mb.store("1:*", "+FLAGS", r"\Deleted")
            mb.expunge()
    with contextlib.suppress(Exception):
        mb.create("INBOX.Processed")
    mb.logout()

    # Anchor the reply to a pending prompt.
    prompt_msg_id = "<prompt-2026-05-06@driftnote>"
    with session_scope(eng) as session:
        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id=prompt_msg_id,
            sent_at="2026-05-06T21:00:00Z",
        )

    # Drop a reply directly into GreenMail's INBOX via raw IMAP APPEND.
    msg = EmailMessage()
    msg["From"] = mail_server.address
    msg["To"] = mail_server.address
    msg["Subject"] = "Re: [Driftnote] How was 2026-05-06?"
    msg["Message-ID"] = make_msgid(domain="example")
    msg["Date"] = "Wed, 06 May 2026 21:30:15 +0000"
    msg["In-Reply-To"] = prompt_msg_id
    msg["References"] = prompt_msg_id
    msg.set_content("Mood: 💪\n\npolled via CLI #cli")
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.append("INBOX", "", imaplib.Time2Internaldate(0), msg.as_bytes())
    mb.logout()

    # Wire the CLI's load_config + transports_from_config to talk to GreenMail.
    monkeypatch.setenv("DRIFTNOTE_CONFIG", str(cfg_path))
    monkeypatch.setenv("DRIFTNOTE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("DRIFTNOTE_DB_PATH", str(db_path))
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", mail_server.user)
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", mail_server.password)
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    monkeypatch.setenv("DRIFTNOTE_ENVIRONMENT", "dev")
    monkeypatch.setenv("DRIFTNOTE_IMAP_HOST", mail_server.host)
    monkeypatch.setenv("DRIFTNOTE_IMAP_PORT", str(mail_server.imap_port))
    monkeypatch.setenv("DRIFTNOTE_IMAP_TLS", "false")

    result = runner.invoke(cli_app, ["poll-responses"])
    assert result.exit_code == 0, result.output
    assert "poll complete" in result.output

    # Entry now in SQLite + filesystem.
    eng2 = make_engine(db_path)
    with session_scope(eng2) as session:
        entry = get_entry(session, "2026-05-06")
    assert entry is not None
    assert entry.mood == "💪"
    entry_md = data_root / "entries" / "2026" / "05" / "06" / "entry.md"
    assert entry_md.exists()
