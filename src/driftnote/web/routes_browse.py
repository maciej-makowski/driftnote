"""Calendar / entry / tags / search browse routes."""

from __future__ import annotations

import calendar as _cal
from collections.abc import Callable
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from driftnote.db import session_scope
from driftnote.digest.inputs import DayInput
from driftnote.digest.moodboard import monthly_moodboard_grid
from driftnote.repository.entries import (
    EntryRecord,
    get_entry,
    list_entries_by_tag,
    list_entries_in_range,
    list_tags_for_date,
    search_fts,
    tag_frequencies_in_range,
)
from driftnote.repository.media import list_media
from driftnote.web.banners import compute_banners

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def install_browse_routes(
    app: FastAPI,
    *,
    engine: Engine,
    iso_now: Callable[[], str],
) -> None:
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    def _ctx(**extras: object) -> dict[str, object]:
        return {"banners": compute_banners(engine, now=iso_now()), **extras}

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        year: int | None = Query(None),
        month: int | None = Query(None),
        tag: str | None = Query(None),
    ) -> HTMLResponse:
        if tag:
            with session_scope(engine) as session:
                entries = list_entries_by_tag(session, tag)
            return templates.TemplateResponse(
                request,
                "search.html.j2",
                _ctx(q=f"#{tag}", results=entries),
            )

        today = _date.today()
        y = year or today.year
        m = month or today.month
        # Query the full 6-week calendar window (which can leak into the
        # prev/next month) so pad cells render their mood emoji too.
        first = _date(y, m, 1)
        grid_start = first - timedelta(days=first.weekday())
        grid_end = grid_start + timedelta(days=41)
        with session_scope(engine) as session:
            entries = list_entries_in_range(session, grid_start.isoformat(), grid_end.isoformat())
        days = [
            DayInput(
                date=_date.fromisoformat(e.date),
                mood=e.mood,
                tags=[],
                photo_thumb=None,
                body_html="",
            )
            for e in entries
        ]
        cells = monthly_moodboard_grid(year=y, month=m, days=days)
        prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
        next_y, next_m = (y, m + 1) if m < 12 else (y + 1, 1)
        return templates.TemplateResponse(
            request,
            "calendar.html.j2",
            _ctx(
                year=y,
                month=m,
                month_name=_cal.month_name[m],
                cells=cells,
                prev_year=prev_y,
                prev_month=prev_m,
                next_year=next_y,
                next_month=next_m,
                today_iso=iso_now()[:10],
            ),
        )

    @app.get("/entry/{date_str}", response_class=HTMLResponse)
    async def entry_detail(request: Request, date_str: str) -> HTMLResponse:
        with session_scope(engine) as session:
            entry = get_entry(session, date_str)
            media = list_media(session, date_str) if entry else []
        if entry is None:
            return HTMLResponse("Not found", status_code=404)
        # Render markdown → HTML (html=False prevents raw-HTML passthrough, mitigating XSS)
        from markdown_it import MarkdownIt

        md = MarkdownIt("commonmark", {"html": False})
        body_html = md.render(entry.body_md)
        with session_scope(engine) as session:
            tags = list_tags_for_date(session, date_str)
        return templates.TemplateResponse(
            request,
            "entry.html.j2",
            _ctx(entry=entry, body_html=body_html, media=media, tags=tags),
        )

    @app.get("/tags", response_class=HTMLResponse)
    async def tags_view(request: Request) -> HTMLResponse:
        with session_scope(engine) as session:
            freq = tag_frequencies_in_range(session, "0001-01-01", "9999-12-31")
        ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
        return templates.TemplateResponse(request, "tags.html.j2", _ctx(tags=ranked))

    @app.get("/search", response_class=HTMLResponse)
    async def search_view(request: Request, q: str | None = Query(None)) -> HTMLResponse:
        results: list[EntryRecord] = []
        error: str | None = None
        if q:
            try:
                with session_scope(engine) as session:
                    results = search_fts(session, q)
            except OperationalError as exc:
                orig = getattr(exc, "orig", None)
                msg = orig.args[0] if orig and orig.args else str(exc)
                error = f"invalid search query: {msg}"
        return templates.TemplateResponse(
            request, "search.html.j2", _ctx(q=q, results=results, error=error)
        )


def install_static(app: FastAPI) -> None:
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
    )
