# Issue #36 — Drill view: failures-only filter + bulk-ack visibility from total-unacked

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface unacked failures on the per-job drill view even when the job runs orders of magnitude more often than it fails, and make the bulk-ack button visible whenever any unacked failure exists for that job.

**Architecture:** Two new repository surfaces (an optional `statuses` filter on the existing `recent_runs_for_job`, plus a dedicated `count_unacked_failures_for_job`). The `admin_drill` handler reads a `show_only_failed` query param (default `"1"`) and threads the filter through to the query; it computes `unacked_count` from the new count helper rather than summing visible rows. The template gains a small hidden+checkbox filter form above the runs table; the bulk-ack threshold changes from `> 1` to `>= 1`.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0, Jinja2, plain CSS, pytest.

**Spec:** [docs/superpowers/specs/2026-05-15-issue-36-drill-failures-filter-design.md](../specs/2026-05-15-issue-36-drill-failures-filter-design.md)

**Issue:** https://github.com/maciej-makowski/driftnote/issues/36

**Branch:** `fix/issue-36-drill-failures-filter` (worktree at `/var/home/cfiet/Documents/Projects/driftnote-issue-36/`)

---

## Working notes for the implementer

- All paths in this plan are relative to the worktree root.
- Fast suite: `uv run pytest -q -m "not live and not slow"`. Pre-commit runs ruff + the fast unit suite on every commit; tests must remain green at every commit point.
- The existing integration test `test_admin_ack_all_button_renders_only_when_two_or_more_unacked` asserts the OLD `> 1` threshold and is REWRITTEN in this PR. Tasks below cover this explicitly.
- TDD discipline is preserved for the two new repo helpers (Chunk 1). Chunk 2 (handler + template + tests) lands as a single commit so the pre-commit hook never sees a state where tests are red.

---

## Chunk 1: Repository helpers (TDD)

### Task 1.1: Extend `recent_runs_for_job` with optional `statuses` filter

**Files:**
- Modify: `src/driftnote/repository/jobs.py`
- Test: `tests/unit/test_repository_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_repository_jobs.py` (after the existing `test_recent_runs_for_job_respects_limit`):

```python
def test_recent_runs_for_job_filters_by_statuses(engine: Engine) -> None:
    """statuses=['error', 'warn'] returns only rows in those statuses; ok is excluded."""
    with session_scope(engine) as session:
        ok = record_job_run(session, job="imap_poll", started_at="2026-05-01T00:00:00Z")
        finish_job_run(session, run_id=ok, finished_at="2026-05-01T00:00:01Z", status="ok")
        err = record_job_run(session, job="imap_poll", started_at="2026-05-02T00:00:00Z")
        finish_job_run(session, run_id=err, finished_at="2026-05-02T00:00:01Z", status="error")
        warn = record_job_run(session, job="imap_poll", started_at="2026-05-03T00:00:00Z")
        finish_job_run(session, run_id=warn, finished_at="2026-05-03T00:00:01Z", status="warn")
    with session_scope(engine) as session:
        rows = recent_runs_for_job(session, "imap_poll", statuses=["error", "warn"])
    assert [r.id for r in rows] == [warn, err]
    assert all(r.status in ("error", "warn") for r in rows)


def test_recent_runs_for_job_statuses_none_returns_all_statuses(engine: Engine) -> None:
    """Default behaviour (statuses=None) returns every status — regression check."""
    with session_scope(engine) as session:
        ok = record_job_run(session, job="imap_poll", started_at="2026-05-01T00:00:00Z")
        finish_job_run(session, run_id=ok, finished_at="2026-05-01T00:00:01Z", status="ok")
        err = record_job_run(session, job="imap_poll", started_at="2026-05-02T00:00:00Z")
        finish_job_run(session, run_id=err, finished_at="2026-05-02T00:00:01Z", status="error")
    with session_scope(engine) as session:
        rows = recent_runs_for_job(session, "imap_poll")
    assert {r.id for r in rows} == {ok, err}
```

- [ ] **Step 2: Run the new tests, confirm `TypeError` on the first**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-36
uv run pytest tests/unit/test_repository_jobs.py::test_recent_runs_for_job_filters_by_statuses -v
```

Expected: FAIL with `TypeError: recent_runs_for_job() got an unexpected keyword argument 'statuses'`.

- [ ] **Step 3: Add the `statuses` parameter**

In `src/driftnote/repository/jobs.py`, locate the existing `recent_runs_for_job` (around line 163):

```python
def recent_runs_for_job(session: Session, job: str, *, limit: int = 100) -> list[JobRunRecord]:
    """Most-recent-first runs for a single job, capped at `limit`."""
    stmt = select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(limit)
    return [_to_record(r) for r in session.scalars(stmt)]
```

Replace it with:

```python
def recent_runs_for_job(
    session: Session,
    job: str,
    *,
    statuses: list[str] | None = None,
    limit: int = 100,
) -> list[JobRunRecord]:
    """Most-recent-first runs for a single job, capped at `limit`.

    If `statuses` is provided, the result is filtered to rows whose
    status is in that list. Pass `["error", "warn"]` for a failures-only
    view; pass `None` (default) for any status.
    """
    stmt = select(JobRun).where(JobRun.job == job)
    if statuses is not None:
        stmt = stmt.where(JobRun.status.in_(statuses))
    stmt = stmt.order_by(JobRun.started_at.desc()).limit(limit)
    return [_to_record(r) for r in session.scalars(stmt)]
```

- [ ] **Step 4: Run all `recent_runs_for_job` tests, confirm they pass**

```bash
uv run pytest tests/unit/test_repository_jobs.py -v -k recent_runs_for_job
```

Expected: 4 passed (the 2 existing tests + 2 new ones).

- [ ] **Step 5: Run the full unit suite to catch any regression**

```bash
uv run pytest tests/unit -q -m "not live and not slow"
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/repository/jobs.py tests/unit/test_repository_jobs.py
git commit -m "feat(repository): recent_runs_for_job accepts optional statuses filter"
```

### Task 1.2: Add `count_unacked_failures_for_job`

**Files:**
- Modify: `src/driftnote/repository/jobs.py`
- Test: `tests/unit/test_repository_jobs.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_repository_jobs.py` (after the tests added in Task 1.1):

```python
def test_count_unacked_failures_for_job_counts_only_unacked_failures(engine: Engine) -> None:
    """Counts error/warn rows where acknowledged_at IS NULL, scoped to the named job."""
    with session_scope(engine) as session:
        # Two unacked failures for imap_poll.
        a = record_job_run(session, job="imap_poll", started_at="2026-05-01T00:00:00Z")
        finish_job_run(session, run_id=a, finished_at="2026-05-01T00:00:01Z", status="error")
        b = record_job_run(session, job="imap_poll", started_at="2026-05-02T00:00:00Z")
        finish_job_run(session, run_id=b, finished_at="2026-05-02T00:00:01Z", status="warn")
        # One acked failure — must be excluded.
        c = record_job_run(session, job="imap_poll", started_at="2026-05-03T00:00:00Z")
        finish_job_run(session, run_id=c, finished_at="2026-05-03T00:00:01Z", status="error")
        acknowledge_run(session, run_id=c, at="2026-05-03T00:01:00Z")
        # An ok run — must be excluded regardless of acked-ness.
        d = record_job_run(session, job="imap_poll", started_at="2026-05-04T00:00:00Z")
        finish_job_run(session, run_id=d, finished_at="2026-05-04T00:00:01Z", status="ok")
        # An unacked failure for a different job — must be excluded by job filter.
        e = record_job_run(session, job="backup", started_at="2026-05-05T00:00:00Z")
        finish_job_run(session, run_id=e, finished_at="2026-05-05T00:00:01Z", status="error")
    with session_scope(engine) as session:
        count = count_unacked_failures_for_job(session, "imap_poll")
    assert count == 2


def test_count_unacked_failures_for_job_returns_zero_for_clean_job(engine: Engine) -> None:
    with session_scope(engine) as session:
        ok = record_job_run(session, job="imap_poll", started_at="2026-05-01T00:00:00Z")
        finish_job_run(session, run_id=ok, finished_at="2026-05-01T00:00:01Z", status="ok")
    with session_scope(engine) as session:
        count = count_unacked_failures_for_job(session, "imap_poll")
    assert count == 0
```

Also update the import block at the top of `tests/unit/test_repository_jobs.py`. Find the existing import for repository helpers (around line 20):

```python
from driftnote.repository.jobs import (
    acknowledge_all_for_job,
    acknowledge_run,
    finish_job_run,
    last_run,
    last_successful_run,
    recent_failures,
    recent_runs_for_job,
    record_job_run,
)
```

Insert `count_unacked_failures_for_job` alphabetically (between `acknowledge_run` and `finish_job_run`):

```python
from driftnote.repository.jobs import (
    acknowledge_all_for_job,
    acknowledge_run,
    count_unacked_failures_for_job,
    finish_job_run,
    last_run,
    last_successful_run,
    recent_failures,
    recent_runs_for_job,
    record_job_run,
)
```

- [ ] **Step 2: Run the new tests, confirm `ImportError` at collection**

```bash
uv run pytest tests/unit/test_repository_jobs.py::test_count_unacked_failures_for_job_counts_only_unacked_failures -v
```

Expected: collection error — `cannot import name 'count_unacked_failures_for_job' from 'driftnote.repository.jobs'`.

- [ ] **Step 3: Add `func` to the SQLAlchemy import line**

In `src/driftnote/repository/jobs.py`, locate the import line (around line 9):

```python
from sqlalchemy import CursorResult, select, update
```

Replace with:

```python
from sqlalchemy import CursorResult, func, select, update
```

- [ ] **Step 4: Add the helper**

In `src/driftnote/repository/jobs.py`, after the existing `recent_runs_for_job` (around line 175 after Task 1.1's modification), append:

```python
def count_unacked_failures_for_job(session: Session, job: str) -> int:
    """Total unacked error/warn rows for `job`, with no row-window cap.

    Used by the admin drill view to decide whether to show the bulk-ack
    button independently of which rows happen to be visible.
    """
    stmt = (
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.job == job)
        .where(JobRun.status.in_(["error", "warn"]))
        .where(JobRun.acknowledged_at.is_(None))
    )
    return session.scalar(stmt) or 0
```

- [ ] **Step 5: Run the new tests, confirm they pass**

```bash
uv run pytest tests/unit/test_repository_jobs.py -v -k count_unacked_failures_for_job
```

Expected: 2 passed.

- [ ] **Step 6: Run the full unit suite**

```bash
uv run pytest tests/unit -q -m "not live and not slow"
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add src/driftnote/repository/jobs.py tests/unit/test_repository_jobs.py
git commit -m "feat(repository): count_unacked_failures_for_job for unlimited-window total"
```

---

## Chunk 2: Handler, template, CSS, and integration tests (single commit)

This chunk lands as ONE commit because the handler and template changes invalidate the existing integration test `test_admin_ack_all_button_renders_only_when_two_or_more_unacked`. Splitting them across multiple commits would leave the pre-commit hook seeing red tests. The single-commit shape keeps every commit green.

### Task 2.1: Update `admin_drill` to read `show_only_failed` and use the count helper

**Files:**
- Modify: `src/driftnote/web/routes_admin.py`

- [ ] **Step 1: Add `count_unacked_failures_for_job` to the imports**

Locate the existing import block (around line 17-24):

```python
from driftnote.repository.jobs import (
    acknowledge_all_for_job,
    acknowledge_run,
    last_run,
    last_successful_run,
    recent_failures,
    recent_runs_for_job,
)
```

Insert `count_unacked_failures_for_job` alphabetically (between `acknowledge_run` and `last_run`):

```python
from driftnote.repository.jobs import (
    acknowledge_all_for_job,
    acknowledge_run,
    count_unacked_failures_for_job,
    last_run,
    last_successful_run,
    recent_failures,
    recent_runs_for_job,
)
```

- [ ] **Step 2: Rewrite the `admin_drill` handler body**

Locate the existing `admin_drill` (around line 122-144):

```python
    @app.get("/admin/runs/{job}", response_class=HTMLResponse)
    async def admin_drill(request: Request, job: str, notice: str | None = None) -> HTMLResponse:
        now = iso_now()
        with session_scope(engine) as session:
            rows = recent_runs_for_job(session, job, limit=100)
        unacked_count = sum(
            1 for r in rows if r.status in ("error", "warn") and r.acknowledged_at is None
        )
        rendered = templates.TemplateResponse(
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
        rendered.headers["Cache-Control"] = "no-store"
        return rendered
```

Replace it with:

```python
    @app.get("/admin/runs/{job}", response_class=HTMLResponse)
    async def admin_drill(
        request: Request,
        job: str,
        notice: str | None = None,
        show_only_failed: str = "1",
    ) -> HTMLResponse:
        now = iso_now()
        only_failed = show_only_failed != "0"
        statuses = ["error", "warn"] if only_failed else None
        with session_scope(engine) as session:
            rows = recent_runs_for_job(session, job, statuses=statuses, limit=100)
            unacked_count = count_unacked_failures_for_job(session, job)
        rendered = templates.TemplateResponse(
            request,
            "admin.html.j2",
            {
                "banners": compute_banners(engine, now=now),
                "cards": _build_cards(now),
                "recent_runs": rows,
                "job_filter": job,
                "unacked_count": unacked_count,
                "show_only_failed": only_failed,
                "dev_mode": environment == "dev",
                "notice": notice,
            },
        )
        rendered.headers["Cache-Control"] = "no-store"
        return rendered
```

Changes:
- Added `show_only_failed: str = "1"` param.
- Computed `only_failed = show_only_failed != "0"`.
- Built `statuses` accordingly and passed to the query.
- Replaced the visible-row sum with `count_unacked_failures_for_job(session, job)`.
- Added `"show_only_failed": only_failed` to the template context.

### Task 2.2: Update `admin.html.j2` with the filter form and the `>= 1` threshold

**Files:**
- Modify: `src/driftnote/web/templates/admin.html.j2`

- [ ] **Step 1: Insert the filter form and change the threshold**

Locate the existing block (around lines 38-44):

```jinja
{% if recent_runs is defined %}
<h2>Runs for {{ job_filter }}</h2>
{% if unacked_count and unacked_count > 1 %}
  <form method="post" action="/admin/runs/{{ job_filter }}/ack-all" class="ack-all">
    <button type="submit">Acknowledge all ({{ unacked_count }})</button>
  </form>
{% endif %}
<table class="runs">
```

Replace it with:

```jinja
{% if recent_runs is defined %}
<h2>Runs for {{ job_filter }}</h2>
<form method="get" action="/admin/runs/{{ job_filter }}" class="runs-filter">
  <input type="hidden" name="show_only_failed" value="0">
  <label>
    <input type="checkbox" name="show_only_failed" value="1" {% if show_only_failed %}checked{% endif %}>
    Show only failed runs
  </label>
  <button type="submit">Apply</button>
</form>
{% if unacked_count and unacked_count >= 1 %}
  <form method="post" action="/admin/runs/{{ job_filter }}/ack-all" class="ack-all">
    <button type="submit">Acknowledge all ({{ unacked_count }})</button>
  </form>
{% endif %}
<table class="runs">
```

Three changes:
1. Added the GET filter form between the `<h2>` and the bulk-ack form. The hidden input pairs with the checkbox so unchecking the box submits `?show_only_failed=0`.
2. Changed the bulk-ack threshold from `> 1` to `>= 1`.
3. The rest of the template (the `<table class="runs">` block) is unchanged.

### Task 2.3: Add the `.runs-filter` CSS rule

**Files:**
- Modify: `src/driftnote/web/static/style.css`

- [ ] **Step 1: Add a CSS rule for the filter form layout**

Open `src/driftnote/web/static/style.css`. Find the section with the existing `.runs` table rules (search for `\.runs\b` — typically near the end of the file after the calendar / entry / admin blocks).

Append the new rule immediately after the last `.runs` rule (or before the mobile media query if there's no obvious anchor):

```css
.runs-filter {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 8px 0;
}
```

No new colour tokens, no new palette variables. The rule sits inside the existing admin CSS area.

- [ ] **Step 2: Stylesheet invariants audit**

```bash
grep -n "border-radius" src/driftnote/web/static/style.css
```

Expected: exactly one match (the `.dot { border-radius: 50%; }` rule from PR #19).

```bash
grep -nE "box-shadow|linear-gradient|radial-gradient" src/driftnote/web/static/style.css
```

Expected: empty (no shadows or gradients introduced).

### Task 2.4: Rewrite the existing integration test (replace `> 1` with `>= 1` semantics)

**Files:**
- Modify: `tests/integration/test_web_routes_media_and_admin.py`

- [ ] **Step 1: Replace `test_admin_ack_all_button_renders_only_when_two_or_more_unacked`**

Locate the existing test (around lines 184-204):

```python
def test_admin_ack_all_button_renders_only_when_two_or_more_unacked(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    fapp, eng, _ = setup
    # With a single unacked row, the bulk button must NOT appear.
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-05-06T08:00:01Z", status="error")
    r = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r.status_code == 200
    assert "Acknowledge all" not in r.text
    assert 'action="/admin/runs/imap_poll/ack-all"' not in r.text

    # Add a second unacked row -> button appears with the count interpolated.
    with session_scope(eng) as session:
        rid2 = record_job_run(session, job="imap_poll", started_at="2026-05-06T09:00:00Z")
        finish_job_run(session, run_id=rid2, finished_at="2026-05-06T09:00:01Z", status="warn")
    r2 = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r2.status_code == 200
    assert "Acknowledge all (2)" in r2.text
    assert 'action="/admin/runs/imap_poll/ack-all"' in r2.text
```

Replace it with TWO tests (renamed) that exercise the new `>= 1` threshold:

```python
def test_admin_ack_all_button_renders_when_any_unacked(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    """With even a single unacked failure, the bulk-ack button is visible."""
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-05-06T08:00:01Z", status="error")
    r = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r.status_code == 200
    assert "Acknowledge all (1)" in r.text
    assert 'action="/admin/runs/imap_poll/ack-all"' in r.text


def test_admin_ack_all_button_hidden_when_no_unacked(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    """Clean job (no failures at all) hides the bulk-ack button."""
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-05-06T08:00:01Z", status="ok")
    r = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r.status_code == 200
    assert "Acknowledge all" not in r.text
    assert 'action="/admin/runs/imap_poll/ack-all"' not in r.text
```

### Task 2.5: Add 5 new integration tests

**Files:**
- Modify: `tests/integration/test_web_routes_media_and_admin.py`

- [ ] **Step 1: Append the five new tests at the end of the file**

```python
def test_admin_drill_defaults_to_failures_only(setup: tuple[FastAPI, Engine, Path]) -> None:
    """Without query string, drill renders error/warn rows only; OK rows are hidden."""
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        ok = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=ok, finished_at="2026-05-06T08:00:01Z", status="ok")
        err = record_job_run(session, job="imap_poll", started_at="2026-05-06T09:00:00Z")
        finish_job_run(session, run_id=err, finished_at="2026-05-06T09:00:01Z", status="error")
    r = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r.status_code == 200
    # The error row's started_at is rendered.
    assert "2026-05-06T09:00:00Z" in r.text
    # The OK row's started_at is NOT rendered (filtered out).
    assert "2026-05-06T08:00:00Z" not in r.text


def test_admin_drill_show_all_includes_ok_rows(setup: tuple[FastAPI, Engine, Path]) -> None:
    """?show_only_failed=0 (the unchecked-submit shape) shows OK rows too."""
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        ok = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=ok, finished_at="2026-05-06T08:00:01Z", status="ok")
        err = record_job_run(session, job="imap_poll", started_at="2026-05-06T09:00:00Z")
        finish_job_run(session, run_id=err, finished_at="2026-05-06T09:00:01Z", status="error")
    r = TestClient(fapp).get("/admin/runs/imap_poll?show_only_failed=0")
    assert r.status_code == 200
    assert "2026-05-06T08:00:00Z" in r.text  # OK row visible
    assert "2026-05-06T09:00:00Z" in r.text  # error row visible


def test_admin_drill_ack_all_visible_when_failures_outside_visible_window(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    """200 OK rows then 5 unacked errors: errors fall outside the limit-100 window
    if the view weren't filtering; with the filter (default), errors are visible
    AND the bulk-ack button is present with the total count."""
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        # 200 OK rows BEFORE the failures (so failures appear newer in started_at order).
        for i in range(200):
            rid = record_job_run(
                session, job="imap_poll", started_at=f"2026-05-01T{i // 60:02d}:{i % 60:02d}:00Z"
            )
            finish_job_run(
                session,
                run_id=rid,
                finished_at=f"2026-05-01T{i // 60:02d}:{i % 60:02d}:01Z",
                status="ok",
            )
        # 5 unacked errors AFTER the OK runs.
        for i in range(5):
            rid = record_job_run(
                session, job="imap_poll", started_at=f"2026-05-02T0{i}:00:00Z"
            )
            finish_job_run(
                session,
                run_id=rid,
                finished_at=f"2026-05-02T0{i}:00:01Z",
                status="error",
            )
    # Default drill (filter ON) shows the 5 failures and the bulk-ack button with count=5.
    r = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r.status_code == 200
    assert "Acknowledge all (5)" in r.text
    assert 'action="/admin/runs/imap_poll/ack-all"' in r.text


def test_admin_drill_filter_form_renders_checkbox_state(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    """The filter checkbox is `checked` by default and unchecked when ?show_only_failed=0."""
    fapp, _, _ = setup
    # Default: checkbox is checked.
    r = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r.status_code == 200
    assert 'name="show_only_failed" value="1" checked' in r.text
    # Explicitly off: checkbox is NOT checked.
    r2 = TestClient(fapp).get("/admin/runs/imap_poll?show_only_failed=0")
    assert r2.status_code == 200
    assert 'name="show_only_failed" value="1" checked' not in r2.text
    assert 'name="show_only_failed" value="1"' in r2.text  # still rendered, just unchecked


def test_admin_drill_acked_error_in_view_shows_no_per_row_button(
    setup: tuple[FastAPI, Engine, Path],
) -> None:
    """An acknowledged error is visible in the failures-only view but has no per-row ack button.

    Locks the template's existing `not r.acknowledged_at` guard against regression.
    """
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-05-06T08:00:01Z", status="error")
        acknowledge_run(session, run_id=rid, at="2026-05-06T08:01:00Z")
    r = TestClient(fapp).get("/admin/runs/imap_poll")
    assert r.status_code == 200
    # The error row's started_at IS in the body (acked errors stay visible in the failure view).
    assert "2026-05-06T08:00:00Z" in r.text
    # But its per-row ack button is NOT rendered (template guard: not r.acknowledged_at).
    assert f'action="/admin/runs/{rid}/ack"' not in r.text
    # Bulk-ack button is also hidden (no unacked failures).
    assert "Acknowledge all" not in r.text
```

- [ ] **Step 2: Add `acknowledge_run` to the test file's imports if needed**

The new acked-error test uses `acknowledge_run`. Check the existing import block at the top of `tests/integration/test_web_routes_media_and_admin.py` — it imports from `driftnote.repository.jobs`. If `acknowledge_run` isn't already there, add it alphabetically (between `acknowledge_all_for_job` and other helpers).

```python
from driftnote.repository.jobs import (
    acknowledge_all_for_job,
    acknowledge_run,
    finish_job_run,
    last_run,
    recent_failures,
    record_job_run,
)
```

(The exact existing import list may differ — match its style and just ensure `acknowledge_run` is present.)

### Task 2.6: Run the suites and commit the single big change

- [ ] **Step 1: Run the full integration suite**

```bash
uv run pytest tests/integration -q -m "not live and not slow"
```

Expected: green. All 5 new integration tests pass, the 2 rewritten tests pass, and existing tests remain green.

- [ ] **Step 2: Run the full fast suite**

```bash
uv run pytest -q -m "not live and not slow"
```

Expected: green.

- [ ] **Step 3: Stylesheet invariants audit**

```bash
grep -n "border-radius" src/driftnote/web/static/style.css
grep -nE "box-shadow|linear-gradient|radial-gradient" src/driftnote/web/static/style.css
```

Expected: one match for `border-radius` (the `.dot` rule); empty for the second grep.

- [ ] **Step 4: Commit Tasks 2.1–2.5 together**

```bash
git add src/driftnote/web/routes_admin.py \
        src/driftnote/web/templates/admin.html.j2 \
        src/driftnote/web/static/style.css \
        tests/integration/test_web_routes_media_and_admin.py
git commit -m "fix(admin): drill view filters by failure status; bulk-ack visible on any unacked"
```

---

## Chunk 3: Final verification + PR

### Task 3.1: Confirm the full diff

- [ ] **Step 1: Inspect commit list**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-36
git log --oneline master..HEAD
git diff --stat master..HEAD
```

Expected: 5 commits on the branch (2 spec + 1 plan + 3 feature). Diff stat touches:
- `src/driftnote/repository/jobs.py`
- `src/driftnote/web/routes_admin.py`
- `src/driftnote/web/templates/admin.html.j2`
- `src/driftnote/web/static/style.css`
- `tests/unit/test_repository_jobs.py`
- `tests/integration/test_web_routes_media_and_admin.py`
- `docs/superpowers/specs/2026-05-15-issue-36-drill-failures-filter-design.md`
- `docs/superpowers/plans/2026-05-15-issue-36-drill-failures-filter.md`

- [ ] **Step 2: Final fast-suite sanity check**

```bash
uv run pytest -q -m "not live and not slow"
```

Expected: green.

### Task 3.2: Push + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin fix/issue-36-drill-failures-filter
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "fix(admin): drill view filters by failure status; bulk-ack on any unacked (#36)" --body "$(cat <<'EOF'
## Summary

Closes #36.

- `/admin/runs/<job>` defaults to a failures-only view via a `show_only_failed=1` query param. A hidden+checkbox form toggles to the full last-100-runs view (`?show_only_failed=0`).
- Bulk-ack button visibility derived from `count_unacked_failures_for_job(session, job)` — counts ALL unacked failures for the job, not just visible rows. Threshold dropped from `> 1` to `>= 1`.
- New repository helper `count_unacked_failures_for_job(session, job) -> int`.
- `recent_runs_for_job` gains an optional `statuses` filter (backwards-compatible).

## Root cause

`recent_runs_for_job` returns the last 100 runs by start time regardless of status. For `imap_poll` (every 5 minutes), 100 rows covers ~8 hours — so failures older than the last ~8 hours of OK polls fall off the visible window. The old `unacked_count = sum(...)` over visible rows produced 0, hiding the bulk-ack button even when the banner reported 6 unacked failures.

## Verification

- 4 new unit tests: statuses filter on/off; unacked-count on mixed status + acked + cross-job + clean states.
- 5 new integration tests: default filter ON; toggle OFF shows OK rows; bulk-ack visible when failures are outside the limit window; checkbox-state rendering; acked-error in view has no per-row button.
- Existing `test_admin_ack_all_button_renders_only_when_two_or_more_unacked` (asserted the old `> 1` threshold) replaced by `test_admin_ack_all_button_renders_when_any_unacked` + `test_admin_ack_all_button_hidden_when_no_unacked`.

## Out of scope

- Persistent per-user filter preference.
- Pagination beyond the 100-row limit.
- Cross-job "all failures everywhere" view.

## Spec + plan

- Spec: `docs/superpowers/specs/2026-05-15-issue-36-drill-failures-filter-design.md`
- Plan: `docs/superpowers/plans/2026-05-15-issue-36-drill-failures-filter.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** every spec acceptance criterion maps to a task here:
  - `recent_runs_for_job` statuses filter → Task 1.1
  - `count_unacked_failures_for_job` → Task 1.2
  - Default failures-only view → Task 2.1 + Task 2.4 integration test
  - Checkbox toggle to show-all → Task 2.2 + Task 2.5 integration test
  - Bulk-ack `>= 1` threshold → Task 2.2 template change + Task 2.4 rewritten test
  - Per-row ack guard preserved → Task 2.5 acked-error integration test
  - Old `> 1` test rewritten → Task 2.4
- **No placeholders:** every step has concrete code or shell commands.
- **Type consistency:** `show_only_failed` (str query param), `only_failed` (bool local), `statuses` (list[str] | None), `unacked_count` (int) — consistent across handler / template / tests.
- **`func` import:** Task 1.2 Step 3 covers adding `func` to the `sqlalchemy` import line before defining the count helper.
