"""Tests for Cloudflare Access JWT middleware."""

from __future__ import annotations

import time
from typing import Any

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from driftnote.web.auth import CloudflareAccessAuth, install_cf_access_middleware


def _hs256_token(secret: str, *, aud: str, exp_offset: int = 60, **extras: Any) -> str:
    payload = {"aud": aud, "iat": int(time.time()), "exp": int(time.time()) + exp_offset, **extras}
    return jwt.encode(payload, secret, algorithm="HS256")


def _build(
    app: FastAPI, *, environment: str, audience: str = "aud", team_domain: str = "t.example.com"
) -> FastAPI:
    auth = CloudflareAccessAuth(
        audience=audience,
        team_domain=team_domain,
        environment=environment,
        # Test override: validate via shared HS256 secret so we don't need JWKS HTTP.
        signing_keys={"k1": "shared-secret"},
        algorithms=["HS256"],
    )
    install_cf_access_middleware(app, auth)
    return app


def test_dev_environment_bypasses_jwt() -> None:
    app = FastAPI()

    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}

    _build(app, environment="dev")
    r = TestClient(app).get("/x")
    assert r.status_code == 200


def test_prod_rejects_missing_jwt() -> None:
    app = FastAPI()

    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}

    _build(app, environment="prod")
    r = TestClient(app).get("/x")
    assert r.status_code == 403
    assert r.json()["detail"] == "missing access token"


def test_prod_accepts_valid_jwt() -> None:
    app = FastAPI()

    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}

    _build(app, environment="prod")
    token = _hs256_token("shared-secret", aud="aud", email="me@example.com")
    r = TestClient(app).get("/x", headers={"Cf-Access-Jwt-Assertion": token})
    assert r.status_code == 200


def test_prod_rejects_wrong_audience() -> None:
    app = FastAPI()

    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}

    _build(app, environment="prod")
    bad = _hs256_token("shared-secret", aud="someone-else")
    r = TestClient(app).get("/x", headers={"Cf-Access-Jwt-Assertion": bad})
    assert r.status_code == 403


def test_prod_rejects_expired_jwt() -> None:
    app = FastAPI()

    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}

    _build(app, environment="prod")
    expired = _hs256_token("shared-secret", aud="aud", exp_offset=-1)
    r = TestClient(app).get("/x", headers={"Cf-Access-Jwt-Assertion": expired})
    assert r.status_code == 403


def test_health_endpoints_skip_auth() -> None:
    app = FastAPI()

    @app.get("/healthz")
    async def _hz() -> dict[str, str]:
        return {"status": "ok"}

    _build(app, environment="prod")
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
