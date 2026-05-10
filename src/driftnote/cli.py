"""Typer CLI entrypoints: serve, reindex, restore-imap, send-prompt, poll-responses."""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path

import typer

from driftnote.bootstrap import load_env
from driftnote.db import init_db, make_engine, session_scope
from driftnote.filesystem.markdown_io import read_entry
from driftnote.repository.entries import EntryRecord, replace_tags, upsert_entry
from driftnote.repository.media import MediaInput, replace_media

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Driftnote CLI")


@app.callback()
def _bootstrap() -> None:
    """Load DRIFTNOTE_HOME/.env before any subcommand runs."""
    load_env()


def _data_root() -> Path:
    return Path(os.environ.get("DRIFTNOTE_DATA_ROOT", "/var/driftnote/data"))


def _db_path() -> Path:
    explicit = os.environ.get("DRIFTNOTE_DB_PATH")
    if explicit:
        return Path(explicit)
    return _data_root() / "index.sqlite"


def _walk_entries(data_root: Path):  # type: ignore[no-untyped-def]
    base = data_root / "entries"
    if not base.exists():
        return
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            for day_dir in sorted(month_dir.iterdir()):
                if (day_dir / "entry.md").exists():
                    yield day_dir / "entry.md"


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000) -> None:  # noqa: S104
    """Start the FastAPI app via uvicorn."""
    import uvicorn

    from driftnote.app import create_app

    uvicorn.run(create_app, factory=True, host=host, port=port)


@app.command()
def reindex(
    from_raw: bool = typer.Option(False, "--from-raw", help="Re-derive entry.md from raw/*.eml"),
    force: bool = typer.Option(False, "--force", help="Override the UI-edits guard"),
) -> None:
    """Rebuild SQLite index from filesystem entries (and optionally re-parse raw .eml)."""
    data_root = _data_root()
    db_path = _db_path()
    engine = make_engine(db_path)
    init_db(engine)

    if from_raw and not force:
        for entry_md in _walk_entries(data_root):
            doc = read_entry(entry_md)
            if doc.updated_at > doc.created_at:
                typer.echo(
                    f"refusing to overwrite UI-edited entry {entry_md} "
                    "(updated_at > created_at). Pass --force to override.",
                    err=True,
                )
                raise typer.Exit(2)

    if from_raw:
        # Iterate every entry, parse all raw/*.eml in order, rewrite entry.md.
        from driftnote.config import load_config

        config_path = Path(os.environ["DRIFTNOTE_CONFIG"])
        config = load_config(config_path)
        from driftnote.ingest.pipeline import ingest_one

        for entry_md in _walk_entries(data_root):
            day_dir = entry_md.parent
            (day_dir / "entry.md").unlink(missing_ok=True)
            for eml in sorted((day_dir / "raw").glob("*.eml")):
                received_at = _parse_received_from_filename(eml.name)
                ingest_one(
                    raw=eml.read_bytes(),
                    config=config,
                    engine=engine,
                    data_root=data_root,
                    received_at=received_at,
                )

    # Rebuild SQLite from current entry.md state.
    for entry_md in _walk_entries(data_root):
        doc = read_entry(entry_md)
        with session_scope(engine) as session:
            upsert_entry(
                session,
                EntryRecord(
                    date=doc.date.isoformat(),
                    mood=doc.mood,
                    body_text=doc.body,
                    body_md=doc.body,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                ),
            )
            replace_tags(session, doc.date.isoformat(), list(doc.tags))
            replace_media(
                session,
                doc.date.isoformat(),
                [
                    MediaInput(kind="photo", filename=p.filename, caption=p.caption)
                    for p in doc.photos
                ]
                + [
                    MediaInput(kind="video", filename=v.filename, caption=v.caption)
                    for v in doc.videos
                ],
            )

    typer.echo("reindex complete")


@app.command(name="restore-imap")
def restore_imap(
    since: str = typer.Option(..., "--since", help="YYYY-MM-DD"),
    until: str | None = typer.Option(None, "--until", help="YYYY-MM-DD (inclusive)"),
) -> None:
    """Re-fetch matching emails from IMAP and run them through ingestion."""
    asyncio.run(_run_restore(since, until))


@app.command(name="send-prompt")
def send_prompt(
    date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD; default today"),
) -> None:
    """Manually send today's (or another day's) prompt."""
    asyncio.run(_run_send_prompt(date))


@app.command(name="poll-responses")
def poll_responses() -> None:
    """One-off IMAP poll: drain pending IMAP-move retries and ingest new replies.

    Equivalent to a single tick of the scheduled imap_poll job. Useful for
    on-demand processing without waiting for the next 5-minute cron tick, or
    when the scheduler isn't running locally.
    """
    asyncio.run(_run_poll_responses())


async def _run_restore(since: str, until: str | None) -> None:
    from driftnote.config import load_config

    config = load_config(Path(os.environ["DRIFTNOTE_CONFIG"]))
    engine = make_engine(_db_path())
    init_db(engine)

    from driftnote.mail.imap import _connect, _extract_rfc822
    from driftnote.mail.transport import transports_from_config

    imap_t, _ = transports_from_config(config)

    client = await _connect(imap_t)
    try:
        for folder in (imap_t.inbox_folder, imap_t.processed_folder):
            await client.select(folder)
            criteria = f"SINCE {_imap_date(since)}"
            if until:
                criteria += f" BEFORE {_imap_date(_inclusive_until(until))}"
            result, data = await client.search(criteria)
            if result != "OK" or not data or not data[0]:
                continue
            for ident in data[0].split():
                ident_str = ident.decode("ascii")
                _fetch_result, fetch_data = await client.fetch(ident_str, "(RFC822)")
                raw = _extract_rfc822(fetch_data)
                if raw is None:
                    continue
                from driftnote.ingest.pipeline import ingest_one

                ingest_one(
                    raw=raw,
                    config=config,
                    engine=engine,
                    data_root=_data_root(),
                    received_at=datetime.now(tz=UTC),
                )
    finally:
        with contextlib.suppress(Exception):
            await client.logout()

    typer.echo("restore-imap complete")


async def _run_poll_responses() -> None:
    from driftnote.config import load_config
    from driftnote.mail.transport import transports_from_config
    from driftnote.repository.jobs import last_run
    from driftnote.scheduler.poll_job import run_poll_job
    from driftnote.scheduler.runner import job_run

    config = load_config(Path(os.environ["DRIFTNOTE_CONFIG"]))
    engine = make_engine(_db_path())
    init_db(engine)
    imap_t, _ = transports_from_config(config)

    with job_run(engine, "imap_poll"):
        await run_poll_job(config=config, engine=engine, data_root=_data_root(), imap=imap_t)

    with session_scope(engine) as session:
        latest = last_run(session, "imap_poll")
    if latest is None:
        typer.echo("poll complete")
    else:
        typer.echo(f"poll complete: status={latest.status} finished_at={latest.finished_at}")


async def _run_send_prompt(date_str: str | None) -> None:
    from driftnote.config import load_config
    from driftnote.mail.transport import transports_from_config
    from driftnote.scheduler.prompt_job import run_prompt_job

    config = load_config(Path(os.environ["DRIFTNOTE_CONFIG"]))
    engine = make_engine(_db_path())
    init_db(engine)
    _, smtp = transports_from_config(config)

    today = _date.fromisoformat(date_str) if date_str else _date.today()

    # Mirror the path-resolution used by the lifespan in driftnote.app.create_app
    # so CLI-driven and scheduler-driven sends use the same template.
    web_root = Path(__file__).parent / "web"
    body_template_path = web_root / config.prompt.body_template
    if not body_template_path.exists():
        raise typer.BadParameter(
            f"prompt template not found at {body_template_path}; "
            f"check [prompt].body_template in {os.environ['DRIFTNOTE_CONFIG']}",
        )
    body = body_template_path.read_text(encoding="utf-8")

    await run_prompt_job(
        engine=engine,
        smtp=smtp,
        recipient=config.email.recipient,
        subject_template=config.prompt.subject_template,
        body_template_text=body,
        today=today,
    )
    typer.echo("prompt sent")


def _imap_date(iso: str) -> str:
    """Convert YYYY-MM-DD to IMAP DD-Mon-YYYY."""
    d = _date.fromisoformat(iso)
    return d.strftime("%d-%b-%Y")


def _inclusive_until(iso: str) -> str:
    from datetime import timedelta

    d = _date.fromisoformat(iso)
    return (d + timedelta(days=1)).isoformat()


def _parse_received_from_filename(name: str) -> datetime:
    from driftnote.filesystem.layout import parse_eml_received_at

    return parse_eml_received_at(name)
