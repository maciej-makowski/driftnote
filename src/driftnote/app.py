"""FastAPI app factory. Full wiring lands in Chunk 9; this minimum gives us /healthz.

Module is import-safe — no env vars or config loading at import time. The
Containerfile invokes `uvicorn --factory driftnote.app:create_app` so config
loading happens inside the factory, not at import. Chunk 9 expands the factory
to load Settings, init the DB, and start the scheduler.
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app(*, skip_startup_jobs: bool = False) -> FastAPI:
    """Create and configure the Driftnote FastAPI app.

    `skip_startup_jobs` is True in tests / when the harness only wants the HTTP
    surface. Full lifespan wiring (DB init, scheduler start) lands in Chunk 9.
    """
    app = FastAPI(title="Driftnote", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
