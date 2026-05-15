# Drill view: failures-only filter + bulk-ack visibility

> Design spec for [issue #36](https://github.com/maciej-makowski/driftnote/issues/36).

## Goal

Make per-job failures visible and ack-able on `/admin/runs/<job>` even when the job runs orders of magnitude more often than it fails. Two changes:

1. The drill view defaults to "show only failed runs" — a checkbox toggles between failures-only and the existing last-100-of-any-status view.
2. The bulk-ack-all button's visibility is decoupled from the visible row set — it appears whenever any unacked failure exists for the job, computed via a dedicated count query.

## Root cause recap

`recent_runs_for_job(session, "imap_poll", limit=100)` returns the most recent 100 runs by `started_at` regardless of status. For a job that runs every 5 minutes (~288/day), 100 rows covers ~8 hours. The 9 known imap_poll error rows are between 2026-05-10 and 2026-05-15T07:05; the last error pre-dates the visible window by 13+ hours of OK polls. So the rendered table contains 100 OK rows, none of which are failures, hence no per-row ack buttons. The bulk-ack visibility check `unacked_count > 1` derived `unacked_count` from those 100 visible rows → 0 → button hidden.

## Architecture

Two new repository surfaces, one handler change, one template change. No schema migration.

### Repository — `src/driftnote/repository/jobs.py`

**Modify** `recent_runs_for_job` to accept an optional status filter:

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

Backwards-compatible: existing callers (and tests) pass no `statuses` and get unchanged behaviour.

**Add** `count_unacked_failures_for_job`:

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

`func` already imported via `from sqlalchemy import ...`; add `func` to that import line if absent.

### Handler — `src/driftnote/web/routes_admin.py`

Update `admin_drill` to read the `show_only_failed` query param, branch the query, and compute `unacked_count` from the new count helper:

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

The `show_only_failed: str = "1"` default means visiting `/admin/runs/<job>` directly (no query string) lands in failures-only mode. Anything other than the literal string `"0"` is treated as "on", matching the form-submission behaviour described below.

Add `count_unacked_failures_for_job` to the existing `from driftnote.repository.jobs import (...)` block alphabetically (between `acknowledge_run` and `last_run` if you keep the existing order).

### Template — `src/driftnote/web/templates/admin.html.j2`

Above the runs table, insert a small filter form:

```jinja
<form method="get" action="/admin/runs/{{ job_filter }}" class="runs-filter">
  <input type="hidden" name="show_only_failed" value="0">
  <label>
    <input type="checkbox" name="show_only_failed" value="1" {% if show_only_failed %}checked{% endif %}>
    Show only failed runs
  </label>
  <button type="submit">Apply</button>
</form>
```

The **hidden + checkbox** combination is the standard pattern for "checkbox actually toggles off":

- Checkbox **checked** → both inputs submit → `?show_only_failed=0&show_only_failed=1`. FastAPI's `str` query-param parsing takes the last occurrence → `"1"` → ON.
- Checkbox **unchecked** → only hidden submits → `?show_only_failed=0` → handler's check `!= "0"` is `False` → OFF.
- No form (direct URL load) → no param → default `"1"` → ON.

Change the bulk-ack button condition from `> 1` to `>= 1`:

```jinja
{% if unacked_count and unacked_count >= 1 %}
  <form method="post" action="/admin/runs/{{ job_filter }}/ack-all" class="ack-all">
    <button type="submit">Acknowledge all ({{ unacked_count }})</button>
  </form>
{% endif %}
```

Rest of the template unchanged.

### CSS — `src/driftnote/web/static/style.css`

Add a minimal rule so the filter form doesn't visually collide with the `<h2>` heading:

```css
.runs-filter {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 8px 0;
}
```

No new colour tokens; nothing else changes in the stylesheet.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/repository/jobs.py` | `recent_runs_for_job` gains optional `statuses` arg; new `count_unacked_failures_for_job`; `func` added to imports |
| `src/driftnote/web/routes_admin.py` | `admin_drill` reads `show_only_failed`; passes `statuses` + computes `unacked_count` from new helper; threads `show_only_failed` to template |
| `src/driftnote/web/templates/admin.html.j2` | New filter form above runs table; bulk-ack threshold `> 1` → `>= 1` |
| `src/driftnote/web/static/style.css` | New `.runs-filter` flex rule |
| `tests/unit/test_repository_jobs.py` | Cover `recent_runs_for_job(..., statuses=[...])` and `count_unacked_failures_for_job` |
| `tests/integration/test_web_routes_media_and_admin.py` | Cover filter default ON, toggle OFF, bulk-ack visibility independent of limit window |

No production behaviour outside the drill view changes. No DB schema change.

## Tests

### Unit (`tests/unit/test_repository_jobs.py`)

1. `test_recent_runs_for_job_filters_by_statuses` — seed mixed ok/error/warn rows for one job; call with `statuses=["error", "warn"]`; assert only those two statuses returned and OK rows excluded.
2. `test_recent_runs_for_job_statuses_none_returns_all_statuses` — regression check that the default unchanged behaviour still includes OK.
3. `test_count_unacked_failures_for_job_counts_only_unacked_failures` — seed mix of (ok/error/warn) × (acked/unacked); assert count equals unacked error + warn for the target job only.
4. `test_count_unacked_failures_for_job_returns_zero_for_clean_job` — assert returns 0 when no failures exist.

### Integration (`tests/integration/test_web_routes_media_and_admin.py`)

1. `test_admin_drill_defaults_to_failures_only` — seed both OK and error rows; GET `/admin/runs/<job>`; assert OK row's timestamp string NOT in body and error row's IS.
2. `test_admin_drill_show_all_includes_ok_rows` — GET `/admin/runs/<job>?show_only_failed=0` (the unchecked-submit shape — exactly what the form submits when the checkbox is unchecked); assert OK timestamp IS in body.
3. `test_admin_drill_ack_all_visible_when_failures_outside_visible_window` — seed 200 OK rows and 5 unacked error rows where the errors fall outside the most-recent-100; GET drill; assert "Acknowledge all (5)" button is in body.
4. `test_admin_drill_filter_form_renders_checkbox_state` — assert the `checked` attribute is present on the checkbox when default; absent when `show_only_failed=0`.
5. `test_admin_drill_acked_error_in_view_shows_no_per_row_button` — seed one acked error row; with failures-only view (default), assert the row is rendered (acked error is part of the failure history) but no per-row `<button>ack</button>` is present for it. Locks the template's existing `not r.acknowledged_at` guard.

### Existing tests to update

`test_admin_ack_all_button_renders_only_when_two_or_more_unacked` (currently around `tests/integration/test_web_routes_media_and_admin.py:184–204`) asserts the OLD `> 1` threshold (i.e. "with a single unacked row the button must NOT appear"). This test directly contradicts the new `>= 1` threshold and must be rewritten:

- Rename to `test_admin_ack_all_button_renders_when_any_unacked`.
- Assert the bulk-ack button IS rendered when exactly one unacked failure exists for the job.
- Add a separate `test_admin_ack_all_button_hidden_when_no_unacked` covering the all-acked-or-no-failures case (button hidden).

## Acceptance criteria

- [ ] `recent_runs_for_job(..., statuses=["error", "warn"])` returns only error/warn rows; default behaviour unchanged.
- [ ] `count_unacked_failures_for_job(session, job)` returns total count of unacked error/warn rows for that job, ignoring all limits and row windows.
- [ ] `/admin/runs/<job>` (no query string) renders failures-only view by default.
- [ ] Toggling the checkbox to unchecked and submitting renders the last-100-of-any-status view.
- [ ] Bulk-ack button is visible whenever ≥1 unacked failure exists for the job, regardless of which rows are currently visible.
- [ ] Per-row ack buttons render for each unacked error/warn row that is in the visible set; acked rows show timestamp instead of button (template's existing `not r.acknowledged_at` guard).
- [ ] All 4 unit tests + 5 integration tests pass.
- [ ] The old `test_admin_ack_all_button_renders_only_when_two_or_more_unacked` is rewritten as `test_admin_ack_all_button_renders_when_any_unacked` + `test_admin_ack_all_button_hidden_when_no_unacked`.
- [ ] Other existing tests still pass.

## Risks

**Risk:** The hidden + checkbox pattern relies on FastAPI taking the last value of duplicated query params. If FastAPI's behaviour changes or the user's browser submits the values in a non-document order, the toggle could break.
**Mitigation:** Verified behaviour on FastAPI 0.136.1 (the lockfile-resolved version): Starlette's `ImmutableMultiDict` stores `_dict = {k: v for k, v in _items}` so a later duplicate overwrites the earlier value; FastAPI's `str`-annotated query params read from that dict, hitting the last value. The integration test exercises the unchecked-submit URL shape `?show_only_failed=0` directly, which is what the form actually emits when the box is unchecked.

**Risk:** Changing the bulk-ack threshold from `> 1` to `>= 1` makes the button visible when only one unacked failure exists. The user might be confused that "Acknowledge all (1)" is shown alongside a per-row ack button doing the same thing.
**Mitigation:** Acceptable per the user's request ("when there are any unacked errors"). The duplication is mild UX redundancy, not a correctness issue.

**Risk:** `func.count()` requires `func` imported from `sqlalchemy`. If the existing import statement is `from sqlalchemy import select, update`, the implementer must add `func` to it.
**Mitigation:** Spec explicitly notes this; the implementer plan will too.

## Out of scope

- Persistent per-user filter preference (URL-only state is fine).
- Pagination beyond the 100-row limit when filter is OFF.
- Cross-job "all failures everywhere" view.
- Auto-refreshing the drill page after ack (current full-page redirect-back is fine).
