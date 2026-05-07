"""Serve original / web / thumb media from the entries tree."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def install_media_routes(app: FastAPI, *, data_root: Path) -> None:
    @app.get("/media/{date_str}/{kind}/{filename}")
    async def media(date_str: str, kind: str, filename: str) -> FileResponse:
        if kind not in {"original", "web", "thumb"}:
            raise HTTPException(status_code=400, detail="invalid kind")
        # Defense against path traversal: filename and date_str are exact path components.
        if "/" in filename or ".." in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="invalid filename")
        try:
            y, m, d = date_str.split("-")
            int(y), int(m), int(d)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid date") from exc
        sub = "originals" if kind == "original" else ("web" if kind == "web" else "thumbs")
        path = data_root / "entries" / y / m / d / sub / filename
        try:
            resolved = path.resolve(strict=True)
            data_root_resolved = data_root.resolve()
            if not str(resolved).startswith(str(data_root_resolved) + "/"):
                raise HTTPException(status_code=400, detail="bad path")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        return FileResponse(resolved)
