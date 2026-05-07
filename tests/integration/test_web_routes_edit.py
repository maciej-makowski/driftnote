"""Edit-route smoke tests."""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.filesystem.layout import entry_paths_for
from driftnote.filesystem.markdown_io import EntryDocument, write_entry
from driftnote.repository.entries import EntryRecord, get_entry, upsert_entry
from driftnote.web.routes_edit import install_edit_routes


@pytest.fixture
def app(tmp_path: Path) -> tuple[FastAPI, Engine, Path]:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    data_root = tmp_path / "data"
    # Pre-seed an entry on disk + index.
    paths = entry_paths_for(data_root, _date(2026, 5, 6))
    paths.dir.mkdir(parents=True, exist_ok=True)
    write_entry(
        paths.entry_md,
        EntryDocument(
            date=_date(2026, 5, 6),
            mood="💪",
            tags=["work"],
            created_at="t",
            updated_at="t",
            sources=["raw/x.eml"],
            body="initial body\n",
        ),
    )
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-05-06",
                mood="💪",
                body_text="initial body",
                body_md="initial body",
                created_at="t",
                updated_at="t",
            ),
        )
    fapp = FastAPI()
    install_edit_routes(
        fapp, engine=eng, data_root=data_root, iso_now=lambda: "2026-05-07T08:00:00Z"
    )
    return fapp, eng, data_root


def test_edit_form_renders(app: tuple[FastAPI, Engine, Path]) -> None:
    fapp, _, _ = app
    r = TestClient(fapp).get("/entry/2026-05-06/edit")
    assert r.status_code == 200
    assert "initial body" in r.text


def test_edit_post_updates_entry_md_and_db(app: tuple[FastAPI, Engine, Path]) -> None:
    fapp, eng, data_root = app
    r = TestClient(fapp, follow_redirects=False).post(
        "/entry/2026-05-06",
        data={"mood": "🎉", "tags": "work, party", "body": "updated body"},
    )
    assert r.status_code in (200, 303)
    with session_scope(eng) as session:
        entry = get_entry(session, "2026-05-06")
    assert entry is not None
    assert entry.mood == "🎉"
    assert "updated body" in entry.body_md

    paths = entry_paths_for(data_root, _date(2026, 5, 6))
    md_text = paths.entry_md.read_text()
    assert "updated body" in md_text
    assert "🎉" in md_text
    assert "raw/x.eml" in md_text  # raw sources preserved


def test_preview_endpoint_renders_markdown_to_html(app: tuple[FastAPI, Engine, Path]) -> None:
    fapp, _, _ = app
    r = TestClient(fapp).post("/preview", data={"body": "# hi\n\n**there**"})
    assert r.status_code == 200
    assert "<h1>hi</h1>" in r.text
    assert "<strong>there</strong>" in r.text
