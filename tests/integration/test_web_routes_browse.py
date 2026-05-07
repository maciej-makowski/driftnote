"""Smoke tests for the browse routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.entries import EntryRecord, replace_tags, upsert_entry
from driftnote.web.routes_browse import install_browse_routes, install_static


@pytest.fixture
def app_with_data(tmp_path: Path) -> tuple[FastAPI, Engine]:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-05-06",
                mood="💪",
                body_text="risotto night",
                body_md="# Risotto night\n\nIt was great.",
                created_at="t",
                updated_at="t",
            ),
        )
        replace_tags(session, "2026-05-06", ["work", "cooking"])
    app = FastAPI()
    install_browse_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z")
    install_static(app)
    return app, eng


def test_calendar_page_renders(app_with_data: tuple[FastAPI, Engine]) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    assert "💪" in r.text


def test_entry_page_renders_markdown(app_with_data: tuple[FastAPI, Engine]) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/entry/2026-05-06")
    assert r.status_code == 200
    assert "<h1>Risotto night</h1>" in r.text
    assert "#work" in r.text or "work" in r.text


def test_tags_page_lists_tags(app_with_data: tuple[FastAPI, Engine]) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/tags")
    assert r.status_code == 200
    assert "work" in r.text
    assert "cooking" in r.text


def test_search_returns_fts_hits(app_with_data: tuple[FastAPI, Engine]) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/search?q=risotto")
    assert r.status_code == 200
    assert "2026-05-06" in r.text
