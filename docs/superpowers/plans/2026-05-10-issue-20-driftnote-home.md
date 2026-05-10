# Issue #20 — `DRIFTNOTE_HOME` bootstrap with auto-loaded `.env`

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the boilerplate for local Driftnote development. Introduce a `DRIFTNOTE_HOME` env var (default `~/.driftnote`), load `$DRIFTNOTE_HOME/.env` via `python-dotenv` with `override=False`, and fall back to `$DRIFTNOTE_HOME/{config.toml,data}` when `DRIFTNOTE_CONFIG`/`DRIFTNOTE_DATA_ROOT` are unset.

**Architecture:** A new ~25-line `src/driftnote/bootstrap.py` module exposes `load_env()`. Two call sites: first line of `create_app()` and a Typer `@app.callback()` in the CLI. Both calls are no-ops on the second hit thanks to `setdefault` and `load_dotenv(..., override=False)`.

**Tech Stack:** Python 3.14, FastAPI, Typer, pytest, python-dotenv (new dep).

**Spec:** [docs/superpowers/specs/2026-05-10-issue-20-driftnote-home-design.md](../specs/2026-05-10-issue-20-driftnote-home-design.md)

**Issue:** https://github.com/maciej-makowski/driftnote/issues/20

**Branch:** `feat/issue-20-driftnote-home` (worktree at `/var/home/cfiet/Documents/Projects/driftnote-dx-env/`)

---

## Working notes for the implementer

- All paths in this plan are relative to the repo root (the worktree).
- Tests run via `uv run pytest`. The fast suite excludes `live` and `slow` markers and runs as a pre-commit hook.
- `from __future__ import annotations` everywhere.
- Pre-commit hooks: `ruff` (lint + auto-fix), `ruff-format`, `pytest -q -m "not live and not slow" tests/unit`. If a hook fails, fix the cause and create a NEW commit; never `--amend`.
- Existing tests `monkeypatch.setenv("DRIFTNOTE_CONFIG", ...)` and `monkeypatch.setenv("DRIFTNOTE_DATA_ROOT", ...)` — with `override=False` and `setdefault`, those tests should pass unchanged because the explicit env always wins.

---

## Chunk 1: Bootstrap module + dependency

### Task 1.1: Add `python-dotenv` dependency

**Files:**
- Modify: `pyproject.toml`
- Regenerate: `uv.lock`

- [ ] **Step 1: Add the dependency**

Open `pyproject.toml`. Find the `[project]` table's `dependencies` array. Add `"python-dotenv>=1.0",` to that array, alphabetically near the existing entries (it sorts after `pyjwt[crypto]` and before `pyyaml` in the current alphabet). Read the file first to see exact ordering.

- [ ] **Step 2: Regenerate `uv.lock`**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-dx-env
uv sync
```

Expected: `uv.lock` updated; `python-dotenv` added; no other transitive deps added (it has no runtime dependencies).

- [ ] **Step 3: Confirm import works**

```bash
uv run python -c "from dotenv import load_dotenv; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add python-dotenv for .env autoload bootstrap"
```

### Task 1.2: Add `bootstrap.py` (TDD)

**Files:**
- Create: `src/driftnote/bootstrap.py`
- Create: `tests/unit/test_bootstrap.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_bootstrap.py`:

```python
"""Tests for the DRIFTNOTE_HOME / .env bootstrap helper."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from driftnote.bootstrap import driftnote_home, load_env


def test_driftnote_home_defaults_to_user_home_dotfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DRIFTNOTE_HOME", raising=False)
    assert driftnote_home() == Path.home() / ".driftnote"


def test_driftnote_home_respects_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    assert driftnote_home() == tmp_path


def test_load_env_loads_dotenv_from_driftnote_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("DRIFTNOTE_TESTKEY=from_dotenv\n")
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_TESTKEY", raising=False)
    monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)
    monkeypatch.delenv("DRIFTNOTE_DATA_ROOT", raising=False)

    load_env()

    assert os.environ["DRIFTNOTE_TESTKEY"] == "from_dotenv"


def test_load_env_does_not_override_existing_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("DRIFTNOTE_TESTKEY=from_dotenv\n")
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTNOTE_TESTKEY", "from_shell")

    load_env()

    assert os.environ["DRIFTNOTE_TESTKEY"] == "from_shell"


def test_load_env_defaults_config_path_from_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)

    load_env()

    assert os.environ["DRIFTNOTE_CONFIG"] == str(tmp_path / "config.toml")


def test_load_env_defaults_data_root_from_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_DATA_ROOT", raising=False)

    load_env()

    assert os.environ["DRIFTNOTE_DATA_ROOT"] == str(tmp_path / "data")


def test_load_env_does_not_override_explicit_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTNOTE_CONFIG", "/somewhere/else.toml")

    load_env()

    assert os.environ["DRIFTNOTE_CONFIG"] == "/somewhere/else.toml"


def test_load_env_no_dotenv_file_is_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tmp_path has no .env — should not raise; defaults still applied."""
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)

    load_env()  # must not raise

    assert os.environ["DRIFTNOTE_CONFIG"] == str(tmp_path / "config.toml")


def test_load_env_unreadable_dotenv_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.env` file we cannot read is silently skipped; defaults still apply.

    `python-dotenv.load_dotenv()` returns False for missing/directory paths
    but raises `PermissionError` for a regular file with mode 0o000. Our
    contract is to swallow that. Test by writing a real .env, chmod'ing it
    to 0o000, and checking load_env() returns normally.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root bypasses POSIX file mode")
    env_file = tmp_path / ".env"
    env_file.write_text("DRIFTNOTE_TESTKEY_UNREADABLE=should_not_load\n")
    env_file.chmod(0o000)
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_TESTKEY_UNREADABLE", raising=False)
    monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)
    try:
        load_env()  # must not raise
    finally:
        env_file.chmod(0o644)  # restore so pytest can clean up tmp_path

    assert "DRIFTNOTE_TESTKEY_UNREADABLE" not in os.environ
    assert os.environ["DRIFTNOTE_CONFIG"] == str(tmp_path / "config.toml")
```

- [ ] **Step 2: Run the new tests, confirm they fail**

```bash
uv run pytest tests/unit/test_bootstrap.py -v
```

Expected: all 9 tests fail with `ModuleNotFoundError: No module named 'driftnote.bootstrap'`.

- [ ] **Step 3: Create `src/driftnote/bootstrap.py`**

Write this exact content:

```python
"""DRIFTNOTE_HOME / .env bootstrap loader.

Resolves a single home directory (default ~/.driftnote), loads .env from
it via python-dotenv with `override=False`, and fills in defaults for
DRIFTNOTE_CONFIG and DRIFTNOTE_DATA_ROOT when those are unset.

Idempotent: safe to call multiple times. Existing env vars always win.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from dotenv import load_dotenv

_DEFAULT_HOME = "~/.driftnote"


def driftnote_home() -> Path:
    """Resolve DRIFTNOTE_HOME (or ~/.driftnote default), expanduser()'d."""
    return Path(os.environ.get("DRIFTNOTE_HOME", _DEFAULT_HOME)).expanduser()


def load_env() -> None:
    """Load $DRIFTNOTE_HOME/.env and set defaults for derived env paths."""
    home = driftnote_home()
    env_file = home / ".env"
    # python-dotenv returns False for missing/directory paths but RAISES
    # PermissionError for an unreadable regular file. Swallow that — our
    # contract is "silently skip an unreadable .env; defaults still apply".
    with contextlib.suppress(OSError):
        load_dotenv(env_file, override=False)
    os.environ.setdefault("DRIFTNOTE_CONFIG", str(home / "config.toml"))
    os.environ.setdefault("DRIFTNOTE_DATA_ROOT", str(home / "data"))
```

The `contextlib.suppress(OSError)` is load-bearing — `python-dotenv` raises `PermissionError` when the file exists but is unreadable (verified empirically against `python-dotenv` 1.x). Missing files and directories at the path return `False` from `load_dotenv()` without raising, so the suppress block also covers those gracefully. No `is_file()` gate needed.

- [ ] **Step 4: Run the tests and confirm they pass**

```bash
uv run pytest tests/unit/test_bootstrap.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run the full unit suite**

```bash
uv run pytest tests/unit -q -m "not live and not slow"
```

Expected: green (no impact on other tests).

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/bootstrap.py tests/unit/test_bootstrap.py
git commit -m "feat(bootstrap): add DRIFTNOTE_HOME-aware .env loader"
```

---

## Chunk 2: Wire bootstrap into entry points

### Task 2.1: Call `load_env()` from `create_app()`

**Files:**
- Modify: `src/driftnote/app.py`

- [ ] **Step 1: Add the import + call**

Open `src/driftnote/app.py`. After the existing `from driftnote.alerts import AlertSender` import (alphabetically ordered first-party imports), add:

```python
from driftnote.bootstrap import load_env
```

Then locate `def create_app(*, skip_startup_jobs: bool = False) -> FastAPI:` (around line 50). The existing first line is `configure_logging(...)`. Insert `load_env()` BEFORE the `configure_logging` call:

```python
def create_app(*, skip_startup_jobs: bool = False) -> FastAPI:
    """Compose the full app. `skip_startup_jobs=True` is for tests."""
    load_env()
    configure_logging(
        level="INFO",
        json_output=os.environ.get("DRIFTNOTE_ENVIRONMENT", "prod") != "dev",
    )
    # ...rest unchanged
```

This ensures the `os.environ.get("DRIFTNOTE_ENVIRONMENT", ...)` call below sees any value provided by `.env`.

- [ ] **Step 2: Run app-level tests**

```bash
uv run pytest tests/integration/test_app_full.py tests/integration/test_healthz.py -v
```

Expected: green. These tests `monkeypatch.setenv("DRIFTNOTE_CONFIG", ...)` before calling `create_app`, so `load_env()`'s `setdefault` is a no-op for those keys and behaviour is identical.

### Task 2.2: Call `load_env()` from a Typer callback (TDD)

**Files:**
- Modify: `src/driftnote/cli.py`
- Modify: `tests/integration/test_cli.py` (append one new test)

- [ ] **Step 1: Add the failing integration test**

Append to `tests/integration/test_cli.py` (at the end of the file, after the last existing test):

```python
def test_cli_callback_loads_dotenv_before_subcommand(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Typer callback runs `load_env()` before any subcommand fires.

    With DRIFTNOTE_HOME pointing at a tmp dir containing a .env, invoking
    `driftnote --help` is enough to trigger the callback and populate any
    env vars the .env declares.
    """
    (tmp_path / ".env").write_text("DRIFTNOTE_TESTKEY_CLI=from_cli_dotenv\n")
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_TESTKEY_CLI", raising=False)

    result = runner.invoke(cli_app, ["--help"])

    assert result.exit_code == 0, result.output
    assert os.environ["DRIFTNOTE_TESTKEY_CLI"] == "from_cli_dotenv"
```

Note: `Path`, `pytest`, `cli_app`, `CliRunner`, and the `runner` fixture are already in scope. The file does NOT currently import `os` — add `import os` to the imports block at the top of the file (alphabetically, between `imaplib` and `from datetime`).

- [ ] **Step 2: Run the test and confirm it fails**

```bash
uv run pytest tests/integration/test_cli.py::test_cli_callback_loads_dotenv_before_subcommand -v
```

Expected: fails on the `os.environ["DRIFTNOTE_TESTKEY_CLI"]` assertion (key won't be set — no callback yet).

- [ ] **Step 3: Wire the callback into `cli.py`**

Open `src/driftnote/cli.py`. Add the import after the existing first-party imports:

```python
from driftnote.bootstrap import load_env
```

Then locate the `app = typer.Typer(...)` line (around line 19). Immediately after it, add:

```python
@app.callback()
def _bootstrap() -> None:
    """Load DRIFTNOTE_HOME/.env before any subcommand runs."""
    load_env()
```

Typer fires `@app.callback()` exactly once per CLI invocation, before any subcommand body executes — including for `--help`. This is what the new test relies on.

- [ ] **Step 4: Make the existing `--help` test hermetic**

The pre-existing `test_poll_responses_help_lists_command` (around line 149 in `tests/integration/test_cli.py`) calls `runner.invoke(cli_app, ["--help"])` without setting `DRIFTNOTE_HOME`. After this change, that invocation fires `load_env()`, which mutates the process's `os.environ` based on whatever `~/.driftnote/` exists on the host and persists into subsequent tests.

Make it hermetic: change the test signature from `runner: CliRunner` to `tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch`, and at the top of the body add:

```python
monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)
monkeypatch.delenv("DRIFTNOTE_DATA_ROOT", raising=False)
```

This pins `load_env()`'s effect to the tmp dir for the duration of the test; `monkeypatch.delenv` ensures `setdefault` writes the tmp-derived values, and pytest restores the original env after the test. Other tests in the file already follow this pattern.

- [ ] **Step 5: Run the new test, confirm it passes**

```bash
uv run pytest tests/integration/test_cli.py::test_cli_callback_loads_dotenv_before_subcommand -v
```

Expected: pass.

- [ ] **Step 6: Run the full CLI integration suite**

```bash
uv run pytest tests/integration/test_cli.py -v
```

Expected: green. Existing env-touching tests use `monkeypatch.setenv` before `runner.invoke`, so `load_env()`'s `setdefault` is a no-op for those keys — no behavioural change. The hermetic update to `test_poll_responses_help_lists_command` keeps it deterministic across pytest's test ordering.

- [ ] **Step 7: Commit**

```bash
git add src/driftnote/app.py src/driftnote/cli.py tests/integration/test_cli.py
git commit -m "feat(bootstrap): wire load_env into create_app and Typer callback"
```

---

## Chunk 3: Documentation

### Task 3.1: Add "Local development" section to README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README to find the natural insertion point**

```bash
head -60 README.md
```

The README has setup, run, and architecture sections. Add the new "Local development" section after the existing setup section but before "Architecture" (or wherever the existing structure most naturally surfaces dev ergonomics — read carefully and place it where a developer skimming for "how do I run this locally" would find it).

- [ ] **Step 2: Append the section**

Insert the content below into `README.md` at the chosen insertion point. The plan wraps the content in a four-backtick outer fence so the inner three-backtick fences render correctly here; **do not** paste the outer four-backtick fence into the README — only the content between them.

Match the heading level to the surrounding README (use `##` if existing top-level sections use `##`).

````markdown
## Local development

Driftnote reads its config and SQLite/media data root from a single home
directory. By convention this is `~/.driftnote/`, but you can override
it with the `DRIFTNOTE_HOME` environment variable.

A typical local setup:

```
~/.driftnote/
├── config.toml          # see deploy/README.md §3 for the canonical template
├── .env                 # secrets + per-machine overrides
├── data/                # SQLite + entries/ + raw/ + backups/
└── ...
```

The `.env` is auto-loaded at startup (CLI subcommands and the FastAPI app
both call the same loader). Existing environment variables always win,
so production systemd quadlets and CI runs are unaffected.

A minimal `.env` for local development:

```ini
DRIFTNOTE_GMAIL_USER=tester@example.com
DRIFTNOTE_GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
DRIFTNOTE_ENVIRONMENT=dev
DRIFTNOTE_WEB_BASE_URL=http://localhost:8000
```

With those two files in place, you can run any CLI command without
exporting anything in the shell:

```bash
uv run driftnote serve
uv run driftnote send-prompt
```

To use a custom location:

```bash
export DRIFTNOTE_HOME=/path/to/your/driftnote
uv run driftnote serve
```

Override individual paths if needed: `DRIFTNOTE_CONFIG` (defaults to
`$DRIFTNOTE_HOME/config.toml`) and `DRIFTNOTE_DATA_ROOT` (defaults to
`$DRIFTNOTE_HOME/data`) still take precedence over the home-derived
defaults.
````

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): document DRIFTNOTE_HOME and local .env workflow"
```

---

## Chunk 4: Final verification + PR

### Task 4.1: Full fast suite

- [ ] **Step 1: Run unit + integration (excluding live/slow)**

```bash
uv run pytest -q -m "not live and not slow"
```

Expected: all green. The new tests bring the total up by 10 (9 unit + 1 integration).

### Task 4.2: Manual smoke test

- [ ] **Step 1: Verify `DRIFTNOTE_HOME` default works**

Make sure no leftover env state contaminates the smoke test:

```bash
unset DRIFTNOTE_HOME DRIFTNOTE_CONFIG DRIFTNOTE_DATA_ROOT
```

If you have a real `~/.driftnote/{config.toml,.env}` already (which you should — this branch is built on the prod install spec):

```bash
uv run driftnote --help
```

Expected: `--help` output renders, no `KeyError`, no traceback.

If you don't have `~/.driftnote/`, point at a tmp:

```bash
SMOKE_DIR=$(mktemp -d)
echo 'DRIFTNOTE_GMAIL_USER=smoke@example.com' > "$SMOKE_DIR/.env"
DRIFTNOTE_HOME="$SMOKE_DIR" uv run driftnote --help
rm -rf "$SMOKE_DIR"
```

Expected: same.

### Task 4.3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/issue-20-driftnote-home
```

- [ ] **Step 2: Open the PR**

Use this body:

```bash
gh pr create --title "feat: DRIFTNOTE_HOME bootstrap with auto-loaded .env (#20)" --body "$(cat <<'EOF'
## Summary

Closes #20.

- New \`DRIFTNOTE_HOME\` env var (default \`~/.driftnote\`).
- On startup, \`$DRIFTNOTE_HOME/.env\` is loaded via \`python-dotenv\` with \`override=False\` — existing env vars (production systemd, CI) always win.
- \`DRIFTNOTE_CONFIG\` and \`DRIFTNOTE_DATA_ROOT\` fall back to \`$DRIFTNOTE_HOME/config.toml\` and \`$DRIFTNOTE_HOME/data\` when unset.
- One bootstrap module (\`src/driftnote/bootstrap.py\`), called from \`create_app()\` and a Typer \`@app.callback()\`.

## DX outcome

With \`~/.driftnote/{config.toml,.env}\` already in place, \`uv run driftnote serve\` Just Works on a fresh dev clone — no shell exports required.

## Test plan

- [x] 9 unit tests in \`tests/unit/test_bootstrap.py\` cover defaults, override semantics, missing/unreadable \`.env\`
- [x] 1 CLI integration test proves the Typer callback loads \`.env\` before any subcommand runs
- [x] Full fast suite green
- [x] Manual smoke: \`uv run driftnote --help\` works with no shell exports when \`~/.driftnote/.env\` exists

## Out of scope

- Renaming the prod systemd quadlet's \`driftnote.env\` → \`.env\` (separate optional cleanup PR)
- Centralising existing direct \`os.environ[...]\` reads behind a settings object

## Spec + plan

- Spec: \`docs/superpowers/specs/2026-05-10-issue-20-driftnote-home-design.md\`
- Plan: \`docs/superpowers/plans/2026-05-10-issue-20-driftnote-home.md\`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

(The PR description is plain markdown — escape backticks in the heredoc only as the example shows.)
