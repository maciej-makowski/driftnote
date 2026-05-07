"""Tests for the CLI commands."""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftnote.cli import app as cli_app
from driftnote.db import init_db, make_engine, session_scope
from driftnote.filesystem.layout import entry_paths_for
from driftnote.filesystem.markdown_io import EntryDocument, write_entry
from driftnote.repository.entries import get_entry


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
