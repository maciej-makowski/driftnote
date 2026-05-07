"""Smoke test: /healthz returns 200."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok() -> None:
    """Smoke test: the minimal create_app() boots and /healthz returns 200.

    Chunk 2's create_app() does no config loading; Chunk 9 will expand it and
    re-add env-var setup to this test (or replace it with a fixture).
    """
    from driftnote.app import create_app

    app = create_app(skip_startup_jobs=True)
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
