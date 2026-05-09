"""Tests for media-serving and admin dashboard routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import finish_job_run, record_job_run
from driftnote.web.routes_admin import install_admin_routes
from driftnote.web.routes_media import install_media_routes


@pytest.fixture
def setup(tmp_path: Path) -> tuple[FastAPI, Engine, Path]:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    data_root = tmp_path / "data"
    # Drop a tiny image into the entries tree.
    entry_dir = data_root / "entries" / "2026" / "05" / "06"
    (entry_dir / "originals").mkdir(parents=True)
    (entry_dir / "web").mkdir()
    (entry_dir / "thumbs").mkdir()
    (entry_dir / "originals" / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (entry_dir / "web" / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (entry_dir / "thumbs" / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    app = FastAPI()
    install_media_routes(app, data_root=data_root)
    install_admin_routes(
        app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z", environment="prod"
    )
    return app, eng, data_root


def test_media_serves_thumb(setup: tuple[FastAPI, Engine, Path]) -> None:
    fapp, _, _ = setup
    r = TestClient(fapp).get("/media/2026-05-06/thumb/photo.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert r.content[:2] == b"\xff\xd8"


def test_media_404_for_missing_file(setup: tuple[FastAPI, Engine, Path]) -> None:
    fapp, _, _ = setup
    r = TestClient(fapp).get("/media/2026-05-06/web/missing.jpg")
    assert r.status_code == 404


def test_media_rejects_path_traversal(setup: tuple[FastAPI, Engine, Path]) -> None:
    fapp, _, _ = setup
    r = TestClient(fapp).get("/media/2026-05-06/thumb/..%2F..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_admin_index_lists_each_job_card(setup: tuple[FastAPI, Engine, Path]) -> None:
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-05-06T08:00:01Z",
            status="ok",
            detail="ingested 1",
        )
    r = TestClient(fapp).get("/admin")
    assert r.status_code == 200
    assert "imap_poll" in r.text
    assert "ingested 1" in r.text


def test_admin_acknowledge(setup: tuple[FastAPI, Engine, Path]) -> None:
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-05-06T08:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    r = TestClient(fapp, follow_redirects=False).post(f"/admin/runs/{rid}/ack")
    assert r.status_code in (200, 303)
    from driftnote.repository.jobs import recent_failures

    with session_scope(eng) as session:
        unack = recent_failures(
            session, now="2026-05-06T12:00:00Z", days=7, only_unacknowledged=True
        )
    assert unack == []


def test_admin_test_controls_hidden_in_prod(setup: tuple[FastAPI, Engine, Path]) -> None:
    fapp, _, _ = setup
    r = TestClient(fapp).get("/admin")
    assert r.status_code == 200
    assert "Test controls" not in r.text


def test_admin_test_controls_visible_in_dev(tmp_path: Path) -> None:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    app = FastAPI()
    install_admin_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z", environment="dev")
    r = TestClient(app).get("/admin")
    assert r.status_code == 200
    assert "Test controls" in r.text
    # Each of the five buttons is present.
    assert 'action="/admin/test/send-prompt"' in r.text
    assert 'action="/admin/test/send-digest/weekly"' in r.text
    assert 'action="/admin/test/send-digest/monthly"' in r.text
    assert 'action="/admin/test/send-digest/yearly"' in r.text
    assert 'action="/admin/test/poll-now"' in r.text


def test_admin_test_endpoints_404_in_prod(setup: tuple[FastAPI, Engine, Path]) -> None:
    fapp, _, _ = setup
    client = TestClient(fapp)
    for path in (
        "/admin/test/send-prompt",
        "/admin/test/send-digest/weekly",
        "/admin/test/send-digest/monthly",
        "/admin/test/send-digest/yearly",
        "/admin/test/poll-now",
    ):
        r = client.post(path)
        assert r.status_code == 404, f"{path} should 404 in prod, got {r.status_code}"


def test_admin_notice_banner_renders_when_query_param_set(tmp_path: Path) -> None:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    app = FastAPI()
    install_admin_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z", environment="dev")
    r = TestClient(app).get("/admin?notice=prompt-sent")
    assert r.status_code == 200
    assert "prompt-sent" in r.text


def test_admin_renders_status_dot_class(setup: tuple[FastAPI, Engine, Path]) -> None:
    """Each job card includes a colored dot reflecting last_status."""
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-05-06T08:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    r = TestClient(fapp).get("/admin")
    assert r.status_code == 200
    # The error dot appears in the imap_poll card.
    assert 'class="dot dot-error"' in r.text
