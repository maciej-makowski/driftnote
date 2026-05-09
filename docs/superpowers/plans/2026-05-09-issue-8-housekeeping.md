# Issue #8 — Housekeeping bundle

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five small polish/tech-debt items from the initial review, each landing as its own commit on a single PR. Each is small enough to land independently if any turns out to be larger than expected.

**Architecture:** Touches five unrelated files; each commit is self-contained.

**Tech Stack:** Python (already in repo), no new deps.

**Issue:** https://github.com/maciej-makowski/driftnote/issues/8

---

## Chunk 1: Five small commits in sequence

Each task = one commit. Order is independent — pick whichever order is easiest to context-switch through.

### Task 1: Deepen logging redaction to nested dicts

**Files:**
- Modify: `src/driftnote/logging.py` (function `redact_secrets`)
- Modify: `tests/unit/test_logging.py` (add nested-redaction test)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_logging.py`:

```python
def test_redact_secrets_recurses_into_nested_dicts() -> None:
    out = redact_secrets({
        "user": "u@example.com",
        "cfg": {"gmail_app_password": "p", "host": "smtp.gmail.com"},
        "deeper": {"a": {"token": "t", "ok": "fine"}},
    })
    assert out["user"] == "u@example.com"
    assert out["cfg"]["gmail_app_password"] == REDACTED
    assert out["cfg"]["host"] == "smtp.gmail.com"
    assert out["deeper"]["a"]["token"] == REDACTED
    assert out["deeper"]["a"]["ok"] == "fine"


def test_redact_secrets_recurses_into_lists_of_dicts() -> None:
    out = redact_secrets({
        "items": [
            {"password": "p1", "name": "alice"},
            {"password": "p2", "name": "bob"},
        ],
    })
    assert out["items"][0]["password"] == REDACTED
    assert out["items"][0]["name"] == "alice"
    assert out["items"][1]["password"] == REDACTED
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/unit/test_logging.py -v
```

Expected: the two new tests fail because the current `redact_secrets` is shallow.

- [ ] **Step 3: Implement recursion**

In `src/driftnote/logging.py`, replace `redact_secrets` with:

```python
def redact_secrets(event_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of event_dict with values for known secret keys masked.

    Recursively walks nested mappings and lists so a secret nested inside
    a logged config dict (e.g. log.info("cfg", cfg=config.model_dump()))
    still gets masked.
    """
    return {k: _redact_value(k, v) for k, v in event_dict.items()}


def _redact_value(key: str, value: Any) -> Any:
    if key.lower() in _SECRET_KEYS:
        return REDACTED
    if isinstance(value, Mapping):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value
```

Note: when recursing into a list whose items are dicts, each dict's keys are checked against `_SECRET_KEYS` independently — that's the right behavior. The `key` parameter passed into recursive list calls is the parent's key, used only as a fallback if the list item isn't itself a Mapping.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_logging.py -v` — all tests pass.

- [ ] **Step 5: Update the docstring caveat**

The existing docstring on `redact_secrets` says "redaction is shallow — nested dict values are not inspected." Remove that paragraph.

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/logging.py tests/unit/test_logging.py
git commit -m "feat(logging): recurse into nested dicts/lists when redacting secrets"
```

---

### Task 2: Pin htmx version + document upgrade procedure

**Files:**
- Modify: `src/driftnote/web/static/htmx.min.js` (no content change; we're documenting via a sibling file)
- Create: `src/driftnote/web/static/.htmx-version` (plain text file with the pinned version)

- [ ] **Step 1: Create version-pin file**

```bash
echo "2.0.4" > src/driftnote/web/static/.htmx-version
```

- [ ] **Step 2: Add an upgrade-procedure note**

Append to `Implementation.md` (under any "Operational notes" section, or create one):

```markdown
### Vendored frontend assets

`src/driftnote/web/static/htmx.min.js` is vendored from
[unpkg.com/htmx.org@<version>](https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js).
The pinned version lives in `src/driftnote/web/static/.htmx-version` so
upgrades are explicit. To bump:

```
VERSION=$(cat src/driftnote/web/static/.htmx-version)
echo "current: $VERSION"
NEW=2.0.5  # set this
curl -sSf "https://unpkg.com/htmx.org@${NEW}/dist/htmx.min.js" \
    -o src/driftnote/web/static/htmx.min.js
echo "$NEW" > src/driftnote/web/static/.htmx-version
git diff src/driftnote/web/static/
```

If you want SRI verification, append the SHA-384 digest to `.htmx-version` on
the line below the version. The page template doesn't use it currently, but
having it on disk makes adding `integrity="sha384-…"` a one-line change later.
```

- [ ] **Step 3: Commit**

```bash
git add src/driftnote/web/static/.htmx-version Implementation.md
git commit -m "chore(static): pin htmx version explicitly + document upgrade procedure"
```

---

### Task 3: Suppress \"no recent backup\" banner on first install

**Files:**
- Modify: `src/driftnote/web/banners.py` (function `compute_banners`)
- Modify: `tests/unit/test_web_banners.py` (update existing test + add a new one)

- [ ] **Step 1: Write the failing test**

Replace `test_no_banners_for_clean_state` (currently it asserts `banners == []` when the DB has no rows; that should still pass after the fix) and add a new test that distinguishes "no backup ever ran" from "last successful backup is stale":

```python
def test_no_banners_when_no_backup_history(engine: Engine) -> None:
    """A fresh install with no backup runs at all should NOT show the banner."""
    banners = compute_banners(engine, now="2026-05-09T12:00:00Z")
    assert banners == []


def test_warn_banner_when_last_backup_is_stale(engine: Engine) -> None:
    """A backup ran 40 days ago, no recent run since → amber banner."""
    with session_scope(engine) as session:
        rid = record_job_run(session, job="backup", started_at="2026-03-01T03:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-03-01T03:00:10Z",
            status="ok",
        )
    banners = compute_banners(engine, now="2026-05-09T12:00:00Z")
    assert any("backup" in b.message.lower() and b.level == "warn" for b in banners)
```

- [ ] **Step 2: Run to verify**

Run: `uv run pytest tests/unit/test_web_banners.py -v`

If the existing implementation already handles this correctly (suggested by issue #15's review notes from chunk 9 implementation), both tests will pass and you can skip the implementation step. If `test_no_banners_when_no_backup_history` fails (banner appears), proceed to Step 3.

- [ ] **Step 3: Fix `compute_banners` if needed**

In `src/driftnote/web/banners.py`, the relevant block:

```python
    with session_scope(engine) as session:
        last_backup = last_successful_run(session, "backup")
    if last_backup is None or _days_since(last_backup.started_at, now) > 35:
        out.append(Banner(level="warn", message="Last successful backup is older than 35 days.", link="/admin"))
```

Change to:

```python
    with session_scope(engine) as session:
        last_backup = last_successful_run(session, "backup")
    if last_backup is not None and _days_since(last_backup.started_at, now) > 35:
        out.append(Banner(level="warn", message="Last successful backup is older than 35 days.", link="/admin"))
```

(Drop the `last_backup is None or` clause. Fresh installs without any backup runs no longer trigger the banner.)

- [ ] **Step 4: Run + verify**

Run: `uv run pytest tests/unit/test_web_banners.py -v` — all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/driftnote/web/banners.py tests/unit/test_web_banners.py
git commit -m "fix(web): no backup banner on fresh installs (only after a real run goes stale)"
```

(If Step 2 found the implementation was already correct and only the new tests are needed, the commit message should be `test(banners): cover the no-backup-history case` instead.)

---

### Task 4: Document the live-test workflow

**Files:**
- Modify: `docs/runbook.md` (add a "Live tests" section)

The live tests (`@pytest.mark.live`) target real Gmail and aren't run in CI. Document the manual procedure rather than wiring up GitHub Actions secrets — for a personal app, manual is fine.

- [ ] **Step 1: Append to `docs/runbook.md`**

```markdown
## Live tests against real Gmail

`tests/` contains tests marked `@pytest.mark.live` which talk to a real Gmail account. They're not run in CI (no secrets), but they're useful when changing IMAP/SMTP code or upgrading `aioimaplib`/`aiosmtplib`.

### One-time setup

1. Use a dedicated Gmail account (NOT your real Driftnote account — these tests will create + delete messages).
2. Enable 2-Step Verification on that account.
3. Generate an App Password labeled "Driftnote live tests".
4. Create labels `Driftnote/Inbox` and `Driftnote/Processed` in that account.
5. Create the same Gmail filter as the production setup (subject contains `[Driftnote]`, apply label, skip inbox, **NOT** mark as read).

### Running

```bash
export DRIFTNOTE_LIVE_GMAIL_USER="livetest@gmail.com"
export DRIFTNOTE_LIVE_GMAIL_APP_PASSWORD="xxxxxxxxxxxxxxxx"
uv run pytest -m live -v
```

If no live tests exist in the suite (the marker is registered but no test actually carries it), this command exits with `no tests ran`. That's fine — the marker is reserved for future opt-in tests.

### When to run

- After upgrading `aioimaplib` or `aiosmtplib`
- After changing the OAuth/App Password handling in `mail/transport.py`
- Before any release that touches the email send/receive path
```

- [ ] **Step 2: Commit**

```bash
git add docs/runbook.md
git commit -m "docs(runbook): document the @pytest.mark.live live-test procedure"
```

---

### Task 5: Better error from `cron()` on bad expressions

**Files:**
- Modify: `src/driftnote/scheduler/runner.py` (function `cron`)
- Modify: `tests/unit/test_scheduler_runner.py` (add a test for the error message)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_scheduler_runner.py`:

```python
def test_cron_raises_clear_error_on_wrong_field_count() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="cron expression must have 5 fields"):
        cron("0 21 * * * *", "Europe/London")  # 6 fields: minute hour day month dow EXTRA

    with _pytest.raises(ValueError, match="cron expression must have 5 fields"):
        cron("0 21 *", "Europe/London")  # 3 fields
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_scheduler_runner.py::test_cron_raises_clear_error_on_wrong_field_count -v`

Expected: FAIL — current implementation raises `ValueError: too many values to unpack` (or `not enough values to unpack`) with no context about the offending expression.

- [ ] **Step 3: Implement the clearer error**

In `src/driftnote/scheduler/runner.py`, replace the `cron` function body:

```python
def cron(expr: str, tz: str) -> CronTrigger:
    """Build a CronTrigger from a 5-field cron string in the given tz."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(
            f"cron expression must have 5 fields (minute hour day month dow), "
            f"got {len(fields)} in {expr!r}"
        )
    minute, hour, day, month, day_of_week = fields
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=ZoneInfo(tz),
    )
```

- [ ] **Step 4: Run + verify pass**

Run: `uv run pytest tests/unit/test_scheduler_runner.py -v` — all pass.

- [ ] **Step 5: Commit**

```bash
git add src/driftnote/scheduler/runner.py tests/unit/test_scheduler_runner.py
git commit -m "feat(scheduler): clearer error message when cron expression has wrong field count"
```

---

## Chunk closeout

**Pre-PR gate (after all five commits):**

```bash
uv run pytest -m "not live" -q
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy
```

Both must be clean. Expected test count: ~180 (175 prior + ≥5 new).

**Push + PR:**

```bash
git push -u origin chore/issue-8-housekeeping
gh pr create --title "chore: housekeeping sweep — five small polish items" --body "$(cat <<'EOF'
## Summary
Five independent commits, each targeting a checkbox item from #8.

- **logging redaction recurses into nested dicts/lists** — Logging `cfg=config.model_dump()` no longer leaks `secrets.gmail_app_password`.
- **htmx version pinned + upgrade procedure documented** — `.htmx-version` file + Implementation.md note.
- **\"No recent backup\" banner suppressed on fresh installs** — Banner only fires when an actual backup run goes stale, not when zero runs exist.
- **Live-test workflow documented** — `docs/runbook.md` covers the manual procedure for `@pytest.mark.live` tests.
- **`cron()` raises a clear error on wrong field count** — Replaces the cryptic `ValueError: too many values to unpack`.

## Test plan
- [x] Each commit ends with green tests + lint + types
- [x] Full suite passes; ~5 new tests added
- [x] No new dependencies

Closes #8.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Acceptance criteria:**
- [ ] All five checkboxes from issue #8 satisfied
- [ ] No new dependencies
- [ ] Full suite + lint + types clean
- [ ] Closes #8 via the PR body
