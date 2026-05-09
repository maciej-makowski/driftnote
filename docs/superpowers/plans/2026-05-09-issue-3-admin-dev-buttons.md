# Issue #3 — Dev-mode admin buttons for one-click sends + manual poll

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Test controls" section to `/admin` (only rendered when `DRIFTNOTE_ENVIRONMENT == "dev"`) with one-click buttons that synchronously dispatch the daily prompt, weekly/monthly/yearly digests, and the IMAP poll.

**Architecture:** Wire-and-render only — the underlying jobs already exist. Add a new query parameter to the `install_admin_routes` factory so it can read the `environment` flag, render the test-controls section conditionally in `admin.html.j2`, add five POST endpoints that call the existing job functions inside a `job_run` context, and redirect back to `/admin?notice=…` to show a transient banner.

**Tech Stack:** FastAPI, Jinja2, existing scheduler jobs.

**Issue:** https://github.com/maciej-makowski/issues/3

---

## Chunk 1: Wire environment flag through, add endpoints, conditional render

### Task 1: Pass `environment` + transports + data root through `install_admin_routes`

**Files:**
- Modify: `src/driftnote/web/routes_admin.py` (add new args to `install_admin_routes` and use them)
- Modify: `src/driftnote/app.py` (pass the new args at the install_admin_routes call site)

The admin routes currently know nothing about IMAP/SMTP — they only render `job_runs` rows. We need to pass enough state in so the new POST handlers can call the underlying jobs.

- [ ] **Step 1: Extend `install_admin_routes` signature**

In `src/driftnote/web/routes_admin.py`, locate `install_admin_routes` (around line 46) and replace its signature with:

```python
def install_admin_routes(
    app: FastAPI,
    *,
    engine: Engine,
    iso_now: Callable[[], str],
    environment: str,
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
```

(Imports at the top of the file: add `from pathlib import Path`, `from driftnote.config import Config`, `from driftnote.mail.transport import ImapTransport, SmtpTransport`.)

The closure captures these for the route handlers below.

- [ ] **Step 2: Pass `dev_mode` to the templates**

In `routes_admin.py`, update the two existing template-render calls (`admin_index` and `admin_drill`) to include `"dev_mode": environment == "dev"` in the context dict. Templates will read this to decide whether to render the test-controls section.

- [ ] **Step 3: Update the `app.py` call site**

In `src/driftnote/app.py`, find the call to `install_admin_routes` and pass the new args. The transports + recipient + templates are already prepared in the lifespan; thread them down. Approximate diff (paste-ready):

```python
    install_admin_routes(
        app,
        engine=engine,
        iso_now=_iso_now,
        environment=config.environment,
        smtp=smtp_t if not skip_startup_jobs else None,
        imap=imap_t if not skip_startup_jobs else None,
        recipient=config.email.recipient,
        subject_template=config.prompt.subject_template,
        body_template_text=prompt_body if not skip_startup_jobs else None,
        web_base_url=web_base_url,
        config=config,
        data_root=data_root,
    )
```

Note: `smtp_t`, `imap_t`, and `prompt_body` are only built inside the lifespan today (they're not module-scope). You'll need to lift their construction out of the lifespan into the `create_app` body so they're available before the lifespan runs (which is when `install_admin_routes` is called). Construct them once at top of `create_app`, after `engine = make_engine(...)`. The lifespan still uses them.

If lifting transport construction is too invasive, an acceptable alternative: build them lazily inside each test-control handler (one-time-per-request hit, but only for dev-mode users). Pick this if the lift breaks too many existing tests — the perf is irrelevant for an admin-triggered button.

---

### Task 2: Add the five POST endpoints

**Files:**
- Modify: `src/driftnote/web/routes_admin.py`

- [ ] **Step 1: Define the test-control endpoints**

Inside `install_admin_routes`, after the existing routes, add:

```python
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
        assert smtp is not None and recipient and subject_template and body_template_text
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
        from driftnote.scheduler.runner import job_run
        from driftnote.scheduler.digest_jobs import (
            run_weekly_digest,
            run_monthly_digest,
            run_yearly_digest,
        )
        if period not in {"weekly", "monthly", "yearly"}:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="invalid period")
        assert smtp is not None and recipient and web_base_url
        today = _date.today()
        if period == "weekly":
            week_start = today - timedelta(days=today.weekday())
            with job_run(engine, "digest_weekly"):
                await run_weekly_digest(
                    engine=engine, smtp=smtp, recipient=recipient,
                    week_start=week_start, web_base_url=web_base_url,
                )
        elif period == "monthly":
            with job_run(engine, "digest_monthly"):
                await run_monthly_digest(
                    engine=engine, smtp=smtp, recipient=recipient,
                    year=today.year, month=today.month, web_base_url=web_base_url,
                )
        else:  # yearly
            with job_run(engine, "digest_yearly"):
                await run_yearly_digest(
                    engine=engine, smtp=smtp, recipient=recipient,
                    year=today.year, web_base_url=web_base_url,
                )
        return RedirectResponse(f"/admin?notice=digest-{period}-sent", status_code=303)

    @app.post("/admin/test/poll-now")
    async def admin_test_poll_now() -> RedirectResponse:
        _require_dev()
        from driftnote.scheduler.poll_job import run_poll_job
        from driftnote.scheduler.runner import job_run
        assert imap is not None and config is not None and data_root is not None
        with job_run(engine, "imap_poll"):
            await run_poll_job(config=config, engine=engine, data_root=data_root, imap=imap)
        return RedirectResponse("/admin?notice=poll-complete", status_code=303)
```

(Imports of `RedirectResponse` already exist at the top of the file — verify; if not, add `from fastapi.responses import RedirectResponse`.)

- [ ] **Step 2: Read the `notice` query param in `admin_index` and pass it to the template**

Modify the `admin_index` route to accept and forward `notice`:

```python
    @app.get("/admin", response_class=HTMLResponse)
    async def admin_index(request: Request, notice: str | None = None) -> HTMLResponse:
        now = iso_now()
        return templates.TemplateResponse(
            "admin.html.j2",
            {
                "request": request,
                "banners": compute_banners(engine, now=now),
                "cards": _build_cards(now),
                "dev_mode": environment == "dev",
                "notice": notice,
            },
        )
```

---

### Task 3: Render the test-controls section in `admin.html.j2`

**Files:**
- Modify: `src/driftnote/web/templates/admin.html.j2`

- [ ] **Step 1: Add the conditional section**

At the top of the `{% block content %}` (before the existing `<h1>Admin</h1>`), add:

```jinja
{% if notice %}
  <p class="notice" style="padding:8px;border:1px solid #6c6;border-radius:4px;background:#eaffea">
    {{ notice }}
  </p>
{% endif %}
```

After the existing `<section class="job-cards">…</section>` block, add:

```jinja
{% if dev_mode %}
  <section class="test-controls" style="margin-top:24px;padding:12px;border:2px dashed #c66;border-radius:6px;background:#fff8f8">
    <h2 style="margin-top:0">Test controls (dev only)</h2>
    <p style="color:#888;margin:4px 0 12px">
      Synchronously dispatches the listed scheduled job. The result lands in
      the corresponding card above (refresh after a couple of seconds).
    </p>
    <form method="post" action="/admin/test/send-prompt" style="display:inline-block;margin:4px"><button>Send today's prompt</button></form>
    <form method="post" action="/admin/test/send-digest/weekly" style="display:inline-block;margin:4px"><button>Send weekly digest</button></form>
    <form method="post" action="/admin/test/send-digest/monthly" style="display:inline-block;margin:4px"><button>Send monthly digest</button></form>
    <form method="post" action="/admin/test/send-digest/yearly" style="display:inline-block;margin:4px"><button>Send yearly digest</button></form>
    <form method="post" action="/admin/test/poll-now" style="display:inline-block;margin:4px"><button>Poll responses now</button></form>
  </section>
{% endif %}
```

(Issue #4 will eventually replace these inline styles with CSS classes during the dark-mode redesign — for now keep them inline so the visual cue is unmissable.)

---

### Task 4: Tests

**Files:**
- Modify: `tests/integration/test_web_routes_media_and_admin.py`

- [ ] **Step 1: Update existing fixtures to pass the new args**

The current `setup` fixture calls `install_admin_routes(app, engine=eng, iso_now=...)`. Update to:

```python
    install_admin_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z", environment="prod")
```

This keeps existing tests on the prod path (where the test-controls section MUST NOT render).

Run: `uv run pytest tests/integration/test_web_routes_media_and_admin.py -v` → existing tests still pass.

- [ ] **Step 2: Add visibility tests**

Append:

```python
def test_admin_test_controls_hidden_in_prod(setup) -> None:
    fapp, _, _ = setup
    r = TestClient(fapp).get("/admin")
    assert r.status_code == 200
    assert "Test controls" not in r.text


def test_admin_test_controls_visible_in_dev(tmp_path: Path) -> None:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    app = FastAPI()
    install_admin_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z", environment="dev")
    r = TestClient(app).get("/admin")
    assert r.status_code == 200
    assert "Test controls" in r.text
    # Each of the five buttons is present.
    assert 'action="/admin/test/send-prompt"' in r.text
    assert 'action="/admin/test/send-digest/weekly"' in r.text
    assert 'action="/admin/test/send-digest/monthly"' in r.text
    assert 'action="/admin/test/send-digest/yearly"' in r.text
    assert 'action="/admin/test/poll-now"' in r.text


def test_admin_test_endpoints_404_in_prod(setup) -> None:
    fapp, _, _ = setup
    client = TestClient(fapp)
    for path in (
        "/admin/test/send-prompt",
        "/admin/test/send-digest/weekly",
        "/admin/test/send-digest/monthly",
        "/admin/test/send-digest/yearly",
        "/admin/test/poll-now",
    ):
        r = client.post(path)
        assert r.status_code == 404, f"{path} should 404 in prod, got {r.status_code}"


def test_admin_notice_banner_renders_when_query_param_set(tmp_path: Path) -> None:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    app = FastAPI()
    install_admin_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z", environment="dev")
    r = TestClient(app).get("/admin?notice=prompt-sent")
    assert r.status_code == 200
    assert "prompt-sent" in r.text
```

(Note: testing the actual POST handlers end-to-end requires SMTP/IMAP transports which mean wiring up GreenMail. Defer that to a separate test if needed; the 404-in-prod check + visibility checks are the primary regression guards.)

- [ ] **Step 2: Run + verify**

Run: `uv run pytest tests/integration/test_web_routes_media_and_admin.py -v`
Expected: existing 5 tests + 4 new tests = 9 passed.

- [ ] **Step 3: Run the full app integration test (it constructs the real `create_app`)**

Run: `uv run pytest tests/integration/test_app_full.py -v`
Expected: 1 passed (the full create_app boots, regardless of dev/prod mode).

- [ ] **Step 4: Run the full suite + lint + types**

Run: `uv run pytest -m "not live" -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy`
Expected: ≥ 179 passed (175 prior + 4 new); lint/types clean.

- [ ] **Step 5: Commit**

```bash
git add src/driftnote/web/routes_admin.py \
        src/driftnote/web/templates/admin.html.j2 \
        src/driftnote/app.py \
        tests/integration/test_web_routes_media_and_admin.py
git commit -m "$(cat <<'EOF'
feat(admin): dev-only test controls for one-click prompt + digest + poll

Adds a "Test controls" section to /admin, rendered only when
DRIFTNOTE_ENVIRONMENT=dev. Five POST endpoints synchronously dispatch
the corresponding scheduler job inside a job_run context (so the
admin's history table picks the invocation up):

  - POST /admin/test/send-prompt          → daily prompt
  - POST /admin/test/send-digest/weekly   → weekly digest
  - POST /admin/test/send-digest/monthly  → monthly digest
  - POST /admin/test/send-digest/yearly   → yearly digest
  - POST /admin/test/poll-now             → IMAP poll

In prod (any environment != "dev") the buttons don't render and each
POST endpoint returns 404 — verified by an explicit test.

Threads SMTP/IMAP transports + recipient/template config through
install_admin_routes so the handlers can call the underlying jobs.
Constructs transports at create_app top-level so they're available
to install_admin_routes (the lifespan still uses the same instances).

Closes #3
EOF
)"
```

### Closeout

**Acceptance criteria:**
- [ ] Test-controls section visible only when `environment=="dev"`
- [ ] All five POST endpoints work in dev, return 404 in prod
- [ ] Each invocation creates a `job_runs` row visible on the admin page
- [ ] Notice banner renders when redirected back with `?notice=…`
- [ ] All existing tests still pass; 4 new tests added
- [ ] Closes #3 via the commit message
