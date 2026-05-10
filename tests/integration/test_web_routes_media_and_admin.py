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


def test_admin_ack_all_acks_every_unacked_failure_for_job(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        ids = []
        for hour in (6, 7, 8):
            rid = record_job_run(session, job="imap_poll", started_at=f"2026-05-06T0{hour}:00:00Z")
            finish_job_run(
                session,
                run_id=rid,
                finished_at=f"2026-05-06T0{hour}:00:01Z",
                status="error",
                error_kind="imap_auth",
            )
            ids.append(rid)
        # An ok run should remain unaffected.
        ok_id = record_job_run(session, job="imap_poll", started_at="2026-05-06T05:00:00Z")
        finish_job_run(session, run_id=ok_id, finished_at="2026-05-06T05:00:01Z", status="ok")

    client = TestClient(fapp, follow_redirects=False)
    r = client.post("/admin/runs/imap_poll/ack-all")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/runs/imap_poll?notice=acked-3"

    # Follow up GET shows the notice and rows now appear acked.
    r2 = client.get("/admin/runs/imap_poll?notice=acked-3")
    assert r2.status_code == 200
    assert "acked-3" in r2.text

    from driftnote.repository.jobs import recent_failures

    with session_scope(eng) as session:
        unack = recent_failures(
            session, now="2026-05-06T13:00:00Z", days=7, only_unacknowledged=True
        )
    assert unack == []


def test_admin_ack_all_button_renders_only_when_two_or_more_unacked(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    fapp, eng, _ = setup
    # With a single unacked row, the bulk button must NOT appear.
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-05-06T08:00:01Z", status="error")
    r = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r.status_code == 200
    assert "Acknowledge all" not in r.text
    assert 'action="/admin/runs/imap_poll/ack-all"' not in r.text

    # Add a second unacked row -> button appears with the count interpolated.
    with session_scope(eng) as session:
        rid2 = record_job_run(session, job="imap_poll", started_at="2026-05-06T09:00:00Z")
        finish_job_run(session, run_id=rid2, finished_at="2026-05-06T09:00:01Z", status="warn")
    r2 = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r2.status_code == 200
    assert "Acknowledge all (2)" in r2.text
    assert 'action="/admin/runs/imap_poll/ack-all"' in r2.text


def test_admin_ack_all_does_not_affect_runs_started_after_now(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    """A run with started_at > now (clock skew or future-dated insert) is left alone."""
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        past1 = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=past1, finished_at="2026-05-06T08:00:01Z", status="error")
        past2 = record_job_run(session, job="imap_poll", started_at="2026-05-06T09:00:00Z")
        finish_job_run(session, run_id=past2, finished_at="2026-05-06T09:00:01Z", status="error")
        # iso_now is 2026-05-06T12:00:00Z (see fixture). This row started after that.
        future = record_job_run(session, job="imap_poll", started_at="2026-05-06T15:00:00Z")
        finish_job_run(session, run_id=future, finished_at="2026-05-06T15:00:01Z", status="error")
    client = TestClient(fapp, follow_redirects=False)
    r = client.post("/admin/runs/imap_poll/ack-all")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/runs/imap_poll?notice=acked-2"

    from driftnote.repository.jobs import recent_runs_for_job

    with session_scope(eng) as session:
        rows = recent_runs_for_job(session, "imap_poll")
    by_id = {r.id: r for r in rows}
    assert by_id[past1].acknowledged_at is not None
    assert by_id[past2].acknowledged_at is not None
    assert by_id[future].acknowledged_at is None


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
