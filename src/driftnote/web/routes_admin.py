"""Admin dashboard: per-job cards + drill-down + acknowledge."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from driftnote.config import Config
from driftnote.db import session_scope
from driftnote.mail.transport import ImapTransport, SmtpTransport
from driftnote.repository.jobs import (
    acknowledge_all_for_job,
    acknowledge_run,
    last_run,
    last_successful_run,
    recent_failures,
    recent_runs_for_job,
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


def _dot_class_for_status(status: str | None) -> str:
    """Map a job's last status to a CSS class for the rendered dot.

    Never-run jobs render a neutral green; the "(never)" text disambiguates.
    """
    if status == "ok":
        return "dot-ok"
    if status == "warn":
        return "dot-warn"
    if status == "error":
        return "dot-error"
    return "dot-ok"


@dataclass(frozen=True)
class _JobCard:
    job: str
    last_started_at: str | None
    last_status: str | None
    last_detail: str | None
    last_success_at: str | None
    failures_30d: int
    dot_class: str


def install_admin_routes(
    app: FastAPI,
    *,
    engine: Engine,
    iso_now: Callable[[], str],
    environment: str = "prod",
    # The following are only used by the dev-mode test controls. Optional so
    # tests that don't exercise the test controls can pass None.
    smtp: SmtpTransport | None = None,
    imap: ImapTransport | None = None,
    recipient: str | None = None,
    subject_template: str | None = None,
    body_template_text: str | None = None,
    web_base_url: str | None = None,
    config: Config | None = None,
    data_root: Path | None = None,
) -> None:
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
                    dot_class=_dot_class_for_status(last.status if last else None),
                )
            )
        return cards

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_index(request: Request, notice: str | None = None) -> HTMLResponse:
        now = iso_now()
        return templates.TemplateResponse(
            request,
            "admin.html.j2",
            {
                "banners": compute_banners(engine, now=now),
                "cards": _build_cards(now),
                "dev_mode": environment == "dev",
                "notice": notice,
            },
        )

    @app.get("/admin/runs/{job}", response_class=HTMLResponse)
    async def admin_drill(request: Request, job: str, notice: str | None = None) -> HTMLResponse:
        now = iso_now()
        with session_scope(engine) as session:
            rows = recent_runs_for_job(session, job, limit=100)
        unacked_count = sum(
            1 for r in rows if r.status in ("error", "warn") and r.acknowledged_at is None
        )
        return templates.TemplateResponse(
            request,
            "admin.html.j2",
            {
                "banners": compute_banners(engine, now=now),
                "cards": _build_cards(now),
                "recent_runs": rows,
                "job_filter": job,
                "unacked_count": unacked_count,
                "dev_mode": environment == "dev",
                "notice": notice,
            },
        )

    @app.post("/admin/runs/{run_id}/ack")
    async def admin_ack(run_id: int) -> RedirectResponse:
        with session_scope(engine) as session:
            acknowledge_run(session, run_id=run_id, at=iso_now())
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/runs/{job}/ack-all")
    async def admin_ack_all(job: str) -> RedirectResponse:
        with session_scope(engine) as session:
            count = acknowledge_all_for_job(session, job=job, now=iso_now())
        return RedirectResponse(f"/admin/runs/{job}?notice=acked-{count}", status_code=303)

    def _require_dev() -> None:
        if environment != "dev":
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="not found")

    @app.post("/admin/test/send-prompt")
    async def admin_test_send_prompt() -> RedirectResponse:
        _require_dev()
        from datetime import date as _date

        from driftnote.scheduler.prompt_job import run_prompt_job
        from driftnote.scheduler.runner import job_run

        if smtp is None or not recipient or not subject_template or not body_template_text:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail="transport not configured")
        with job_run(engine, "daily_prompt"):
            await run_prompt_job(
                engine=engine,
                smtp=smtp,
                recipient=recipient,
                subject_template=subject_template,
                body_template_text=body_template_text,
                today=_date.today(),
            )
        return RedirectResponse("/admin?notice=prompt-sent", status_code=303)

    @app.post("/admin/test/send-digest/{period}")
    async def admin_test_send_digest(period: str) -> RedirectResponse:
        _require_dev()
        from datetime import date as _date
        from datetime import timedelta

        from driftnote.scheduler.digest_jobs import (
            run_monthly_digest,
            run_weekly_digest,
            run_yearly_digest,
        )
        from driftnote.scheduler.runner import job_run

        if period not in {"weekly", "monthly", "yearly"}:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="invalid period")
        if smtp is None or not recipient or not web_base_url:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail="transport not configured")
        today = _date.today()
        if period == "weekly":
            week_start = today - timedelta(days=today.weekday())
            with job_run(engine, "digest_weekly"):
                await run_weekly_digest(
                    engine=engine,
                    smtp=smtp,
                    recipient=recipient,
                    week_start=week_start,
                    web_base_url=web_base_url,
                )
        elif period == "monthly":
            with job_run(engine, "digest_monthly"):
                await run_monthly_digest(
                    engine=engine,
                    smtp=smtp,
                    recipient=recipient,
                    year=today.year,
                    month=today.month,
                    web_base_url=web_base_url,
                )
        else:  # yearly
            with job_run(engine, "digest_yearly"):
                await run_yearly_digest(
                    engine=engine,
                    smtp=smtp,
                    recipient=recipient,
                    year=today.year,
                    web_base_url=web_base_url,
                )
        return RedirectResponse(f"/admin?notice=digest-{period}-sent", status_code=303)

    @app.post("/admin/test/poll-now")
    async def admin_test_poll_now() -> RedirectResponse:
        _require_dev()
        from driftnote.scheduler.poll_job import run_poll_job
        from driftnote.scheduler.runner import job_run

        if imap is None or config is None or data_root is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail="transport not configured")
        with job_run(engine, "imap_poll"):
            await run_poll_job(config=config, engine=engine, data_root=data_root, imap=imap)
        return RedirectResponse("/admin?notice=poll-complete", status_code=303)
