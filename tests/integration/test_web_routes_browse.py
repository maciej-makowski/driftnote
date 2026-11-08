"""Smoke tests for the browse routes."""

from __future__ import annotations

import re
import urllib.parse
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
    # Cloud canvas is rendered with at least one positioned chip.
    assert 'class="tag-cloud-canvas"' in r.text
    assert "left:" in r.text


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


def test_calendar_marks_today_with_entry(app_with_data: tuple[FastAPI, Engine]) -> None:
    """Today's cell with an entry gets the `today has-entry` state classes."""
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    # Fixture seeds entry on 2026-05-06 with mood; iso_now is 2026-05-06T12:00:00Z.
    # Today's cell must have both `today` and `has-entry` classes (in any order).
    assert re.search(r'<td class="[^"]*\btoday\b[^"]*\bhas-entry\b', r.text) or re.search(
        r'<td class="[^"]*\bhas-entry\b[^"]*\btoday\b', r.text
    )


def test_calendar_marks_in_month_days_without_entries_as_empty(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """In-month days with no entry that aren't today get the `empty` state class."""
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    # The fixture only seeds 2026-05-06; every other in-month May day is empty.
    assert '<td class="empty">' in r.text


def test_calendar_marks_today_without_entry_as_today_empty(tmp_path: Path) -> None:
    """Today with no entry yet gets `today today-empty` (subtle amber bg)."""
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    app = FastAPI()
    install_browse_routes(app, engine=eng, iso_now=lambda: "2026-05-15T12:00:00Z")
    install_static(app)
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    assert re.search(r'<td class="[^"]*\btoday\b[^"]*\btoday-empty\b', r.text) or re.search(
        r'<td class="[^"]*\btoday-empty\b[^"]*\btoday\b', r.text
    )


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
    # Pad cells get a `dim` class plus a state class. Day-of-month sits in
    # a <div class="dom"> just like in-month cells.
    pad_doms = re.findall(
        r'<td class="dim[^"]*">\s*<a href="/entry/[^"]+"[^>]*>\s*<div class="dom">(\d+)</div>',
        r.text,
    )
    assert "27" in pad_doms
    assert "28" in pad_doms
    assert "29" in pad_doms
    assert "30" in pad_doms


def test_calendar_pad_cells_carry_state_classes(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """Pad cells get the same `empty`/`has-entry` state classes as in-month
    cells, so prev/next-month days render with the same subtle backgrounds."""
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    # Fixture only seeds 2026-05-06, so every pad cell (April + June) is empty.
    assert re.search(r'<td class="dim empty">', r.text)


def test_calendar_pad_cell_with_entry_renders_mood(tmp_path: Path) -> None:
    """An entry on the prev-month tail (e.g. Apr 30) shows its mood emoji and
    `has-entry` state class when viewing the next month's grid."""
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-04-30",
                mood="🌧️",
                body_text="april rain",
                body_md="rain",
                created_at="t",
                updated_at="t",
            ),
        )
    app = FastAPI()
    install_browse_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z")
    install_static(app)
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    # The April 30 pad cell must carry the has-entry state and the mood emoji.
    assert re.search(
        r'<td class="dim has-entry">\s*<a href="/entry/2026-04-30"[^>]*>\s*<div class="dom">30</div>\s*<div class="emoji">🌧️</div>',
        r.text,
    )


def test_calendar_cell_links_carry_full_date_aria_labels(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """Every calendar cell link names its full date for screen readers: the
    visible text is only the day number and a mood emoji, so the accessible
    name must carry the ISO date instead."""
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    labelled = re.findall(r'<a href="/entry/(\d{4}-\d{2}-\d{2})" aria-label="([^"]+)">', r.text)
    assert labelled, "calendar cell links must carry aria-labels"
    # Each label is the cell's own full date, pad cells included.
    assert all(date == label for date, label in labelled)
    assert len(labelled) == 42  # six rows of seven cells, all linked
    assert ("2026-05-06", "2026-05-06") in labelled


def test_calendar_empty_month_line_renders_for_empty_month(tmp_path: Path) -> None:
    """A month with no entries at all renders the quiet hint line pointing
    at the imap_poll drill, the likely cause of a silently empty month."""
    eng = make_engine(tmp_path / "empty.sqlite")
    init_db(eng)
    app = FastAPI()
    install_browse_routes(app, engine=eng, iso_now=lambda: "2026-05-15T12:00:00Z")
    install_static(app)
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    assert "No entries this month." in r.text
    assert 'href="/admin/runs/imap_poll"' in r.text


def test_calendar_empty_month_line_absent_when_month_has_entries(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """The hint is for fully empty months only: the fixture seeds one May entry."""
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    assert "No entries this month." not in r.text
    assert "calendar-empty" not in r.text


def test_calendar_empty_month_line_ignores_pad_cell_entries(tmp_path: Path) -> None:
    """An entry in the prev-month pad tail does not make the viewed month
    non-empty: the hint keys on in-month cells (issue #61)."""
    eng = make_engine(tmp_path / "pad.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-04-30",
                mood="🌧️",
                body_text="april rain",
                body_md="rain",
                created_at="t",
                updated_at="t",
            ),
        )
    app = FastAPI()
    install_browse_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z")
    install_static(app)
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    assert "No entries this month." in r.text


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


def test_search_results_render_tag_chips_per_hit(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """Each search hit shows the entry's tags as clickable chips."""
    app, _ = app_with_data
    r = TestClient(app).get("/search?q=risotto")
    assert r.status_code == 200
    # The fixture's seeded entry has tags ["work", "cooking"]; both must
    # render as tag-chip links in the response.
    assert 'class="tag-chip"' in r.text
    assert 'href="/?tag=work"' in r.text
    assert 'href="/?tag=cooking"' in r.text


def test_base_chrome_skip_link_head_and_landmark(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """The base template carries the phase-2 chrome: the skip link is the
    first focusable element, main is its target, and the head declares the
    dark colour scheme, the canvas theme colour, and the inline SVG favicon."""
    app, _ = app_with_data
    r = TestClient(app).get("/")
    assert r.status_code == 200
    head, sep, body = r.text.partition("</head>")
    assert sep, "page must carry a head section"
    assert '<meta name="color-scheme" content="dark">' in head
    assert '<meta name="theme-color" content="#201b26">' in head
    icon = re.search(r'<link rel="icon" href="data:image/svg\+xml,[^"]*"', head)
    assert icon is not None
    assert len(icon.group(0)) < 1024
    # The favicon payload must be a well-formed SVG, not merely a short
    # data URI. Structural check instead of an XML parser: the payload is
    # the app's own static template text (bounded, not external input), and
    # an XML parser would add XXE-hardening caveats the repo does not need
    # a new dependency for. No DOCTYPE or entity declarations are allowed,
    # which is the construct that matters if the input were untrusted.
    href = icon.group(0).split('href="', 1)[1].rsplit('"', 1)[0]
    svg = urllib.parse.unquote(href.split(",", 1)[1])
    stripped = svg.lstrip()
    assert stripped.startswith("<svg"), "favicon payload must start with the svg root"
    assert svg.count("<svg") == 1 and "</svg>" in svg
    assert "<!" not in svg, "favicon payload must not carry DOCTYPE or entity declarations"
    # The skip link is the first focusable element: nothing tabbable sits
    # between the opening body tag and the skip link. Anchors are matched
    # on their tag boundary so <article> cannot satisfy <a, and explicit
    # tabindex attributes count as tabbable too.
    body_start = body.index("<body>") + len("<body>")
    skip_start = body.index('<a class="skip-link" href="#content">')
    region = body[body_start:skip_start]
    for pattern in (
        r"<a[\s>]",
        r"<button[\s>]",
        r"<input[\s>]",
        r"<textarea[\s>]",
        r"<select[\s>]",
        r"tabindex=",
    ):
        assert re.search(pattern, region) is None, (
            f"tabbable element before the skip link: {pattern}"
        )
    # The skip link's target is the main landmark.
    assert '<main id="content">' in body
