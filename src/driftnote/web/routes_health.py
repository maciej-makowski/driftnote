"""Health and readiness HTTP routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Response


def install_health_routes(
    app: FastAPI,
    *,
    db_ok: Callable[[], bool],
    last_imap_poll_status: Callable[[], tuple[str | None, str | None]],
    readiness: Callable[[], bool] | None = None,
) -> None:
    @app.get("/healthz")
    async def healthz() -> dict[str, str | None]:
        last_at, last_status = last_imap_poll_status()
        return {
            "status": "ok",
            "db": "ok" if db_ok() else "error",
            "last_imap_poll": last_at,
            "last_imap_poll_status": last_status,
        }

    if readiness is None:

        @app.get("/readyz")
        async def readyz_default() -> dict[str, str]:
            return {"status": "ok"}

    else:

        @app.get("/readyz")
        async def readyz_dyn(response: Response) -> dict[str, str]:
            if not readiness():
                response.status_code = 503
                return {"status": "starting"}
            return {"status": "ok"}
