"""Entry edit form, save handler, live-preview endpoint."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as _date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.filesystem.layout import entry_paths_for
from driftnote.filesystem.locks import entry_lock
from driftnote.filesystem.markdown_io import (
    EntryDocument,
    read_entry,
    write_entry,
)
from driftnote.repository.entries import (
    EntryRecord,
    get_entry,
    replace_tags,
    upsert_entry,
)
from driftnote.web.banners import compute_banners

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_md = MarkdownIt("commonmark", {"html": False})


def install_edit_routes(
    app: FastAPI,
    *,
    engine: Engine,
    data_root: Path,
    iso_now: Callable[[], str],
) -> None:
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    @app.get("/entry/{date_str}/edit", response_class=HTMLResponse)
    async def edit_form(request: Request, date_str: str) -> HTMLResponse:
        with session_scope(engine) as session:
            entry = get_entry(session, date_str)
        if entry is None:
            return HTMLResponse("Not found", status_code=404)
        from sqlalchemy import select

        from driftnote.models import Tag

        with session_scope(engine) as session:
            tags = [t.tag for t in session.scalars(select(Tag).where(Tag.date == date_str))]
        ctx = {
            "banners": compute_banners(engine, now=iso_now()),
            "entry": entry,
            "tags_csv": ", ".join(tags),
            "initial_preview": _md.render(entry.body_md),
        }
        return templates.TemplateResponse(request, "entry_edit.html.j2", ctx)

    @app.post("/entry/{date_str}", response_class=HTMLResponse)
    async def save_entry(
        date_str: str,
        mood: str = Form(""),
        tags: str = Form(""),
        body: str = Form(""),
    ) -> RedirectResponse:
        d = _date.fromisoformat(date_str)
        paths = entry_paths_for(data_root, d)
        if not paths.entry_md.exists():
            return HTMLResponse("Not found", status_code=404)  # type: ignore[return-value]
        new_tags = [t.strip().lower() for t in tags.split(",") if t.strip()]
        with entry_lock(data_root, d):
            existing = read_entry(paths.entry_md)
            updated = EntryDocument(
                date=existing.date,
                mood=(mood.strip() or None),
                tags=new_tags,
                photos=existing.photos,
                videos=existing.videos,
                created_at=existing.created_at,
                updated_at=iso_now(),
                sources=existing.sources,
                body=body if body.endswith("\n") else body + "\n",
            )
            write_entry(paths.entry_md, updated)
            with session_scope(engine) as session:
                upsert_entry(
                    session,
                    EntryRecord(
                        date=date_str,
                        mood=updated.mood,
                        body_text=updated.body,
                        body_md=updated.body,
                        created_at=updated.created_at,
                        updated_at=updated.updated_at,
                    ),
                )
                replace_tags(session, date_str, new_tags)
        return RedirectResponse(f"/entry/{date_str}", status_code=303)

    @app.post("/preview", response_class=HTMLResponse)
    async def preview(body: str = Form("")) -> HTMLResponse:
        return HTMLResponse(_md.render(body))
