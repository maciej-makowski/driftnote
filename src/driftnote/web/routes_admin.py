"""Admin dashboard: per-job cards + drill-down + acknowledge."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select

from driftnote.db import session_scope
from driftnote.models import JobRun
from driftnote.repository.jobs import (
    JobRunRecord,
    acknowledge_run,
    last_run,
    last_successful_run,
    recent_failures,
)
from driftnote.web.banners import compute_banners

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_JOBS = [
    "daily_prompt",
    "imap_poll",
    "digest_weekly",
    "digest_monthly",
    "digest_yearly",
    "backup",
    "disk_check",
]


@dataclass(frozen=True)
class _JobCard:
    job: str
    last_started_at: str | None
    last_status: str | None
    last_detail: str | None
    last_success_at: str | None
    failures_30d: int


def install_admin_routes(app: FastAPI, *, engine: Engine, iso_now: Callable[[], str]) -> None:
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    def _build_cards(now: str) -> list[_JobCard]:
        cards: list[_JobCard] = []
        for job in _JOBS:
            with session_scope(engine) as session:
                last = last_run(session, job)
                last_ok = last_successful_run(session, job)
                fails = recent_failures(session, now=now, days=30)
            failures_30d = sum(1 for f in fails if f.job == job)
            cards.append(
                _JobCard(
                    job=job,
                    last_started_at=last.started_at if last else None,
                    last_status=last.status if last else None,
                    last_detail=last.detail if last else None,
                    last_success_at=last_ok.started_at if last_ok else None,
                    failures_30d=failures_30d,
                )
            )
        return cards

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_index(request: Request) -> HTMLResponse:
        now = iso_now()
        return templates.TemplateResponse(
            request,
            "admin.html.j2",
            {"banners": compute_banners(engine, now=now), "cards": _build_cards(now)},
        )

    @app.get("/admin/runs/{job}", response_class=HTMLResponse)
    async def admin_drill(request: Request, job: str) -> HTMLResponse:
        now = iso_now()
        with session_scope(engine) as session:
            stmt = (
                select(JobRun)
                .where(JobRun.job == job)
                .order_by(JobRun.started_at.desc())
                .limit(100)
            )
            rows = [
                JobRunRecord(
                    id=r.id,
                    job=r.job,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    status=r.status,
                    detail=r.detail,
                    error_kind=r.error_kind,
                    error_message=r.error_message,
                    acknowledged_at=r.acknowledged_at,
                )
                for r in session.scalars(stmt)
            ]
        return templates.TemplateResponse(
            request,
            "admin.html.j2",
            {
                "banners": compute_banners(engine, now=now),
                "cards": _build_cards(now),
                "recent_runs": rows,
                "job_filter": job,
            },
        )

    @app.post("/admin/runs/{run_id}/ack")
    async def admin_ack(run_id: int) -> RedirectResponse:
        with session_scope(engine) as session:
            acknowledge_run(session, run_id=run_id, at=iso_now())
        return RedirectResponse("/admin", status_code=303)
