"""Smoke test that /healthz + /readyz are wired and return JSON."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from driftnote.web.routes_health import install_health_routes


def test_healthz_returns_ok() -> None:
    app = FastAPI()
    install_health_routes(
        app, db_ok=lambda: True, last_imap_poll_status=lambda: ("2026-05-06T20:55:00Z", "ok")
    )
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["last_imap_poll_status"] == "ok"


def test_healthz_reports_db_failure() -> None:
    app = FastAPI()
    install_health_routes(app, db_ok=lambda: False, last_imap_poll_status=lambda: (None, None))
    r = TestClient(app).get("/healthz")
    body = r.json()
    assert body["db"] == "error"


def test_readyz_only_returns_when_ready() -> None:
    app = FastAPI()
    state = {"ready": False}
    install_health_routes(
        app,
        db_ok=lambda: True,
        last_imap_poll_status=lambda: (None, None),
        readiness=lambda: state["ready"],
    )
    r = TestClient(app).get("/readyz")
    assert r.status_code == 503
    state["ready"] = True
    r = TestClient(app).get("/readyz")
    assert r.status_code == 200
