"""Smoke tests for the browse routes."""

from __future__ import annotations

import re
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


def test_search_invalid_fts_returns_200_with_error(app_with_data: tuple[FastAPI, Engine]) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/search?q=foo+OR+%28bar")  # unmatched paren
    assert r.status_code == 200
    assert "invalid" in r.text.lower()


def test_calendar_page_renders_pad_cell_day_numbers(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """May 2026 starts Friday: Mon..Thu of week 1 are April 27..30. The grid
    must render those day numbers in cells flagged dim."""
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    # Six body rows of seven cells each, plus one header row.
    assert r.text.count("<tr>") == 7
    # Pad cells live inside <td class="dim"> with a <div class="dom"> day
    # number. Extract every pad-cell day number to verify the prev-month
    # tail (Apr 27..30) is rendered — these days do not collide with any
    # in-month May date and so prove the {% else %} branch of the template
    # actually runs.
    pad_doms = re.findall(
        r'<td class="dim">\s*<div class="dom">(\d+)</div>',
        r.text,
    )
    assert "27" in pad_doms
    assert "28" in pad_doms
    assert "29" in pad_doms
    assert "30" in pad_doms


def test_entry_page_escapes_script_tags(tmp_path: Path) -> None:
    """Regression: raw HTML in body_md must NOT pass through to the browser (XSS hardening)."""
    eng = make_engine(tmp_path / "xss.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-06-01",
                mood=None,
                body_text="This is a body.",
                body_md="<script>alert(1)</script>This is a body.",
                created_at="t",
                updated_at="t",
            ),
        )
    app = FastAPI()
    install_browse_routes(app, engine=eng, iso_now=lambda: "2026-06-01T12:00:00Z")
    r = TestClient(app).get("/entry/2026-06-01")
    assert r.status_code == 200
    assert "<script>" not in r.text
    assert "&lt;script&gt;" in r.text
