"""Full FastAPI app factory: config, DB, middleware, routes, scheduler."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI

from driftnote.alerts import AlertSender
from driftnote.config import Config, load_config
from driftnote.db import init_db, make_engine, session_scope
from driftnote.logging import configure_logging
from driftnote.mail.smtp import send_email
from driftnote.mail.transport import transports_from_config
from driftnote.scheduler.digest_jobs import (
    run_monthly_digest,
    run_weekly_digest,
    run_yearly_digest,
)
from driftnote.scheduler.disk_job import run_disk_check
from driftnote.scheduler.poll_job import run_poll_job
from driftnote.scheduler.prompt_job import run_prompt_job
from driftnote.scheduler.runner import build_scheduler, cron, job_run
from driftnote.web.auth import CloudflareAccessAuth, install_cf_access_middleware
from driftnote.web.routes_admin import install_admin_routes
from driftnote.web.routes_browse import install_browse_routes, install_static
from driftnote.web.routes_edit import install_edit_routes
from driftnote.web.routes_health import install_health_routes
from driftnote.web.routes_media import install_media_routes


def _iso_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _SmtpAlertSender:
    """Implements AlertSender Protocol via SMTP."""

    def __init__(self, config: Config) -> None:
        _, self._smtp = transports_from_config(config)
        self._recipient = config.email.recipient

    async def send(self, *, kind: str, subject: str, body: str) -> None:
        await send_email(self._smtp, recipient=self._recipient, subject=subject, body_text=body)


def create_app(*, skip_startup_jobs: bool = False) -> FastAPI:
    """Compose the full app. `skip_startup_jobs=True` is for tests."""
    configure_logging(
        level="INFO",
        json_output=os.environ.get("DRIFTNOTE_ENVIRONMENT", "prod") != "dev",
    )

    config_path = Path(os.environ["DRIFTNOTE_CONFIG"])
    config = load_config(config_path)
    data_root = Path(os.environ.get("DRIFTNOTE_DATA_ROOT", "/var/driftnote/data"))
    db_path = data_root / "index.sqlite"

    engine = make_engine(db_path)
    init_db(engine)

    web_base_url = os.environ.get("DRIFTNOTE_WEB_BASE_URL", "https://driftnote.example.com")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        if skip_startup_jobs:
            yield
            return
        scheduler = build_scheduler(timezone=config.schedule.timezone)
        imap_t, smtp_t = transports_from_config(config)
        sender: AlertSender = _SmtpAlertSender(config)
        prompt_body = (Path(__file__).parent / "web" / config.prompt.body_template).read_text()

        async def _prompt_tick() -> None:
            from datetime import date as _date

            with job_run(engine, "daily_prompt"):
                await run_prompt_job(
                    engine=engine,
                    smtp=smtp_t,
                    recipient=config.email.recipient,
                    subject_template=config.prompt.subject_template,
                    body_template_text=prompt_body,
                    today=_date.today(),
                )

        async def _poll_tick() -> None:
            with job_run(engine, "imap_poll"):
                await run_poll_job(config=config, engine=engine, data_root=data_root, imap=imap_t)

        async def _disk_tick() -> None:
            await run_disk_check(
                engine=engine,
                sender=sender,
                data_path=config.disk.data_path,
                warn_percent=config.disk.warn_percent,
                alert_percent=config.disk.alert_percent,
                now=_iso_now(),
            )

        scheduler.add_job(
            _prompt_tick, cron(config.schedule.daily_prompt, config.schedule.timezone)
        )
        scheduler.add_job(_poll_tick, cron(config.schedule.imap_poll, config.schedule.timezone))
        scheduler.add_job(_disk_tick, cron(config.disk.check_cron, config.schedule.timezone))

        if config.digests.weekly_enabled:

            async def _weekly_tick() -> None:
                from datetime import date as _date
                from datetime import timedelta

                with job_run(engine, "digest_weekly"):
                    today = _date.today()
                    week_start = today - timedelta(days=7 + today.weekday())
                    await run_weekly_digest(
                        engine=engine,
                        smtp=smtp_t,
                        recipient=config.email.recipient,
                        week_start=week_start,
                        web_base_url=web_base_url,
                    )

            scheduler.add_job(
                _weekly_tick, cron(config.schedule.weekly_digest, config.schedule.timezone)
            )

        if config.digests.monthly_enabled:

            async def _monthly_tick() -> None:
                from datetime import date as _date

                with job_run(engine, "digest_monthly"):
                    today = _date.today()
                    prev_month_year = today.year if today.month > 1 else today.year - 1
                    prev_month = today.month - 1 if today.month > 1 else 12
                    await run_monthly_digest(
                        engine=engine,
                        smtp=smtp_t,
                        recipient=config.email.recipient,
                        year=prev_month_year,
                        month=prev_month,
                        web_base_url=web_base_url,
                    )

            scheduler.add_job(
                _monthly_tick, cron(config.schedule.monthly_digest, config.schedule.timezone)
            )

        if config.digests.yearly_enabled:

            async def _yearly_tick() -> None:
                from datetime import date as _date

                with job_run(engine, "digest_yearly"):
                    today = _date.today()
                    await run_yearly_digest(
                        engine=engine,
                        smtp=smtp_t,
                        recipient=config.email.recipient,
                        year=today.year - 1,
                        web_base_url=web_base_url,
                    )

            scheduler.add_job(
                _yearly_tick, cron(config.schedule.yearly_digest, config.schedule.timezone)
            )

        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Driftnote", version="0.1.0", lifespan=lifespan)

    auth = CloudflareAccessAuth(
        audience=config.secrets.cf_access_aud,
        team_domain=config.secrets.cf_team_domain,
        environment=config.environment,
    )
    install_cf_access_middleware(app, auth)

    def _db_ok() -> bool:
        try:
            with session_scope(engine):
                return True
        except Exception:
            return False

    def _last_imap_poll_status() -> tuple[str | None, str | None]:
        from driftnote.repository.jobs import last_run

        with session_scope(engine) as session:
            row = last_run(session, "imap_poll")
        return (row.started_at, row.status) if row else (None, None)

    install_health_routes(app, db_ok=_db_ok, last_imap_poll_status=_last_imap_poll_status)
    install_browse_routes(app, engine=engine, iso_now=_iso_now)
    install_edit_routes(app, engine=engine, data_root=data_root, iso_now=_iso_now)
    install_media_routes(app, data_root=data_root)
    install_admin_routes(app, engine=engine, iso_now=_iso_now)
    install_static(app)

    return app
