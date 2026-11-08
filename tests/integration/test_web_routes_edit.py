"""Edit-route smoke tests."""

from __future__ import annotations

import re
from datetime import date as _date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.filesystem.layout import entry_paths_for
from driftnote.filesystem.markdown_io import EntryDocument, write_entry
from driftnote.repository.entries import EntryRecord, get_entry, replace_tags, upsert_entry
from driftnote.web.routes_browse import install_browse_routes
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


_PRELOAD = (
    '<link rel="preload" href="/static/fonts/newsreader-400.woff2"'
    ' as="font" type="font/woff2" crossorigin>'
)


def test_edit_page_preloads_roman_face(app: tuple[FastAPI, Engine, Path]) -> None:
    """The edit page preloads the roman face via the head_extra block: the
    preview panel renders the serif since phase 5, so the face has a
    consumer here (phase 4 deliberately left the block empty to avoid a
    preloaded-but-unused console warning)."""
    fapp, _, _ = app
    r = TestClient(fapp).get("/entry/2026-05-06/edit")
    assert r.status_code == 200
    head = r.text.partition("</head>")[0]
    assert _PRELOAD in head
    # Only the roman face preloads: italic and latin-ext fetch on demand
    # through unicode-range, exactly like the entry page.
    assert "newsreader-400-italic" not in head
    assert "latin-ext" not in head


def test_edit_page_mood_input_names_itself(app: tuple[FastAPI, Engine, Path]) -> None:
    """The mood input carries the design's aria-label for screen readers;
    the wrapped label stays for sighted users."""
    fapp, _, _ = app
    r = TestClient(fapp).get("/entry/2026-05-06/edit")
    assert r.status_code == 200
    assert re.search(r'<input name="mood"[^>]*aria-label="Mood, one emoji"', r.text)


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


def test_preview_escapes_script_tags(app: tuple[FastAPI, Engine, Path]) -> None:
    """Regression: raw HTML in preview body must NOT pass through to the browser (XSS hardening)."""
    fapp, _, _ = app
    r = TestClient(fapp).post("/preview", data={"body": "<script>alert(1)</script>hello"})
    assert r.status_code == 200
    assert "<script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_entry_detail_after_tag_edit_shows_new_tags_and_no_store(tmp_path: Path) -> None:
    """Regression #23: after editing tags and being redirected to entry detail,
    the rendered tag list must reflect the new tags on the FIRST page load
    (no hard refresh required). This requires the entry detail response to
    carry a no-cache directive so that browsers / proxies / Cloudflare Access
    don't serve the pre-edit HTML across the 303 redirect."""
    # Set up the same shared engine + data root for both edit and browse routes.
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    data_root = tmp_path / "data"
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
        replace_tags(session, "2026-05-06", ["work"])
    fapp = FastAPI()
    install_edit_routes(
        fapp, engine=eng, data_root=data_root, iso_now=lambda: "2026-05-07T08:00:00Z"
    )
    install_browse_routes(fapp, engine=eng, iso_now=lambda: "2026-05-07T08:00:00Z")

    client = TestClient(fapp, follow_redirects=False)
    # POST the edit with new tags.
    post = client.post(
        "/entry/2026-05-06",
        data={"mood": "💪", "tags": "cooking, reading", "body": "updated body"},
    )
    assert post.status_code == 303
    # Now GET the entry detail (the redirect target) WITHOUT following the
    # redirect so we observe the response headers + body the browser sees.
    get = client.get("/entry/2026-05-06")
    assert get.status_code == 200
    # The new tags must be in the body.
    assert "cooking" in get.text
    assert "reading" in get.text
    # The old tag must NOT be rendered as a tag link.
    assert 'href="/?tag=work"' not in get.text
    # The response must declare itself uncacheable so that the browser /
    # any intermediary doesn't serve a stale copy across the 303 redirect.
    cache_control = get.headers.get("cache-control", "").lower()
    assert any(token in cache_control for token in ("no-store", "no-cache", "must-revalidate")), (
        f"expected no-cache directive, got {cache_control!r}"
    )


def test_edit_page_carries_the_htmx_script(app: tuple[FastAPI, Engine, Path]) -> None:
    """The htmx include moved off base.html.j2 in phase 6: the edit page is
    one of the two consumers (its textarea hx-posts /preview), so its
    head_extra block now carries the script in base's exact form, beside
    the phase-5 roman preload."""
    fapp, _, _ = app
    r = TestClient(fapp).get("/entry/2026-05-06/edit")
    assert r.status_code == 200
    head = r.text.partition("</head>")[0]
    assert '<script src="/static/htmx.min.js" defer></script>' in head
    assert _PRELOAD in head
