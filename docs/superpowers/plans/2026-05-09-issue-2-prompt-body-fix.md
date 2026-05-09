# Issue #2 — Fix truncated prompt body in `driftnote send-prompt`

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the CLI's `send-prompt` command from sending a one-line `"How was {date}?"` placeholder instead of the full prompt body.

**Architecture:** The bug is a path-resolution typo in `cli.py:_run_send_prompt`. It strips the `emails/` subdirectory from `config.prompt.body_template` (`templates/emails/prompt.txt.j2`) by taking only the basename, then prepends `src/driftnote/web/templates/` (without `emails/`). The file isn't found at that path, the silent `if … else "How was {date}?"` fallback fires, and the recipient gets a stub. Fix: mirror the lifespan's path resolution in `app.py` (which is correct), drop the silent fallback, and raise loudly if the template is missing.

**Tech Stack:** Python 3.14, Typer CLI, plain str.format() templating (no Jinja2 needed — current template only uses `{date}` placeholders).

**Issue:** https://github.com/maciej-makowski/driftnote/issues/2

---

## Chunk 1: Fix CLI template path + add regression test

### Task 1: Reproduce the bug, fix the path, raise on missing template

**Files:**
- Modify: `src/driftnote/cli.py` (function `_run_send_prompt`, lines ~232-245)
- Test: `tests/integration/test_cli.py` (new test using GreenMail fixture)

**Investigation summary** (paste this into the PR description):
- `app.py:73-75` correctly resolves the template via `Path(__file__).parent / "web" / config.prompt.body_template` → `src/driftnote/web/templates/emails/prompt.txt.j2`. Scheduler-driven prompts work.
- `cli.py:236-241` does `Path("src/driftnote/web/templates") / config.prompt.body_template.split("/")[-1]`. This drops the `emails/` subdir AND uses a relative path. The file doesn't exist at the wrong location, the `body_template_path.exists()` check returns False, and the fallback `"How was {date}?"` is silently sent.
- The silent fallback hid the bug. Removing it would have made the failure obvious from day one.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_cli.py`:

```python
def test_send_prompt_renders_full_template_body(
    mail_server: MailServer,
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full multi-line prompt template is sent, not the placeholder fallback."""
    cfg_path = tmp_path / "config.toml"
    _write_min_config(cfg_path)
    data_root = tmp_path / "data"
    db_path = data_root / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = make_engine(db_path)
    init_db(eng)

    # Wipe GreenMail INBOX so we read only the message this test sends.
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    with contextlib.suppress(Exception):
        mb.select("INBOX")
        mb.store("1:*", "+FLAGS", r"\Deleted")
        mb.expunge()
    mb.logout()

    monkeypatch.setenv("DRIFTNOTE_CONFIG", str(cfg_path))
    monkeypatch.setenv("DRIFTNOTE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("DRIFTNOTE_DB_PATH", str(db_path))
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", mail_server.user)
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", mail_server.password)
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    monkeypatch.setenv("DRIFTNOTE_ENVIRONMENT", "dev")
    monkeypatch.setenv("DRIFTNOTE_SMTP_HOST", mail_server.host)
    monkeypatch.setenv("DRIFTNOTE_SMTP_PORT", str(mail_server.smtp_port))
    monkeypatch.setenv("DRIFTNOTE_SMTP_TLS", "false")
    monkeypatch.setenv("DRIFTNOTE_SMTP_STARTTLS", "false")

    result = runner.invoke(cli_app, ["send-prompt", "--date", "2026-05-09"])
    assert result.exit_code == 0, result.output

    # Fetch the just-sent prompt and confirm body content.
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select("INBOX")
    typ, data = mb.search(None, "ALL")
    assert typ == "OK" and data[0], "no message in INBOX"
    typ, msg_data = mb.fetch(data[0].split()[-1], "(RFC822)")
    raw = msg_data[0][1]
    mb.logout()

    # The full-template markers (any of these) prove we sent the real template
    # rather than the "How was {date}?" placeholder.
    assert b"Mood: <one emoji>" in raw, raw
    assert b"hashtags anywhere in the body" in raw
    assert b"Up to 4 photos and 2 videos as attachments." in raw
    assert b"\xe2\x80\x94 Driftnote" in raw  # em-dash + Driftnote signature (UTF-8)
    # And the date placeholder substituted correctly.
    assert b"How was 2026-05-09?" in raw
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_cli.py::test_send_prompt_renders_full_template_body -v`

Expected: FAIL on `assert b"Mood: <one emoji>" in raw` — the placeholder body lacks this string.

- [ ] **Step 3: Fix the path resolution in `cli.py`**

Locate `_run_send_prompt` in `src/driftnote/cli.py` (around line 232). Replace this block:

```python
    body_template_path = (
        Path("src/driftnote/web/templates") / config.prompt.body_template.split("/")[-1]
    )
    body = body_template_path.read_text() if body_template_path.exists() else "How was {date}?"
```

with:

```python
    # Mirror the path-resolution used by the lifespan in driftnote.app.create_app
    # so CLI-driven and scheduler-driven sends use the same template.
    web_root = Path(__file__).parent / "web"
    body_template_path = web_root / config.prompt.body_template
    if not body_template_path.exists():
        raise typer.BadParameter(
            f"prompt template not found at {body_template_path}; "
            f"check [prompt].body_template in {os.environ['DRIFTNOTE_CONFIG']}",
        )
    body = body_template_path.read_text(encoding="utf-8")
```

Note: `os` and `Path` are already imported at the top of `cli.py`. `typer` too.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_cli.py::test_send_prompt_renders_full_template_body -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `uv run pytest -m "not live" -q`
Expected: 176 passed (175 prior + 1 new).

- [ ] **Step 6: Lint + types**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/driftnote/cli.py tests/integration/test_cli.py
git commit -m "$(cat <<'EOF'
fix(cli): correct send-prompt template path; raise on missing template

cli.py:_run_send_prompt resolved the template via
  Path("src/driftnote/web/templates") / "prompt.txt.j2"
which strips the "emails/" subdir from config.prompt.body_template
("templates/emails/prompt.txt.j2") AND uses a relative path. The file
isn't found, the silent fallback "How was {date}?" fires, and the
recipient gets a one-line stub instead of the multi-line prompt body.

Mirror the lifespan's resolution from driftnote.app.create_app:
  Path(__file__).parent / "web" / config.prompt.body_template
and raise a typer.BadParameter when the file is missing — silent
fallbacks have to go.

Closes #2
EOF
)"
```

### Closeout

**Acceptance criteria:**
- [ ] CLI `driftnote send-prompt` renders the full multi-line template (not the placeholder)
- [ ] If the template path is wrong/missing, the CLI fails loudly with a useful error
- [ ] All existing tests still pass
- [ ] One new integration test covers the regression
- [ ] Closes #2 via the commit message
