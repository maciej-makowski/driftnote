"""Cloudflare Access JWT verification middleware.

In production, the `Cf-Access-Jwt-Assertion` header is verified against
Cloudflare's JWKS endpoint at `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`.
For tests we substitute static signing keys + HS256 to avoid network IO.
In dev (`environment='dev'`), the middleware bypasses verification entirely.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_SKIP_PATHS = ("/healthz", "/readyz")


@dataclass
class CloudflareAccessAuth:
    audience: str
    team_domain: str
    environment: str = "prod"
    signing_keys: dict[str, str] | None = None  # for tests
    algorithms: list[str] = field(default_factory=lambda: ["RS256"])
    _jwks_cache: dict[str, Any] = field(default_factory=dict)
    _jwks_cached_at: float = 0.0

    @property
    def issuer(self) -> str:
        return f"https://{self.team_domain}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/cdn-cgi/access/certs"

    def _resolve_key(self, kid: str) -> Any:
        if self.signing_keys is not None:
            return self.signing_keys.get(kid) or next(iter(self.signing_keys.values()), None)
        # JWKS cache (1h TTL)
        if not self._jwks_cache or time.time() - self._jwks_cached_at > 3600:
            try:
                resp = httpx.get(self.jwks_url, timeout=5.0)
                resp.raise_for_status()
                payload = resp.json()
            except httpx.HTTPError, ValueError:
                return None
            cache: dict[str, Any] = {}
            for jwk in payload.get("keys", []):
                key_id = jwk.get("kid", "")
                cache[key_id] = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
            self._jwks_cache = cache
            self._jwks_cached_at = time.time()
        return self._jwks_cache.get(kid)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            unverified = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise PermissionError(f"malformed token: {exc}") from exc
        kid = unverified.get("kid", "")
        key = self._resolve_key(kid)
        if key is None:
            raise PermissionError("signing key not found")
        try:
            return jwt.decode(token, key, algorithms=self.algorithms, audience=self.audience)
        except jwt.InvalidTokenError as exc:
            raise PermissionError(f"invalid token: {exc}") from exc


class _CFAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, auth: CloudflareAccessAuth) -> None:
        super().__init__(app)
        self.auth = auth

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        if self.auth.environment == "dev":
            return await call_next(request)
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)
        token = request.headers.get("Cf-Access-Jwt-Assertion")
        if not token:
            return JSONResponse({"detail": "missing access token"}, status_code=403)
        try:
            self.auth.verify(token)
        except PermissionError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=403)
        return await call_next(request)


def install_cf_access_middleware(app: FastAPI, auth: CloudflareAccessAuth) -> None:
    app.add_middleware(_CFAccessMiddleware, auth=auth)
