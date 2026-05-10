# `DRIFTNOTE_HOME` bootstrap with auto-loaded `.env`

> Design spec for [issue #20](https://github.com/maciej-makowski/driftnote/issues/20).

## Goal

Cut the boilerplate to run Driftnote locally. Today every CLI invocation requires `DRIFTNOTE_CONFIG` (and usually `DRIFTNOTE_DATA_ROOT`) to be exported in the shell. The same env vars are written to `~/.driftnote/driftnote.env` for the production systemd quadlet but the local shell never sees them. With this change, a developer with `~/.driftnote/{config.toml,.env}` already in place runs `uv run driftnote serve` and it Just Works.

## Architecture

A new tiny module `src/driftnote/bootstrap.py` exposes one function `load_env()` that:

1. Resolves `DRIFTNOTE_HOME` (env var, defaults to `~/.driftnote`, `Path.expanduser()`'d).
2. Reads `$DRIFTNOTE_HOME/.env` via `python-dotenv` with `override=False` (existing env wins; production systemd's `EnvironmentFile=` keeps working unchanged; CI/test environments are unaffected).
3. Sets `os.environ.setdefault("DRIFTNOTE_CONFIG", str(home / "config.toml"))`.
4. Sets `os.environ.setdefault("DRIFTNOTE_DATA_ROOT", str(home / "data"))`.

The function is idempotent (re-runs are cheap; `setdefault` is a no-op when the key exists; `load_dotenv(..., override=False)` is similarly a no-op when keys are already present).

Two call sites:

- `src/driftnote/app.py::create_app()` — first line, before any `os.environ[...]` read.
- `src/driftnote/cli.py` — a Typer `@app.callback()` so the call runs exactly once before any subcommand. Each subcommand's body keeps reading env vars unchanged.

## Public API

```python
# src/driftnote/bootstrap.py
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_DEFAULT_HOME = "~/.driftnote"


def driftnote_home() -> Path:
    """Resolve DRIFTNOTE_HOME (or ~/.driftnote default), `expanduser()`'d."""
    return Path(os.environ.get("DRIFTNOTE_HOME", _DEFAULT_HOME)).expanduser()


def load_env() -> None:
    """Load `$DRIFTNOTE_HOME/.env` and set defaults for derived paths.

    Idempotent. Existing env vars always win (`override=False` on dotenv,
    `setdefault` on derived paths). Safe to call from multiple entry
    points.
    """
    home = driftnote_home()
    env_file = home / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)
    os.environ.setdefault("DRIFTNOTE_CONFIG", str(home / "config.toml"))
    os.environ.setdefault("DRIFTNOTE_DATA_ROOT", str(home / "data"))
```

## Dependency

- Add `python-dotenv>=1.0` to `[project].dependencies` in `pyproject.toml`.

## Behaviour matrix

| Scenario | DRIFTNOTE_HOME | DRIFTNOTE_CONFIG | DRIFTNOTE_DATA_ROOT | Result |
|---|---|---|---|---|
| Fresh dev clone, `~/.driftnote/{config.toml,.env}` exists | unset → defaults `~/.driftnote` | unset → set to `~/.driftnote/config.toml` | unset → set to `~/.driftnote/data` | works zero-config |
| Dev with custom location | set | unset → set from home | unset → set from home | works |
| Prod (systemd quadlet) | unset → defaults `~/.driftnote` (i.e. `/var/home/driftnote/.driftnote`) | already set by `EnvironmentFile=` | already set by `EnvironmentFile=` | unchanged: setdefault is a no-op |
| CI / test (`monkeypatch.setenv`) | unset | already set by test | already set by test | unchanged: setdefault is a no-op; if no `~/.driftnote/.env` exists on CI, dotenv is a no-op too |
| Override config.toml location explicitly | set | set explicitly | unset → set from home | works; explicit `DRIFTNOTE_CONFIG` wins |

## Production safety

The systemd quadlet (`deploy/driftnote.container`) currently sets `EnvironmentFile=%h/.driftnote/driftnote.env`. After this change, the in-process `load_env()` *also* tries to read `%h/.driftnote/.env`. These are different file names (`driftnote.env` vs `.env`) — there is no collision. Operators who want to consolidate can rename `driftnote.env` → `.env` and drop the `EnvironmentFile=` line in a separate, optional cleanup. **Out of scope for this PR.**

## Tests

A new test file `tests/unit/test_bootstrap.py` covers:

1. `load_env_loads_dotenv_from_driftnote_home`: write a `.env` with `FOO=bar` into a tmp dir, set `DRIFTNOTE_HOME=tmp_dir`, call `load_env()`, assert `os.environ["FOO"] == "bar"`.
2. `load_env_does_not_override_existing_env`: pre-set `FOO=baz`, write `.env` with `FOO=bar`, call `load_env()`, assert `os.environ["FOO"] == "baz"`.
3. `load_env_defaults_config_path_from_home`: tmp dir as `DRIFTNOTE_HOME`, no `DRIFTNOTE_CONFIG` set, call `load_env()`, assert `os.environ["DRIFTNOTE_CONFIG"] == str(tmp_dir / "config.toml")`.
4. `load_env_defaults_data_root_from_home`: same shape; `DRIFTNOTE_DATA_ROOT` ends up `str(tmp_dir / "data")`.
5. `load_env_does_not_override_explicit_config`: pre-set `DRIFTNOTE_CONFIG=/somewhere/else.toml`, call `load_env()`, value unchanged.
6. `driftnote_home_defaults_to_user_home_dotfile`: with `DRIFTNOTE_HOME` unset, `driftnote_home() == Path.home() / ".driftnote"`.
7. `load_env_no_dotenv_file_is_ok`: tmp dir without `.env`, call `load_env()`, no exception, defaults still applied.

All tests use `monkeypatch` to isolate env state. No reliance on the user's actual `~/.driftnote/.env`.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/bootstrap.py` | New module (~25 lines). |
| `src/driftnote/app.py` | Call `bootstrap.load_env()` as first line of `create_app()`. |
| `src/driftnote/cli.py` | Add a Typer `@app.callback()` that calls `bootstrap.load_env()` before any subcommand. |
| `pyproject.toml` | Add `python-dotenv>=1.0` to `[project].dependencies`. |
| `uv.lock` | Regenerated by `uv sync`. |
| `tests/unit/test_bootstrap.py` | New file with 7 tests. |
| `README.md` | Add a "Local development" section explaining `DRIFTNOTE_HOME` and the `~/.driftnote` convention. |

## Acceptance criteria

- [ ] `DRIFTNOTE_HOME` env var documented in README "Local development" section.
- [ ] Default of `~/.driftnote` when `DRIFTNOTE_HOME` is unset.
- [ ] dotenv loads with `override=False` (already-set env wins).
- [ ] `DRIFTNOTE_CONFIG` falls back to `$DRIFTNOTE_HOME/config.toml`.
- [ ] `DRIFTNOTE_DATA_ROOT` falls back to `$DRIFTNOTE_HOME/data`.
- [ ] 7 unit tests in `tests/unit/test_bootstrap.py` cover the contract.
- [ ] Existing tests pass (no behavioural regressions).
- [ ] `uv run driftnote --help` and `uv run driftnote serve` succeed with `~/.driftnote/{config.toml,.env}` only — no shell exports.

## Out of scope

- Renaming `~/.driftnote/driftnote.env` → `.env` and dropping `EnvironmentFile=` from the quadlet.
- Reading config from sources other than env or dotenv (CLI flags, system /etc paths, etc.).
- A `.env.example` template at the repo root.
- Replacing existing direct `os.environ[...]` reads with a centralised settings object — out of scope; the env-var contract is unchanged, only the *source* of those vars expands to include `.env`.

## Risks

**Risk:** `load_env()` is called from CLI module-import side effects via the Typer `@app.callback()`, but pytest collections that import `driftnote.cli` would trigger it too if it ran at import time.
**Mitigation:** The callback runs only when Typer dispatches a subcommand, not at import. Test `test_cli.py` uses `typer.testing.CliRunner` which exercises the callback path; the existing `monkeypatch.setenv` calls run *before* `CliRunner.invoke`, so `setdefault` makes `load_env()` a no-op for those tests.

**Risk:** A developer's `~/.driftnote/.env` could accidentally pollute test runs if pytest is invoked from outside a worktree without `monkeypatch` overrides.
**Mitigation:** All tests that exercise env vars already use `monkeypatch.setenv`. dotenv's `override=False` is the second line of defence. Tests that *don't* set the env vars don't need them.

**Risk:** New dep `python-dotenv` adds supply-chain surface.
**Mitigation:** It's a tiny, mature, single-purpose package (Anthropic ships it; FastAPI ecosystem standard). Negligible risk.
