# Driftnote Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Driftnote — a personal journaling app prompted by daily email, ingested via IMAP into a markdown-on-disk + SQLite-index store, browsable/editable via a FastAPI + HTMX web UI behind Cloudflare Access, with weekly/monthly/yearly digest emails, deployed on a Raspberry Pi as a Podman container.

**Architecture:** Single Python 3.14 process. Filesystem is the source of truth (`data/entries/YYYY/MM/DD/{entry.md,raw/*.eml,originals,web,thumbs}`); SQLite is a derived FTS5 index. APScheduler drives daily prompt, IMAP poll, digests, and disk-check jobs in-process. Mail transport is pluggable (Gmail App Password in prod, GreenMail in dev/CI). Cloudflare Access fronts the web UI; the app verifies the `Cf-Access-Jwt-Assertion` header.

**Tech Stack:** Python 3.14, FastAPI, Jinja2 + HTMX, SQLAlchemy + SQLite (WAL + FTS5), APScheduler, aioimaplib + aiosmtplib, Pillow + pillow-heif, ffmpeg (shell-out), structlog, pydantic-settings, PyJWT, Typer, uv, ruff, mypy, pytest, hypothesis, freezegun, testcontainers, GreenMail, Podman + systemd quadlet.

**Spec:** [`docs/superpowers/specs/2026-05-06-driftnote-design.md`](../specs/2026-05-06-driftnote-design.md). This plan is the operational expansion of that spec; defer to the spec for "why".

**Conventions enforced throughout:**
- TDD where it adds value (logic, parsers, repositories, jobs); "build + verify with smoke check" for infra files (Containerfiles, CI YAML, systemd units).
- Each task ends with a single commit. Conventional Commits prefixes (`feat:`, `test:`, `chore:`, `ci:`, `docs:`, `refactor:`).
- Imports sorted by `ruff`. `from __future__ import annotations` at the top of every module that uses type hints.
- All datetime values stored as ISO-8601 strings in UTC unless explicitly local-zoned.
- Never log secrets. `JOURNAL_GMAIL_APP_PASSWORD` and `DRIFTNOTE_GMAIL_APP_PASSWORD` (the canonical env var name) must be redacted from any structured log payload.

**Worktree / parallelism strategy for executors:**
- Chunks 2 and 3 are independent and may be executed in parallel worktrees. Same for {5, 6, 7} after Chunks 2–4 land.
- After each parallel cohort lands on `master`, rebase next-chunk worktrees on the latest `master` before continuing.
- If using `superpowers:subagent-driven-development`: one subagent per task, fresh context, two-stage review per the skill.

---

## Chunk index

| # | Chunk | Depends on | File at chunk end |
|---|---|---|---|
| 1 | Foundation A: skeleton, container, config, logging | — | dev compose runs GreenMail; config + logging modules |
| 2 | Foundation B: models, db, minimal app, CI | 1 | bootable container with `/healthz`; CI green |
| 3 | Filesystem (paths, markdown_io, locks) | 2 | entry.md round-trips via property tests |
| 4 | Repository | 2 | full SQL access surface, no ORM leaks |
| 5 | Mail transport (IMAP + SMTP via GreenMail) | 2 | can send/receive via GreenMail |
| 6 | Ingestion pipeline | 3, 4, 5 | end-to-end: `.eml` in → entry on disk + DB |
| 7 | Scheduler, jobs, alerts | 6 | scheduled prompts/polls/disk-checks/alerts run |
| 8 | Digest rendering | 4 | digest HTML rendered for fixed inputs |
| 9 | Web layer | 3, 4, 8 | browse/edit/admin UI works locally |
| 10 | CLI + app composition | 6, 7, 8, 9 | full app boots, CLI commands work |
| 11 | Deployment, CI image build, docs | 10 | container in GHCR, README, runbook, quadlet |

**Parallelism opportunities for executors using `subagent-driven-development`:**
- After Chunk 2 lands on `master`: Chunks 3, 4, and 5 can run in parallel worktrees.
- After Chunk 6 lands: Chunks 7, 8, and 9 can run in parallel worktrees.
- All other chunks have linear dependencies and should run in sequence.

---

## Chunk 1: Foundation A — skeleton, container, config, logging

**Outcome of this chunk:** Project skeleton (uv + ruff + mypy + pytest), Containerfile that builds a Python 3.14 image with libheif + ffmpeg, dev compose with GreenMail, config loader (TOML + env, secrets validated from env only), and structured logging with secret redaction. No business logic yet; no FastAPI app yet.

### Task 1.1: Repo bootstrap

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.python-version`
- Create: `README.md` (skeleton — full content lands in Chunk 9)
- Create: `src/driftnote/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py` (skeleton)
- Create: `.editorconfig`

- [ ] **Step 1: Create `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
*.egg-info/
build/
dist/

# uv
.venv/

# Editor
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Project
/data/
/var/
/local/
*.local.toml
*.local.env
.env
.env.*
!.env.example
```

- [ ] **Step 2: Create `.python-version`**

```
3.14
```

- [ ] **Step 3: Create `.editorconfig`**

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.py]
indent_size = 4

[*.{yml,yaml,toml,json,html,js,css,j2}]
indent_size = 2

[Makefile]
indent_style = tab
```

- [ ] **Step 4: Create `pyproject.toml`**

```toml
[project]
name = "driftnote"
version = "0.1.0"
description = "Email-driven personal journaling app"
readme = "README.md"
requires-python = ">=3.14"
license = { text = "MIT" }
authors = [{ name = "Maciej Makowski" }]
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0",
    "apscheduler>=3.10",
    "jinja2>=3.1",
    "pillow>=11.0",
    "pillow-heif>=0.20",
    "aioimaplib>=2.0",
    "aiosmtplib>=3.0",
    "structlog>=24.4",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "pyjwt[crypto]>=2.9",
    "typer>=0.13",
    "markdown-it-py>=3.0",
    "python-multipart>=0.0.12",
    "httpx>=0.27",
]

[project.scripts]
driftnote = "driftnote.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/driftnote"]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "hypothesis>=6.115",
    "freezegun>=1.5",
    "testcontainers>=4.8",
    "ruff>=0.7",
    "mypy>=1.13",
    "pre-commit>=4.0",
    "types-requests",
]

[tool.ruff]
line-length = 100
target-version = "py314"
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E", "W",   # pycodestyle
    "F",        # pyflakes
    "I",        # isort
    "N",        # pep8-naming
    "B",        # flake8-bugbear
    "UP",       # pyupgrade
    "RUF",      # ruff
    "PTH",      # use pathlib
    "SIM",      # simplify
]
ignore = [
    "E501",  # handled by formatter
    "B008",  # FastAPI Depends() requires call in default
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]  # assert is fine in tests

[tool.mypy]
python_version = "3.14"
strict = true
warn_unused_ignores = true
warn_redundant_casts = true
plugins = ["pydantic.mypy"]
mypy_path = "src"
files = ["src", "tests"]

[[tool.mypy.overrides]]
module = ["aioimaplib.*", "apscheduler.*", "pillow_heif.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "live: requires real Gmail credentials; not run in CI",
    "slow: deselect with '-m \"not slow\"'",
]
addopts = "-ra --strict-markers"
```

- [ ] **Step 5: Create `src/driftnote/__init__.py`**

```python
"""Driftnote — personal journaling app."""

from __future__ import annotations

__version__ = "0.1.0"
```

- [ ] **Step 6: Create `tests/__init__.py`** (empty file)

- [ ] **Step 7: Create `tests/conftest.py`** (skeleton; expanded in later chunks)

```python
"""Shared pytest fixtures for Driftnote tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Iterator[Path]:
    """A temp data directory matching the prod layout."""
    data = tmp_path / "data"
    (data / "entries").mkdir(parents=True)
    yield data
```

- [ ] **Step 8: Create `README.md`** (skeleton, expanded in Chunk 9)

```markdown
# Driftnote

Personal email-driven journaling app. Daily prompt → reply with mood emoji + markdown body + optional photos/videos → calendar/tag/search-browsable web UI behind Cloudflare Access.

See [docs/superpowers/specs/2026-05-06-driftnote-design.md](docs/superpowers/specs/2026-05-06-driftnote-design.md) for design details.

## Quickstart

To be filled in.
```

- [ ] **Step 9: Verify install works**

Run: `uv sync`
Expected: dependencies install, `.venv/` created, no errors.

- [ ] **Step 10: Commit**

```bash
git add .gitignore .python-version .editorconfig pyproject.toml \
        src/driftnote/__init__.py tests/__init__.py tests/conftest.py README.md
git commit -m "chore: bootstrap project skeleton with uv + ruff + mypy + pytest"
```

After this commit `uv.lock` should also exist (created by `uv sync`):

```bash
git add uv.lock
git commit -m "chore: pin dependencies via uv.lock"
```

---

### Task 1.2: Containerfile + dev compose with GreenMail

**Files:**
- Create: `Containerfile`
- Create: `podman-compose.dev.yml`
- Create: `scripts/podman-remote.sh`
- Create: `.dockerignore`

- [ ] **Step 1: Create `Containerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy

# uv is the dependency installer
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# System deps: HEIC decoding (libheif), video poster (ffmpeg), tzdata
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libheif1 \
        ffmpeg \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY src /app/src
COPY config /app/config

RUN useradd --system --create-home --uid 1000 driftnote \
    && mkdir -p /var/driftnote/data /var/driftnote/backups \
    && chown -R driftnote:driftnote /var/driftnote /app

USER driftnote

EXPOSE 8000

CMD ["uvicorn", "--factory", "driftnote.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `.dockerignore`**

```gitignore
.git
.gitignore
.venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
htmlcov
.coverage
docs
tests
data
local
*.local.toml
*.local.env
```

- [ ] **Step 3: Create `scripts/podman-remote.sh`** (matches user's CLAUDE.md pattern)

```bash
#!/usr/bin/env bash
# Wrapper used by podman-compose --podman-path so it talks to the host's podman
# socket from inside a Fedora toolbox container.
exec podman --remote "$@"
```

Make it executable:

```bash
chmod +x scripts/podman-remote.sh
```

- [ ] **Step 4: Create `podman-compose.dev.yml`**

```yaml
# podman-compose -f podman-compose.dev.yml up -d
# Driftnote dev stack: app + GreenMail (in-memory IMAP + SMTP)

services:
  mail:
    image: greenmail/standalone:2.1.4
    environment:
      GREENMAIL_OPTS: >-
        -Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap
        -Dgreenmail.users=you:apppwd:you@example.com
        -Dgreenmail.hostname=0.0.0.0
        -Dgreenmail.auth.disabled
    ports:
      - "3025:3025"   # SMTP
      - "3143:3143"   # IMAP
      - "8080:8080"   # REST API for fixture seeding

  app:
    build:
      context: .
      dockerfile: Containerfile
    image: driftnote:dev
    depends_on:
      - mail
    environment:
      DRIFTNOTE_CONFIG: /app/config/config.dev.toml
      DRIFTNOTE_GMAIL_USER: you@example.com
      DRIFTNOTE_GMAIL_APP_PASSWORD: apppwd
      DRIFTNOTE_CF_ACCESS_AUD: dev
      DRIFTNOTE_CF_TEAM_DOMAIN: dev.example.com
      DRIFTNOTE_ENVIRONMENT: dev
      DRIFTNOTE_SMTP_HOST: mail
      DRIFTNOTE_SMTP_PORT: "3025"
      DRIFTNOTE_SMTP_TLS: "false"
      DRIFTNOTE_SMTP_STARTTLS: "false"
      DRIFTNOTE_IMAP_HOST: mail
      DRIFTNOTE_IMAP_PORT: "3143"
      DRIFTNOTE_IMAP_TLS: "false"
    volumes:
      - ./config:/app/config:Z
      - ./local/data:/var/driftnote/data:Z
    ports:
      - "127.0.0.1:8000:8000"
```

- [ ] **Step 5: Verify GreenMail image starts**

GreenMail's standalone webapp only exposes `GET /api/configuration`; for a readiness check, the simplest reliable probe is to confirm SMTP and IMAP TCP ports are accepting connections.

Run:
```bash
podman --remote run --rm -d --name greenmail-smoke \
    -e GREENMAIL_OPTS='-Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled' \
    -p 3025:3025 -p 3143:3143 -p 8080:8080 \
    greenmail/standalone:2.1.4 \
&& for i in 1 2 3 4 5 6 7 8 9 10; do
       nc -z localhost 3025 && nc -z localhost 3143 && break
       sleep 1
   done \
&& curl -sf http://localhost:8080/api/configuration > /dev/null \
&& podman --remote stop greenmail-smoke
```

Expected: SMTP (3025) and IMAP (3143) accept connections, configuration endpoint returns 200, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add Containerfile .dockerignore scripts/podman-remote.sh podman-compose.dev.yml
git commit -m "chore: add Containerfile and dev compose with GreenMail"
```

---

### Task 1.3: Configuration loading

**Files:**
- Create: `src/driftnote/config.py`
- Create: `config/config.example.toml`
- Create: `config/config.dev.toml`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Create `config/config.example.toml`** (full prod-shape, used as the canonical example)

```toml
# Driftnote configuration. Secrets come from env vars (DRIFTNOTE_*).

[schedule]
# All cron expressions are evaluated in [schedule.timezone].
daily_prompt   = "0 21 * * *"
weekly_digest  = "0 8 * * 1"
monthly_digest = "0 8 1 * *"
yearly_digest  = "0 8 1 1 *"
imap_poll      = "*/5 * * * *"
timezone       = "Europe/London"

[email]
imap_folder            = "Driftnote/Inbox"
imap_processed_folder  = "Driftnote/Processed"
recipient              = "you@gmail.com"
sender_name            = "Driftnote"
imap_host              = "imap.gmail.com"
imap_port              = 993
imap_tls               = true
smtp_host              = "smtp.gmail.com"
smtp_port              = 587
smtp_tls               = false
smtp_starttls          = true

[prompt]
subject_template = "[Driftnote] How was {date}?"
body_template    = "templates/emails/prompt.txt.j2"

[parsing]
mood_regex = '^\s*Mood:\s*(\S+)'
tag_regex  = '#(\w+)'
max_photos = 4
max_videos = 2

[digests]
weekly_enabled  = true
monthly_enabled = true
yearly_enabled  = true

[backup]
retain_months = 12
encrypt       = false
age_key_path  = ""

[disk]
warn_percent  = 80
alert_percent = 95
check_cron    = "0 */6 * * *"
data_path     = "/var/driftnote/data"
```

- [ ] **Step 2: Create `config/config.dev.toml`** (overrides for local dev with GreenMail)

```toml
[schedule]
daily_prompt   = "0 21 * * *"
weekly_digest  = "0 8 * * 1"
monthly_digest = "0 8 1 * *"
yearly_digest  = "0 8 1 1 *"
imap_poll      = "*/5 * * * *"
timezone       = "Europe/London"

[email]
imap_folder            = "INBOX"
imap_processed_folder  = "INBOX.Processed"
recipient              = "you@example.com"
sender_name            = "Driftnote (dev)"
imap_host              = "mail"
imap_port              = 3143
imap_tls               = false
smtp_host              = "mail"
smtp_port              = 3025
smtp_tls               = false
smtp_starttls          = false

[prompt]
subject_template = "[Driftnote] How was {date}?"
body_template    = "templates/emails/prompt.txt.j2"

[parsing]
mood_regex = '^\s*Mood:\s*(\S+)'
tag_regex  = '#(\w+)'
max_photos = 4
max_videos = 2

[digests]
weekly_enabled  = true
monthly_enabled = true
yearly_enabled  = true

[backup]
retain_months = 12
encrypt       = false
age_key_path  = ""

[disk]
warn_percent  = 80
alert_percent = 95
check_cron    = "0 */6 * * *"
data_path     = "/var/driftnote/data"
```

- [ ] **Step 3: Write the failing test for config loading**

Create `tests/unit/__init__.py` (empty). Create `tests/unit/test_config.py`:

```python
"""Tests for config loading."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from driftnote.config import Config, ConfigError, load_config


def _write_config(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(dedent(body))
    return p


def test_load_config_minimum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write_config(
        tmp_path,
        """
        [schedule]
        daily_prompt   = "0 21 * * *"
        weekly_digest  = "0 8 * * 1"
        monthly_digest = "0 8 1 * *"
        yearly_digest  = "0 8 1 1 *"
        imap_poll      = "*/5 * * * *"
        timezone       = "Europe/London"

        [email]
        imap_folder            = "Driftnote/Inbox"
        imap_processed_folder  = "Driftnote/Processed"
        recipient              = "you@gmail.com"
        sender_name            = "Driftnote"
        imap_host              = "imap.gmail.com"
        imap_port              = 993
        imap_tls               = true
        smtp_host              = "smtp.gmail.com"
        smtp_port              = 587
        smtp_tls               = false
        smtp_starttls          = true

        [prompt]
        subject_template = "[Driftnote] How was {date}?"
        body_template    = "templates/emails/prompt.txt.j2"

        [parsing]
        mood_regex = '^\\s*Mood:\\s*(\\S+)'
        tag_regex  = '#(\\w+)'
        max_photos = 4
        max_videos = 2

        [digests]
        weekly_enabled  = true
        monthly_enabled = true
        yearly_enabled  = true

        [backup]
        retain_months = 12
        encrypt       = false
        age_key_path  = ""

        [disk]
        warn_percent  = 80
        alert_percent = 95
        check_cron    = "0 */6 * * *"
        data_path     = "/var/driftnote/data"
        """,
    )
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", "u@example.com")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", "p")
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    monkeypatch.setenv("DRIFTNOTE_ENVIRONMENT", "dev")

    cfg = load_config(p)

    assert isinstance(cfg, Config)
    assert cfg.schedule.daily_prompt == "0 21 * * *"
    assert cfg.email.recipient == "you@gmail.com"
    assert cfg.parsing.max_photos == 4
    assert cfg.backup.retain_months == 12
    assert cfg.secrets.gmail_user == "u@example.com"
    assert cfg.secrets.gmail_app_password.get_secret_value() == "p"
    assert cfg.environment == "dev"


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env vars override TOML values for IMAP/SMTP host wiring (dev-mode pattern)."""
    p = _write_config(
        tmp_path,
        """
        [schedule]
        daily_prompt   = "0 21 * * *"
        weekly_digest  = "0 8 * * 1"
        monthly_digest = "0 8 1 * *"
        yearly_digest  = "0 8 1 1 *"
        imap_poll      = "*/5 * * * *"
        timezone       = "Europe/London"

        [email]
        imap_folder            = "Driftnote/Inbox"
        imap_processed_folder  = "Driftnote/Processed"
        recipient              = "you@gmail.com"
        sender_name            = "Driftnote"
        imap_host              = "imap.gmail.com"
        imap_port              = 993
        imap_tls               = true
        smtp_host              = "smtp.gmail.com"
        smtp_port              = 587
        smtp_tls               = false
        smtp_starttls          = true

        [prompt]
        subject_template = "[Driftnote] How was {date}?"
        body_template    = "templates/emails/prompt.txt.j2"

        [parsing]
        mood_regex = '^\\s*Mood:\\s*(\\S+)'
        tag_regex  = '#(\\w+)'
        max_photos = 4
        max_videos = 2

        [digests]
        weekly_enabled  = true
        monthly_enabled = true
        yearly_enabled  = true

        [backup]
        retain_months = 12
        encrypt       = false
        age_key_path  = ""

        [disk]
        warn_percent  = 80
        alert_percent = 95
        check_cron    = "0 */6 * * *"
        data_path     = "/var/driftnote/data"
        """,
    )
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", "u@example.com")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", "p")
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    monkeypatch.setenv("DRIFTNOTE_IMAP_HOST", "mail")
    monkeypatch.setenv("DRIFTNOTE_IMAP_PORT", "3143")
    monkeypatch.setenv("DRIFTNOTE_IMAP_TLS", "false")

    cfg = load_config(p)

    assert cfg.email.imap_host == "mail"
    assert cfg.email.imap_port == 3143
    assert cfg.email.imap_tls is False


def test_missing_secret_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write_config(tmp_path, "[schedule]\ntimezone = \"Europe/London\"\n")
    # Intentionally leave DRIFTNOTE_GMAIL_USER unset.
    for var in [
        "DRIFTNOTE_GMAIL_USER",
        "DRIFTNOTE_GMAIL_APP_PASSWORD",
        "DRIFTNOTE_CF_ACCESS_AUD",
        "DRIFTNOTE_CF_TEAM_DOMAIN",
    ]:
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ConfigError):
        load_config(p)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_config' from 'driftnote.config'`.

- [ ] **Step 5: Implement `src/driftnote/config.py`**

```python
"""Configuration loading: TOML + env, with strict validation."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or validated."""


CronExpr = Annotated[str, Field(pattern=r"^[\d\*/,\-]+(\s+[\d\*/,\-]+){4}$")]


class ScheduleConfig(BaseModel):
    daily_prompt: CronExpr
    weekly_digest: CronExpr
    monthly_digest: CronExpr
    yearly_digest: CronExpr
    imap_poll: CronExpr
    timezone: str


class EmailConfig(BaseModel):
    imap_folder: str
    imap_processed_folder: str
    recipient: str
    sender_name: str
    imap_host: str
    imap_port: int = Field(ge=1, le=65535)
    imap_tls: bool
    smtp_host: str
    smtp_port: int = Field(ge=1, le=65535)
    smtp_tls: bool
    smtp_starttls: bool


class PromptConfig(BaseModel):
    subject_template: str
    body_template: str


class ParsingConfig(BaseModel):
    mood_regex: str
    tag_regex: str
    max_photos: int = Field(ge=0)
    max_videos: int = Field(ge=0)

    @field_validator("mood_regex", "tag_regex")
    @classmethod
    def _validate_regex(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex {v!r}: {exc}") from exc
        return v


class DigestsConfig(BaseModel):
    weekly_enabled: bool
    monthly_enabled: bool
    yearly_enabled: bool


class BackupConfig(BaseModel):
    retain_months: int = Field(ge=1)
    encrypt: bool
    age_key_path: str


class DiskConfig(BaseModel):
    warn_percent: int = Field(ge=1, le=99)
    alert_percent: int = Field(ge=1, le=100)
    check_cron: CronExpr
    data_path: str


class Secrets(BaseSettings):
    """Secrets loaded from env only (never from TOML)."""

    model_config = SettingsConfigDict(env_prefix="DRIFTNOTE_", extra="ignore")

    gmail_user: str
    gmail_app_password: SecretStr
    cf_access_aud: str
    cf_team_domain: str
    age_key_path: str | None = None


class _EmailEnvOverrides(BaseSettings):
    """Optional env overrides for email transport (used by dev compose)."""

    model_config = SettingsConfigDict(env_prefix="DRIFTNOTE_", extra="ignore")

    imap_host: str | None = None
    imap_port: int | None = None
    imap_tls: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_tls: bool | None = None
    smtp_starttls: bool | None = None


class Config(BaseModel):
    """Top-level config. `secrets` accepts an already-instantiated Secrets
    rather than re-validating it from env (which would happen on raw dict input
    via BaseSettings re-init)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    schedule: ScheduleConfig
    email: EmailConfig
    prompt: PromptConfig
    parsing: ParsingConfig
    digests: DigestsConfig
    backup: BackupConfig
    disk: DiskConfig
    secrets: Secrets
    environment: Literal["dev", "prod"] = "prod"


def load_config(path: Path) -> Config:
    """Load TOML at path, apply env overrides, validate, and return Config.

    Secrets are *only* loaded from env vars (never from TOML) — load_config
    raises ConfigError if any required secret is missing. Email transport
    fields can be overridden via DRIFTNOTE_IMAP_* / DRIFTNOTE_SMTP_* env vars.
    """
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read config at {path}: {exc}") from exc

    try:
        secrets = Secrets()  # type: ignore[call-arg]
    except ValidationError as exc:
        raise ConfigError(f"missing/invalid secrets in env: {exc}") from exc

    overrides = _EmailEnvOverrides()  # type: ignore[call-arg]
    email_raw = dict(raw.get("email", {}))
    for field in (
        "imap_host", "imap_port", "imap_tls",
        "smtp_host", "smtp_port", "smtp_tls", "smtp_starttls",
    ):
        v = getattr(overrides, field, None)
        if v is not None:
            email_raw[field] = v
    raw["email"] = email_raw

    raw["environment"] = os.environ.get("DRIFTNOTE_ENVIRONMENT", "prod")
    raw["secrets"] = secrets

    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid config: {exc}") from exc
```

- [ ] **Step 6: Run tests — they should pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 7: Run lint + typecheck**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy`
Expected: 0 issues.

- [ ] **Step 8: Commit**

```bash
git add config/ src/driftnote/config.py tests/unit/__init__.py tests/unit/test_config.py
git commit -m "feat(config): TOML + env loader with secret validation"
```

---

### Task 1.4: Structured logging

**Files:**
- Create: `src/driftnote/logging.py`
- Create: `tests/unit/test_logging.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_logging.py`:

```python
"""Tests for structured logging setup."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import structlog

from driftnote.logging import REDACTED, configure_logging, redact_secrets


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()


def test_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)
    log = structlog.get_logger("test")
    log.info("hello", entry_date="2026-05-06", count=3)

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["entry_date"] == "2026-05-06"
    assert payload["count"] == 3
    assert payload["level"] == "info"


def test_redacts_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)
    log = structlog.get_logger("test")
    log.info("auth", gmail_app_password="hunter2", token="abc", user="u@example.com")

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert payload["gmail_app_password"] == REDACTED
    assert payload["token"] == REDACTED
    assert payload["user"] == "u@example.com"


def test_redact_secrets_helper_keeps_non_secret_keys() -> None:
    out = redact_secrets({"gmail_user": "u", "gmail_app_password": "p", "extra": 1})
    assert out == {"gmail_user": "u", "gmail_app_password": REDACTED, "extra": 1}


def test_pretty_output_when_json_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="DEBUG", json_output=False)
    log = structlog.get_logger("test")
    log.debug("dev")
    out = capsys.readouterr().out
    assert "dev" in out
    # Pretty output is not JSON — line should not parse.
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip().splitlines()[-1])


def test_logging_level_respected(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="WARNING", json_output=True)
    log = structlog.get_logger("test")
    log.info("filtered")
    log.warning("kept")
    out = capsys.readouterr().out
    assert "kept" in out
    assert "filtered" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_logging.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement `src/driftnote/logging.py`**

```python
"""Structured logging via structlog.

JSON output to stdout in prod (`json_output=True`); a friendlier
console renderer in dev. Secrets matched by name are redacted before
the renderer sees them.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog

REDACTED = "***REDACTED***"

_SECRET_KEYS = frozenset(
    {
        "gmail_app_password",
        "app_password",
        "password",
        "secret",
        "token",
        "authorization",
        "cf_access_jwt_assertion",
    }
)


def redact_secrets(event_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of event_dict with values for known secret keys masked."""
    return {k: (REDACTED if k.lower() in _SECRET_KEYS else v) for k, v in event_dict.items()}


def _redact_processor(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    return redact_secrets(event_dict)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure stdlib + structlog. Idempotent."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="%(message)s",
        force=True,
    )

    renderer: Any
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_logging.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run lint + typecheck**

Run: `uv run ruff check src tests && uv run mypy`
Expected: 0 issues.

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/logging.py tests/unit/test_logging.py
git commit -m "feat(logging): structured JSON logging with secret redaction"
```

---

### Chunk 1 closeout

**Acceptance criteria:**
- [ ] `uv sync` succeeds.
- [ ] `uv run pytest -v` reports all tests in this chunk passing (8 tests total: 3 config + 5 logging).
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] GreenMail smoke test in Task 1.2 succeeds.
- [ ] Git history contains 4 task commits with conventional-commit prefixes.

---

## Chunk 2: Foundation B — models, db, minimal app, CI

**Outcome of this chunk:** SQLAlchemy ORM matching the spec schema, FTS5 virtual table + sync triggers, WAL + busy-timeout, a minimum FastAPI app exposing `GET /healthz`, and CI green on a fresh push. After this chunk Chunks 3 and 4 may run in parallel.

### Task 2.1: SQLAlchemy ORM models

**Files:**
- Create: `src/driftnote/models.py`
- Create: `tests/unit/test_models.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_models.py`:

```python
"""Tests for SQLAlchemy ORM models — table names, columns, constraints."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect

from driftnote.models import Base, DiskState, Entry, IngestedMessage, JobRun, Media, PendingPrompt, Tag


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_all_tables_created(engine) -> None:
    expected = {
        "entries",
        "tags",
        "media",
        "ingested_messages",
        "pending_prompts",
        "job_runs",
        "disk_state",
    }
    insp = inspect(engine)
    assert set(insp.get_table_names()) >= expected


def test_entries_has_id_and_unique_date(engine) -> None:
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("entries")}
    assert {"id", "date", "mood", "body_text", "body_md", "created_at", "updated_at"} <= cols
    uniques = insp.get_unique_constraints("entries")
    assert any({c for c in u["column_names"]} == {"date"} for u in uniques)


def test_ingested_messages_has_imap_moved_default_zero(engine) -> None:
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("ingested_messages")}
    assert "imap_moved" in cols
    # SQLAlchemy reflects server_default; it should be '0'.
    default = cols["imap_moved"].get("default")
    assert default in ("0", 0, "'0'")


def test_models_constructible() -> None:
    Entry(
        date="2026-05-06",
        mood="💪",
        body_text="hi",
        body_md="hi",
        created_at="2026-05-06T21:00:00Z",
        updated_at="2026-05-06T21:00:00Z",
    )
    Tag(date="2026-05-06", tag="work")
    Media(date="2026-05-06", kind="photo", filename="a.jpg", ord=0)
    IngestedMessage(message_id="m1", date="2026-05-06", eml_path="raw/x.eml", ingested_at="t")
    PendingPrompt(date="2026-05-06", message_id="m2", sent_at="t")
    JobRun(job="imap_poll", started_at="t", status="running")
    DiskState(threshold_percent=80, crossed_at="t")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `src/driftnote/models.py`**

```python
"""SQLAlchemy ORM models matching the SQLite schema in the design spec.

The `entries` table uses an explicit INTEGER PRIMARY KEY `id` (with a UNIQUE
constraint on `date`) so that FTS5 can reference rows via `content_rowid='id'`.
This is a deliberate refinement of spec §2 — the spec's prose treats `date` as
the natural key, but FTS5 requires a true rowid alias. Foreign keys throughout
still reference `entries.date`, preserving the natural-key relationships.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("date", name="uq_entries_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    mood: Mapped[str | None] = mapped_column(String(16))
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (Index("idx_tags_tag", "tag"),)

    date: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("entries.date", ondelete="CASCADE"),
        primary_key=True,
    )
    tag: Mapped[str] = mapped_column(String(64), primary_key=True)


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (
        CheckConstraint("kind IN ('photo','video')", name="ck_media_kind"),
        Index("idx_media_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("entries.date", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class IngestedMessage(Base):
    __tablename__ = "ingested_messages"
    __table_args__ = (
        Index(
            "idx_ingested_imap_moved",
            "imap_moved",
            sqlite_where=text("imap_moved = 0"),
        ),
    )

    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    date: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("entries.date"),
        nullable=False,
    )
    eml_path: Mapped[str] = mapped_column(String(255), nullable=False)
    ingested_at: Mapped[str] = mapped_column(String(32), nullable=False)
    imap_moved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class PendingPrompt(Base):
    __tablename__ = "pending_prompts"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    sent_at: Mapped[str] = mapped_column(String(32), nullable=False)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (Index("idx_job_runs_job_started", "job", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[str] = mapped_column(String(32), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[str | None] = mapped_column(String(32))


class DiskState(Base):
    __tablename__ = "disk_state"

    threshold_percent: Mapped[int] = mapped_column(Integer, primary_key=True)
    crossed_at: Mapped[str] = mapped_column(String(32), nullable=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check src tests && uv run mypy`
Expected: 0 issues.

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/models.py tests/unit/test_models.py
git commit -m "feat(models): SQLAlchemy ORM matching spec schema"
```

---

### Task 2.2: Database engine, session factory, FTS5 setup

**Files:**
- Create: `src/driftnote/db.py`
- Create: `tests/unit/test_db.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_db.py`:

```python
"""Tests for DB engine, session, and FTS5 trigger setup."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from driftnote.db import init_db, make_engine, session_scope


def test_init_db_applies_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
    assert "entries" in names
    assert "entries_fts" in names


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    init_db(engine)  # second call must not raise


def test_wal_mode_enabled(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar_one()
    assert str(mode).lower() == "wal"


def test_fts_inserts_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with session_scope(engine) as session:
        session.execute(
            text(
                "INSERT INTO entries(date, body_text, body_md, created_at, updated_at) "
                "VALUES (:d, :t, :m, :c, :u)"
            ),
            {
                "d": "2026-05-06",
                "t": "the quick brown fox",
                "m": "the **quick** brown fox",
                "c": "2026-05-06T21:00:00Z",
                "u": "2026-05-06T21:00:00Z",
            },
        )
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT date FROM entries WHERE rowid IN "
                 "(SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'fox')")
        ).all()
    assert rows == [("2026-05-06",)]


def test_fts_updates_on_body_text_change(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with session_scope(engine) as session:
        session.execute(
            text(
                "INSERT INTO entries(date, body_text, body_md, created_at, updated_at) "
                "VALUES ('2026-05-06', 'cats are fine', 'cats are fine', 't', 't')"
            ),
        )
        session.execute(
            text("UPDATE entries SET body_text = 'dogs are fine' WHERE date = '2026-05-06'"),
        )
    with engine.connect() as conn:
        cats = conn.execute(
            text("SELECT date FROM entries WHERE rowid IN "
                 "(SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'cats')")
        ).all()
        dogs = conn.execute(
            text("SELECT date FROM entries WHERE rowid IN "
                 "(SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'dogs')")
        ).all()
    assert cats == []
    assert dogs == [("2026-05-06",)]


def test_session_scope_commits_on_success(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)
    with session_scope(engine) as session:
        session.execute(
            text("INSERT INTO disk_state(threshold_percent, crossed_at) VALUES (80, 't')"),
        )
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT threshold_percent FROM disk_state")).all()
    assert rows == [(80,)]


def test_session_scope_rolls_back_on_error(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite"
    engine = make_engine(db_path)
    init_db(engine)

    with pytest.raises(RuntimeError):
        with session_scope(engine) as session:
            session.execute(
                text("INSERT INTO disk_state(threshold_percent, crossed_at) VALUES (80, 't')"),
            )
            raise RuntimeError("boom")

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT threshold_percent FROM disk_state")).all()
    assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_db.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/db.py`**

```python
"""Database engine, session factory, schema init, and FTS5 trigger setup.

WAL mode + 5s busy-timeout makes concurrent writes from the host-side backup
script and the in-container app safe. FTS5 uses content_rowid='id' over
entries.body_text and is kept in sync via standard FTS5 triggers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from driftnote.models import Base

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    body_text,
    content='entries',
    content_rowid='id'
);
"""

_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
        INSERT INTO entries_fts(rowid, body_text) VALUES (new.id, new.body_text);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
        INSERT INTO entries_fts(entries_fts, rowid, body_text) VALUES('delete', old.id, old.body_text);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
        INSERT INTO entries_fts(entries_fts, rowid, body_text) VALUES('delete', old.id, old.body_text);
        INSERT INTO entries_fts(rowid, body_text) VALUES (new.id, new.body_text);
    END;
    """,
]


def make_engine(db_path: Path) -> Engine:
    """Create an Engine for the given file. WAL + foreign keys enabled per-connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"timeout": 5.0},  # busy-timeout in seconds
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    """Apply ORM schema, create FTS5 virtual table + triggers. Idempotent."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(_FTS_DDL))
        for ddl in _FTS_TRIGGERS:
            conn.execute(text(ddl))


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Context manager that yields a Session, commits on success, rolls back on error."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_db.py -v`
Expected: 7 passed.

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check src tests && uv run mypy`
Expected: 0 issues.

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/db.py tests/unit/test_db.py
git commit -m "feat(db): engine + session_scope + WAL + FTS5 triggers"
```

---

### Task 2.3: Minimal `app.py` with `/healthz`

**Files:**
- Create: `src/driftnote/app.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_healthz.py`

This task gives us a bootable container; full FastAPI wiring (routes, scheduler, lifespan) lands in Chunk 8.

- [ ] **Step 1: Write failing test**

`tests/integration/__init__.py` (empty), then `tests/integration/test_healthz.py`:

```python
"""Smoke test: /healthz returns 200."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok() -> None:
    """Smoke test: the minimal create_app() boots and /healthz returns 200.

    Chunk 2's create_app() does no config loading; Chunk 9 will expand it and
    re-add env-var setup to this test (or replace it with a fixture).
    """
    from driftnote.app import create_app

    app = create_app(skip_startup_jobs=True)
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_healthz.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement minimal `src/driftnote/app.py`**

```python
"""FastAPI app factory. Full wiring lands in Chunk 9; this minimum gives us /healthz.

Module is import-safe — no env vars or config loading at import time. The
Containerfile invokes `uvicorn --factory driftnote.app:create_app` so config
loading happens inside the factory, not at import. Chunk 9 expands the factory
to load Settings, init the DB, and start the scheduler.
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app(*, skip_startup_jobs: bool = False) -> FastAPI:
    """Create and configure the Driftnote FastAPI app.

    `skip_startup_jobs` is True in tests / when the harness only wants the HTTP
    surface. Full lifespan wiring (DB init, scheduler start) lands in Chunk 9.
    """
    app = FastAPI(title="Driftnote", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_healthz.py -v`
Expected: 1 passed.

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check src tests && uv run mypy`
Expected: 0 issues.

- [ ] **Step 6: Smoke-test container build**

Run:
```bash
podman --remote build -f Containerfile -t driftnote:smoke .
podman --remote run --rm -d --name driftnote-smoke -p 8000:8000 driftnote:smoke
for i in 1 2 3 4 5 6 7 8 9 10; do
    curl -sf http://localhost:8000/healthz && break
    sleep 1
done
podman --remote stop driftnote-smoke
podman --remote rmi driftnote:smoke
```

Expected: `{"status":"ok"}` printed; exit code 0. (No env vars required at this stage — Chunk 2's `create_app` does no config loading. Chunk 9 will reintroduce env-var requirements.)

- [ ] **Step 7: Commit**

```bash
git add src/driftnote/app.py tests/integration/__init__.py tests/integration/test_healthz.py
git commit -m "feat(app): minimal FastAPI factory with /healthz endpoint"
```

---

### Task 2.4: Pre-commit hooks + CI workflow

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `.github/workflows/ci.yml`
- Create: `.github/CODEOWNERS`

- [ ] **Step 1: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: local
    hooks:
      - id: pytest-fast
        name: pytest (unit, fast)
        entry: uv run pytest -q -m "not live and not slow" tests/unit
        language: system
        pass_filenames: false
        stages: [pre-commit]
```

- [ ] **Step 2: Create `.github/CODEOWNERS`**

```
* @maciej-makowski
```

- [ ] **Step 3: Create `.github/workflows/ci.yml`**

```yaml
name: CI
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "0.5.x"
          enable-cache: true

      - name: Install dependencies
        run: uv sync --frozen

      - name: Lint
        run: uv run ruff check src tests

      - name: Format check
        run: uv run ruff format --check src tests

      - name: Type check
        run: uv run mypy

      - name: Tests (excluding live)
        run: uv run pytest -m "not live" -v --cov=driftnote --cov-report=term-missing

  build-container:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - name: Build container (smoke)
        run: |
          docker build -f Containerfile -t driftnote:ci .
```

- [ ] **Step 4: Verify locally — pre-commit installs and runs**

Run:
```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Expected: ruff and pytest checks pass; exit 0.

- [ ] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml .github/workflows/ci.yml .github/CODEOWNERS
git commit -m "ci: pre-commit hooks and GitHub Actions for lint/types/tests"
```

---

### Chunk 2 closeout

**Acceptance criteria:**
- [ ] `uv run pytest -v` reports all tests in Chunks 1 + 2 passing (≥17 tests total).
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] `podman build -f Containerfile -t driftnote:smoke .` builds successfully.
- [ ] Running the built container responds to `GET /healthz` with `{"status":"ok"}`.
- [ ] `pre-commit run --all-files` is clean.
- [ ] CI workflow exists and lint + type + test jobs pass on a clean run.
- [ ] Git history contains 4 task commits in this chunk with conventional-commit prefixes.

**Hand-off to subsequent chunks:** Foundation is complete. Chunks 3 (filesystem + repository) and 4 (mail transport) can now be developed in parallel worktrees.

---

## Chunk 3: Filesystem (paths, markdown_io, locks)

**Outcome of this chunk:** A clean `filesystem/` module that knows how to compute paths, read/write `entry.md` (YAML frontmatter + body) atomically, and serialize per-date access via `fcntl.flock`. After this chunk Chunk 6 (ingestion) — together with Chunk 4 (repository) and Chunk 5 (mail transport) — can write entries to disk.

**Adds dependencies:** `pyyaml` (for YAML frontmatter; tomllib is stdlib but YAML is not).

### Task 3.1: Add YAML dep + `filesystem/layout.py`

**Files:**
- Modify: `pyproject.toml` (add `pyyaml`, `types-pyyaml`)
- Create: `src/driftnote/filesystem/__init__.py`
- Create: `src/driftnote/filesystem/layout.py`
- Create: `tests/unit/test_filesystem_layout.py`

- [ ] **Step 1: Add `pyyaml` to project dependencies and `types-pyyaml` to dev**

In `pyproject.toml`, add `"pyyaml>=6.0",` to `[project].dependencies`. Add `"types-pyyaml"` to `[dependency-groups].dev`. Run `uv sync` and commit `uv.lock` along with the change at the end of this task.

- [ ] **Step 2: Write failing test for path layout**

Create `tests/unit/test_filesystem_layout.py`:

```python
"""Tests for filesystem path layout helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from driftnote.filesystem.layout import (
    EntryPaths,
    entry_paths_for,
    parse_eml_received_at,
    raw_eml_filename,
)


def test_entry_paths_for_date(tmp_path: Path) -> None:
    paths = entry_paths_for(tmp_path, date(2026, 5, 6))
    assert isinstance(paths, EntryPaths)
    assert paths.dir == tmp_path / "entries" / "2026" / "05" / "06"
    assert paths.entry_md == paths.dir / "entry.md"
    assert paths.raw_dir == paths.dir / "raw"
    assert paths.originals_dir == paths.dir / "originals"
    assert paths.web_dir == paths.dir / "web"
    assert paths.thumbs_dir == paths.dir / "thumbs"


def test_raw_eml_filename_format() -> None:
    # 21:30:15 UTC on 2026-05-06
    from datetime import datetime, timezone
    received = datetime(2026, 5, 6, 21, 30, 15, tzinfo=timezone.utc)
    name = raw_eml_filename(received)
    assert name == "2026-05-06T21-30-15Z.eml"


def test_raw_eml_filename_is_filesystem_safe() -> None:
    from datetime import datetime, timezone
    name = raw_eml_filename(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    forbidden = set(":/\\<>|?*")
    assert not (set(name) & forbidden)


def test_parse_eml_received_at_round_trip() -> None:
    from datetime import datetime, timezone
    original = datetime(2026, 5, 6, 21, 30, 15, tzinfo=timezone.utc)
    name = raw_eml_filename(original)
    parsed = parse_eml_received_at(name)
    assert parsed == original


def test_parse_eml_received_at_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        parse_eml_received_at("not-a-date.eml")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_filesystem_layout.py -v`
Expected: FAIL with import error.

- [ ] **Step 4: Implement `src/driftnote/filesystem/__init__.py`** (empty package marker)

```python
"""Filesystem layer: paths, markdown I/O, locks."""
```

- [ ] **Step 5: Implement `src/driftnote/filesystem/layout.py`**

```python
"""Path layout helpers for the entries tree.

Single source of truth for where things live on disk so the rest of the code
never hard-codes path arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

_RAW_FILENAME_FMT = "%Y-%m-%dT%H-%M-%SZ"


@dataclass(frozen=True)
class EntryPaths:
    """All filesystem paths for one day's entry."""

    dir: Path
    entry_md: Path
    raw_dir: Path
    originals_dir: Path
    web_dir: Path
    thumbs_dir: Path


def entry_paths_for(data_root: Path, d: date) -> EntryPaths:
    """Compute (without creating) the path bundle for a given date.

    `data_root` is the parent of `entries/` (i.e. typically `/var/driftnote/data`).
    """
    base = data_root / "entries" / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"
    return EntryPaths(
        dir=base,
        entry_md=base / "entry.md",
        raw_dir=base / "raw",
        originals_dir=base / "originals",
        web_dir=base / "web",
        thumbs_dir=base / "thumbs",
    )


def raw_eml_filename(received_at: datetime) -> str:
    """Filesystem-safe filename for a raw .eml message keyed on its received-at UTC time."""
    if received_at.tzinfo is None:
        raise ValueError("received_at must be timezone-aware (use UTC)")
    utc = received_at.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime(_RAW_FILENAME_FMT) + ".eml"


def parse_eml_received_at(filename: str) -> datetime:
    """Inverse of raw_eml_filename. Raises ValueError if the name doesn't fit."""
    if not filename.endswith(".eml"):
        raise ValueError(f"not an .eml filename: {filename!r}")
    stem = filename[:-len(".eml")]
    try:
        dt = datetime.strptime(stem, _RAW_FILENAME_FMT)
    except ValueError as exc:
        raise ValueError(f"cannot parse received-at from {filename!r}: {exc}") from exc
    return dt.replace(tzinfo=timezone.utc)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_filesystem_layout.py -v`
Expected: 5 passed.

- [ ] **Step 7: Lint + typecheck + commit**

Run: `uv run ruff check src tests && uv run mypy`
Expected: clean.

```bash
git add pyproject.toml uv.lock src/driftnote/filesystem/ tests/unit/test_filesystem_layout.py
git commit -m "feat(filesystem): path layout helpers and raw .eml filename codec"
```

---

### Task 3.2: `filesystem/markdown_io.py`

**Files:**
- Create: `src/driftnote/filesystem/markdown_io.py`
- Create: `tests/unit/test_filesystem_markdown_io.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_filesystem_markdown_io.py`:

```python
"""Tests for entry.md read/write — YAML frontmatter + body."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest
from hypothesis import given, settings, strategies as st

from driftnote.filesystem.markdown_io import (
    EntryDocument,
    MalformedEntryError,
    PhotoRef,
    VideoRef,
    read_entry,
    write_entry,
)


def _doc(**overrides) -> EntryDocument:
    base = EntryDocument(
        date=date(2026, 5, 6),
        mood="💪",
        tags=["work", "cooking"],
        photos=[PhotoRef(filename="IMG_4521.heic", caption="")],
        videos=[VideoRef(filename="VID_4522.mov")],
        created_at="2026-05-06T21:30:15Z",
        updated_at="2026-05-06T21:30:15Z",
        sources=["raw/2026-05-06T21-30-15Z.eml"],
        body="Long day at work. #work\n",
    )
    return base.model_copy(update=overrides)


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    doc = _doc()
    write_entry(path, doc)
    loaded = read_entry(path)
    assert loaded == doc


def test_write_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "deeper" / "entry.md"
    write_entry(path, _doc())
    assert path.exists()


def test_write_is_atomic(tmp_path: Path) -> None:
    """write_entry replaces atomically (no half-written file visible)."""
    path = tmp_path / "entry.md"
    write_entry(path, _doc(body="first"))
    write_entry(path, _doc(body="second"))
    text = path.read_text()
    assert "second" in text
    # No leftover .tmp from os.replace pattern
    assert list(path.parent.glob("*.tmp")) == []


def test_read_handles_no_mood(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    write_entry(path, _doc(mood=None))
    loaded = read_entry(path)
    assert loaded.mood is None


def test_read_handles_empty_tags_and_media(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    write_entry(path, _doc(tags=[], photos=[], videos=[]))
    loaded = read_entry(path)
    assert loaded.tags == []
    assert loaded.photos == []
    assert loaded.videos == []


def test_read_rejects_missing_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    path.write_text("just a body, no frontmatter\n")
    with pytest.raises(MalformedEntryError):
        read_entry(path)


def test_read_rejects_unterminated_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    path.write_text("---\ndate: 2026-05-06\nbody never ends\n")
    with pytest.raises(MalformedEntryError):
        read_entry(path)


def test_read_rejects_bad_yaml(tmp_path: Path) -> None:
    path = tmp_path / "entry.md"
    path.write_text("---\nfoo: : :\n---\nbody\n")
    with pytest.raises(MalformedEntryError):
        read_entry(path)


def test_body_separator_preserved_for_multi_section_entries(tmp_path: Path) -> None:
    """Multi-source entries put `---` between body sections; this is part of the
    body text (not a frontmatter delimiter) and must round-trip."""
    body = "First reply.\n\n---\n\nAfterthought.\n"
    path = tmp_path / "entry.md"
    write_entry(path, _doc(body=body))
    assert read_entry(path).body == body


@given(
    body=st.text(
        alphabet=st.characters(
            blacklist_categories=("Cs",),  # exclude surrogates
            blacklist_characters="\x00",
        ),
        min_size=0,
        max_size=200,
    ),
    tags=st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=20),
        max_size=10,
    ),
    mood=st.one_of(st.none(), st.sampled_from(["💪", "🌧️", "☕", "🎉", "😴"])),
)
@settings(max_examples=30, deadline=None)
def test_round_trip_property(tmp_path_factory, body: str, tags: list[str], mood: str | None) -> None:
    path = tmp_path_factory.mktemp("entry") / "entry.md"
    doc = _doc(body=body, tags=tags, mood=mood)
    write_entry(path, doc)
    loaded = read_entry(path)
    assert loaded == doc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_filesystem_markdown_io.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement `src/driftnote/filesystem/markdown_io.py`**

```python
"""Read and write `entry.md` — YAML frontmatter + markdown body.

The frontmatter is parsed as YAML via PyYAML. Writes are atomic via
`os.replace`. Multi-section bodies (when several email replies feed into the
same date) keep `---` as an in-body separator; only the *first* `\\n---\\n`
after the opening one is the frontmatter terminator.

I/O uses `newline=""` to disable Python's universal-newline translation so
bodies round-trip byte-for-byte regardless of any embedded `\\r` or other
line-break characters. Property tests rely on this.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class MalformedEntryError(ValueError):
    """Raised when an entry.md file cannot be parsed as frontmatter+body."""


class PhotoRef(BaseModel):
    filename: str
    caption: str = ""


class VideoRef(BaseModel):
    filename: str
    caption: str = ""


class EntryDocument(BaseModel):
    date: date
    mood: str | None = None
    tags: list[str] = Field(default_factory=list)
    photos: list[PhotoRef] = Field(default_factory=list)
    videos: list[VideoRef] = Field(default_factory=list)
    created_at: str
    updated_at: str
    sources: list[str] = Field(default_factory=list)
    body: str = ""


def read_entry(path: Path) -> EntryDocument:
    """Parse entry.md at `path` into an EntryDocument. Raises MalformedEntryError on bad input."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    if not text.startswith("---\n"):
        raise MalformedEntryError(f"{path}: missing opening frontmatter delimiter")

    rest = text[len("---\n"):]
    end_idx = rest.find("\n---\n")
    if end_idx == -1:
        # Could also be terminated by trailing ---\n with no body (hand-edited files only;
        # write_entry() never produces this shape).
        if rest.endswith("\n---"):
            fm_text, body = rest[:-len("\n---")], ""
        else:
            raise MalformedEntryError(f"{path}: unterminated frontmatter")
    else:
        fm_text = rest[:end_idx]
        body = rest[end_idx + len("\n---\n"):]

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise MalformedEntryError(f"{path}: invalid YAML frontmatter: {exc}") from exc

    if not isinstance(fm, dict):
        raise MalformedEntryError(f"{path}: frontmatter is not a mapping")

    fm["body"] = body
    try:
        return EntryDocument.model_validate(fm)
    except Exception as exc:  # pydantic.ValidationError is the expected subclass
        raise MalformedEntryError(f"{path}: invalid entry: {exc}") from exc


def write_entry(path: Path, doc: EntryDocument) -> None:
    """Atomically write `doc` to `path`. Creates parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_dict = doc.model_dump(mode="json", exclude={"body"})
    fm_text = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True).rstrip()
    rendered = f"---\n{fm_text}\n---\n{doc.body}"

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        fh.write(rendered)
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_filesystem_markdown_io.py -v`
Expected: 9 tests + 1 hypothesis test passing.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/filesystem/markdown_io.py tests/unit/test_filesystem_markdown_io.py
git commit -m "feat(filesystem): atomic YAML-frontmatter entry.md read/write"
```

---

### Task 3.3: `filesystem/locks.py`

**Files:**
- Create: `src/driftnote/filesystem/locks.py`
- Create: `tests/unit/test_filesystem_locks.py`

Per-date `fcntl.flock` so two concurrent ingestions for the same date serialize.

- [ ] **Step 1: Write failing tests**

```python
"""Tests for per-date file locks."""

from __future__ import annotations

import multiprocessing as mp
import time
from datetime import date
from pathlib import Path

from driftnote.filesystem.locks import entry_lock


def _holder(data_root_str: str, hold_seconds: float, started_at: list, finished_at: list) -> None:
    from datetime import date as _date
    from driftnote.filesystem.locks import entry_lock as _lock
    with _lock(Path(data_root_str), _date(2026, 5, 6)):
        started_at.append(time.monotonic())
        time.sleep(hold_seconds)
        finished_at.append(time.monotonic())


def test_entry_lock_serializes_concurrent_holders(tmp_path: Path) -> None:
    """Two processes holding the same date's lock must not overlap."""
    mgr = mp.Manager()
    started = mgr.list()
    finished = mgr.list()
    p1 = mp.Process(target=_holder, args=(str(tmp_path), 0.3, started, finished))
    p2 = mp.Process(target=_holder, args=(str(tmp_path), 0.3, started, finished))
    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)
    assert p1.exitcode == 0 and p2.exitcode == 0

    # The second holder's start must be after the first holder's finish.
    starts = sorted(started)
    finishes = sorted(finished)
    assert starts[1] >= finishes[0] - 0.05  # small slack for timer jitter


def test_entry_lock_releases_on_exception(tmp_path: Path) -> None:
    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        with entry_lock(tmp_path, date(2026, 5, 6)):
            raise RuntimeError("boom")
    # If the lock leaked, the next acquisition would block forever.
    with entry_lock(tmp_path, date(2026, 5, 6)):
        pass


def test_entry_lock_creates_lock_file(tmp_path: Path) -> None:
    with entry_lock(tmp_path, date(2026, 5, 6)):
        # Lock file should live under data_root/locks/ keyed by date.
        lock_files = list((tmp_path / "locks").glob("2026-05-06.lock"))
        assert lock_files
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_filesystem_locks.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/filesystem/locks.py`**

```python
"""Per-date file locks via fcntl.flock.

A lock file lives under `data_root/locks/YYYY-MM-DD.lock`. Acquiring an
`entry_lock(data_root, date)` blocks until any other holder releases.

Spec §6 describes "per-date `fcntl.flock` on entry directory"; we instead
keep all lock files under a sibling `locks/` directory so the lock can be
acquired before the entry directory exists (first-time ingestion). The
serialization guarantee is identical.
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path


@contextmanager
def entry_lock(data_root: Path, d: date) -> Iterator[None]:
    """Hold an exclusive lock on the per-date lock file. Blocks until acquired."""
    lock_dir = data_root / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{d.isoformat()}.lock"
    # Append mode creates the file if absent; we never read/write its contents,
    # we just need an fd to flock on.
    with lock_path.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_filesystem_locks.py -v`
Expected: 3 passed (the multiprocessing test takes ~0.6s).

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/filesystem/locks.py tests/unit/test_filesystem_locks.py
git commit -m "feat(filesystem): per-date fcntl.flock for serializing ingestion"
```

---

### Chunk 3 closeout

**Acceptance criteria:**
- [ ] All Chunks 1–3 tests pass: `uv run pytest -v` (≥25 tests).
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] Filesystem layer reads/writes entry.md round-trips via property tests.
- [ ] 3 task commits in this chunk with conventional-commit prefixes.

**Hand-off:** Filesystem layer is ready. Chunk 4 (repository) and Chunk 5 (mail transport) can be developed in parallel worktrees from this point.

---

## Chunk 4: Repository

**Outcome of this chunk:** A `repository/` module providing the CRUD + query API the rest of the codebase will use to talk to SQLite. ORM types do not leak above this layer — every public function returns Pydantic records. Covers entries+tags, media, job_runs, ingested_messages, pending_prompts, and disk_state.

### Task 4.1: `repository/entries.py` — entry + tag CRUD + queries

**Files:**
- Create: `src/driftnote/repository/__init__.py`
- Create: `src/driftnote/repository/entries.py`
- Create: `tests/unit/test_repository_entries.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for the entries repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.entries import (
    EntryRecord,
    count_entries_in_range,
    delete_entry,
    get_entry,
    list_entries_by_month,
    list_entries_by_tag,
    list_entries_in_range,
    replace_tags,
    search_fts,
    tag_frequencies_in_range,
    upsert_entry,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def _record(date: str = "2026-05-06", **overrides) -> EntryRecord:
    base = EntryRecord(
        date=date,
        mood="💪",
        body_text="cracked the migration bug today",
        body_md="cracked the migration bug today #work",
        created_at="2026-05-06T21:30:15Z",
        updated_at="2026-05-06T21:30:15Z",
    )
    return base.model_copy(update=overrides)


def test_upsert_inserts_new_entry(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
    with session_scope(engine) as session:
        got = get_entry(session, "2026-05-06")
    assert got is not None
    assert got.mood == "💪"
    assert got.body_text == "cracked the migration bug today"


def test_upsert_updates_existing_entry(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(mood="💪", body_text="v1", body_md="v1"))
        upsert_entry(session, _record(mood="🎉", body_text="v2", body_md="v2 #celebrate"))
    with session_scope(engine) as session:
        got = get_entry(session, "2026-05-06")
    assert got is not None
    assert got.mood == "🎉"
    assert got.body_text == "v2"


def test_replace_tags_overwrites_previous(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
        replace_tags(session, "2026-05-06", ["work", "cooking"])
        replace_tags(session, "2026-05-06", ["work", "rest"])
    with session_scope(engine) as session:
        entries = list_entries_by_tag(session, "rest")
        cooking = list_entries_by_tag(session, "cooking")
    assert [e.date for e in entries] == ["2026-05-06"]
    assert cooking == []


def test_replace_tags_lowercases(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
        replace_tags(session, "2026-05-06", ["Work", "COOKING"])
    with session_scope(engine) as session:
        ents_work = list_entries_by_tag(session, "work")
        ents_cooking = list_entries_by_tag(session, "cooking")
    assert ents_work and ents_cooking


def test_list_entries_by_month_orders_by_date(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-06"))
        upsert_entry(session, _record(date="2026-05-01"))
        upsert_entry(session, _record(date="2026-04-30"))
    with session_scope(engine) as session:
        may = list_entries_by_month(session, 2026, 5)
    assert [e.date for e in may] == ["2026-05-01", "2026-05-06"]


def test_count_and_tag_frequencies_in_range(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-01"))
        replace_tags(session, "2026-05-01", ["work", "cooking"])
        upsert_entry(session, _record(date="2026-05-02"))
        replace_tags(session, "2026-05-02", ["work"])
        upsert_entry(session, _record(date="2026-04-30"))
        replace_tags(session, "2026-04-30", ["cooking"])
    with session_scope(engine) as session:
        n = count_entries_in_range(session, "2026-05-01", "2026-05-31")
        freq = tag_frequencies_in_range(session, "2026-05-01", "2026-05-31")
    assert n == 2
    assert freq == {"work": 2, "cooking": 1}


def test_search_fts_matches_body(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-01", body_text="risotto night was great"))
        upsert_entry(session, _record(date="2026-05-02", body_text="rainy walk in the park"))
    with session_scope(engine) as session:
        hits = search_fts(session, "risotto")
    assert [e.date for e in hits] == ["2026-05-01"]


def test_delete_entry_cascades_tags(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record())
        replace_tags(session, "2026-05-06", ["work"])
        delete_entry(session, "2026-05-06")
    with session_scope(engine) as session:
        assert get_entry(session, "2026-05-06") is None
        assert list_entries_by_tag(session, "work") == []


def test_list_entries_in_range_inclusive(engine: Engine) -> None:
    with session_scope(engine) as session:
        for d in ("2026-05-01", "2026-05-02", "2026-05-03"):
            upsert_entry(session, _record(date=d))
    with session_scope(engine) as session:
        rs = list_entries_in_range(session, "2026-05-02", "2026-05-03")
    assert [e.date for e in rs] == ["2026-05-02", "2026-05-03"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repository_entries.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/repository/__init__.py`** (empty)

```python
"""Repository: SQL access. ORM types do not leak above this layer."""
```

- [ ] **Step 4: Implement `src/driftnote/repository/entries.py`**

```python
"""CRUD and queries for entries + tags. ORM types do not leak above this layer.

All public functions take an open SQLAlchemy `Session` and return Pydantic
records (`EntryRecord`) — never `Entry` ORM instances.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from driftnote.models import Entry, Tag


class EntryRecord(BaseModel):
    date: str
    mood: str | None = None
    body_text: str
    body_md: str
    created_at: str
    updated_at: str


def _to_record(e: Entry) -> EntryRecord:
    return EntryRecord(
        date=e.date,
        mood=e.mood,
        body_text=e.body_text,
        body_md=e.body_md,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def upsert_entry(session: Session, record: EntryRecord) -> None:
    """Insert-or-update by primary key `date`. Idempotent."""
    stmt = (
        sqlite_insert(Entry)
        .values(
            date=record.date,
            mood=record.mood,
            body_text=record.body_text,
            body_md=record.body_md,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        .on_conflict_do_update(
            index_elements=["date"],
            set_={
                "mood": record.mood,
                "body_text": record.body_text,
                "body_md": record.body_md,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            },
        )
    )
    session.execute(stmt)


def get_entry(session: Session, date: str) -> EntryRecord | None:
    e = session.scalar(select(Entry).where(Entry.date == date))
    return _to_record(e) if e else None


def list_entries_by_month(session: Session, year: int, month: int) -> list[EntryRecord]:
    prefix = f"{year:04d}-{month:02d}-"
    stmt = select(Entry).where(Entry.date.like(f"{prefix}%")).order_by(Entry.date)
    return [_to_record(e) for e in session.scalars(stmt)]


def list_entries_in_range(session: Session, start: str, end: str) -> list[EntryRecord]:
    stmt = select(Entry).where(Entry.date.between(start, end)).order_by(Entry.date)
    return [_to_record(e) for e in session.scalars(stmt)]


def list_entries_by_tag(session: Session, tag: str) -> list[EntryRecord]:
    stmt = (
        select(Entry)
        .join(Tag, Tag.date == Entry.date)
        .where(Tag.tag == tag.lower())
        .order_by(Entry.date.desc())
    )
    return [_to_record(e) for e in session.scalars(stmt)]


def count_entries_in_range(session: Session, start: str, end: str) -> int:
    from sqlalchemy import func
    stmt = select(func.count()).select_from(Entry).where(Entry.date.between(start, end))
    return session.scalar(stmt) or 0


def tag_frequencies_in_range(session: Session, start: str, end: str) -> dict[str, int]:
    """Tag.date is the FK to entries.date, so we don't need to join Entry."""
    stmt = select(Tag.tag).where(Tag.date.between(start, end))
    counter: Counter[str] = Counter(session.scalars(stmt))
    return dict(counter)


def replace_tags(session: Session, date: str, tags: list[str]) -> None:
    """Replace all tags for `date` with the given list (lowercased, deduplicated)."""
    session.execute(delete(Tag).where(Tag.date == date))
    seen: set[str] = set()
    for raw in tags:
        normalized = raw.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        session.add(Tag(date=date, tag=normalized))


def search_fts(session: Session, query: str) -> list[EntryRecord]:
    """Full-text search via FTS5. Returns most-recently-dated matches first."""
    rows = session.execute(
        text(
            "SELECT date FROM entries "
            "WHERE id IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH :q) "
            "ORDER BY date DESC"
        ),
        {"q": query},
    ).all()
    if not rows:
        return []
    dates = [r[0] for r in rows]
    stmt = select(Entry).where(Entry.date.in_(dates)).order_by(Entry.date.desc())
    return [_to_record(e) for e in session.scalars(stmt)]


def delete_entry(session: Session, date: str) -> None:
    session.execute(delete(Entry).where(Entry.date == date))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repository_entries.py -v`
Expected: 9 passed.

- [ ] **Step 6: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/repository/__init__.py src/driftnote/repository/entries.py tests/unit/test_repository_entries.py
git commit -m "feat(repository): entries + tags CRUD with FTS search"
```

---

### Task 4.2: `repository/media.py`

**Files:**
- Create: `src/driftnote/repository/media.py`
- Create: `tests/unit/test_repository_media.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for the media repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.entries import EntryRecord, upsert_entry
from driftnote.repository.media import MediaInput, list_media, replace_media


@pytest.fixture
def engine_with_entry(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-05-06",
                mood="💪",
                body_text="hi",
                body_md="hi",
                created_at="t",
                updated_at="t",
            ),
        )
    return eng


def test_replace_media_inserts_in_order(engine_with_entry: Engine) -> None:
    eng = engine_with_entry
    with session_scope(eng) as session:
        replace_media(
            session,
            "2026-05-06",
            [
                MediaInput(kind="photo", filename="a.heic"),
                MediaInput(kind="photo", filename="b.jpg"),
                MediaInput(kind="video", filename="v.mov", caption="walk"),
            ],
        )
    with session_scope(eng) as session:
        items = list_media(session, "2026-05-06")
    assert [(m.ord, m.kind, m.filename) for m in items] == [
        (0, "photo", "a.heic"),
        (1, "photo", "b.jpg"),
        (2, "video", "v.mov"),
    ]
    assert items[2].caption == "walk"


def test_replace_media_overwrites_previous(engine_with_entry: Engine) -> None:
    eng = engine_with_entry
    with session_scope(eng) as session:
        replace_media(session, "2026-05-06", [MediaInput(kind="photo", filename="old.heic")])
        replace_media(session, "2026-05-06", [MediaInput(kind="photo", filename="new.heic")])
    with session_scope(eng) as session:
        items = list_media(session, "2026-05-06")
    assert [m.filename for m in items] == ["new.heic"]


def test_list_media_for_unknown_date_is_empty(engine_with_entry: Engine) -> None:
    with session_scope(engine_with_entry) as session:
        assert list_media(session, "2099-01-01") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repository_media.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `src/driftnote/repository/media.py`**

```python
"""Media (photo/video) row management. One row per media file per entry, with display order."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from driftnote.models import Media


class MediaInput(BaseModel):
    kind: Literal["photo", "video"]
    filename: str
    caption: str = ""


class MediaRecord(BaseModel):
    date: str
    kind: Literal["photo", "video"]
    filename: str
    ord: int
    caption: str


def _to_record(m: Media) -> MediaRecord:
    return MediaRecord(
        date=m.date,
        kind=m.kind,  # type: ignore[arg-type]
        filename=m.filename,
        ord=m.ord,
        caption=m.caption,
    )


def replace_media(session: Session, date: str, items: list[MediaInput]) -> None:
    """Drop and re-insert all media rows for `date` in the given order."""
    session.execute(delete(Media).where(Media.date == date))
    for ord_, item in enumerate(items):
        session.add(
            Media(
                date=date,
                kind=item.kind,
                filename=item.filename,
                ord=ord_,
                caption=item.caption,
            )
        )


def list_media(session: Session, date: str) -> list[MediaRecord]:
    stmt = select(Media).where(Media.date == date).order_by(Media.ord)
    return [_to_record(m) for m in session.scalars(stmt)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repository_media.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/repository/media.py tests/unit/test_repository_media.py
git commit -m "feat(repository): media row management"
```

---

### Task 4.3: `repository/jobs.py` — job_runs + alert dedup helpers

**Files:**
- Create: `src/driftnote/repository/jobs.py`
- Create: `tests/unit/test_repository_jobs.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for the job_runs repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import (
    JobRunRecord,
    acknowledge_run,
    finish_job_run,
    last_run,
    last_successful_run,
    recent_alerts_of_kind,
    recent_failures,
    record_job_run,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def test_record_then_finish_run(engine: Engine) -> None:
    with session_scope(engine) as session:
        run_id = record_job_run(session, job="imap_poll", started_at="2026-05-06T21:00:00Z")
    with session_scope(engine) as session:
        finish_job_run(
            session,
            run_id=run_id,
            finished_at="2026-05-06T21:00:05Z",
            status="ok",
            detail="ingested 1",
        )
    with session_scope(engine) as session:
        latest = last_run(session, "imap_poll")
    assert latest is not None
    assert latest.status == "ok"
    assert latest.detail == "ingested 1"


def test_last_successful_run_skips_errors(engine: Engine) -> None:
    with session_scope(engine) as session:
        ok_id = record_job_run(session, job="imap_poll", started_at="2026-05-06T20:00:00Z")
        finish_job_run(session, run_id=ok_id, finished_at="2026-05-06T20:00:01Z", status="ok")
        err_id = record_job_run(session, job="imap_poll", started_at="2026-05-06T21:00:00Z")
        finish_job_run(
            session,
            run_id=err_id,
            finished_at="2026-05-06T21:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    with session_scope(engine) as session:
        ok = last_successful_run(session, "imap_poll")
        any_run = last_run(session, "imap_poll")
    assert ok is not None and ok.status == "ok"
    assert any_run is not None and any_run.status == "error"


def test_recent_failures_within_days(engine: Engine) -> None:
    with session_scope(engine) as session:
        old = record_job_run(session, job="backup", started_at="2026-04-01T00:00:00Z")
        finish_job_run(session, run_id=old, finished_at="2026-04-01T00:00:01Z", status="error")
        new = record_job_run(session, job="backup", started_at="2026-05-05T00:00:00Z")
        finish_job_run(session, run_id=new, finished_at="2026-05-05T00:00:01Z", status="error")
    with session_scope(engine) as session:
        within_7 = recent_failures(session, now="2026-05-06T00:00:00Z", days=7)
    assert [r.id for r in within_7] == [new]


def test_recent_alerts_of_kind_for_dedup(engine: Engine) -> None:
    with session_scope(engine) as session:
        a = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(
            session,
            run_id=a,
            finished_at="2026-05-06T08:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    with session_scope(engine) as session:
        in_24h = recent_alerts_of_kind(
            session,
            error_kind="imap_auth",
            now="2026-05-06T20:00:00Z",
            hours=24,
        )
        old = recent_alerts_of_kind(
            session,
            error_kind="imap_auth",
            now="2026-05-08T20:00:00Z",
            hours=24,
        )
    assert len(in_24h) == 1
    assert old == []


def test_acknowledge_run(engine: Engine) -> None:
    with session_scope(engine) as session:
        a = record_job_run(session, job="imap_poll", started_at="t")
        finish_job_run(session, run_id=a, finished_at="t", status="error")
    with session_scope(engine) as session:
        acknowledge_run(session, run_id=a, at="2026-05-06T22:00:00Z")
    with session_scope(engine) as session:
        unack = recent_failures(session, now="2026-05-06T23:00:00Z", days=7, only_unacknowledged=True)
    assert unack == []


def test_record_returns_running_record(engine: Engine) -> None:
    with session_scope(engine) as session:
        run_id = record_job_run(session, job="imap_poll", started_at="t")
        latest = last_run(session, "imap_poll")
    assert latest is not None
    assert latest.id == run_id
    assert latest.status == "running"
    assert isinstance(latest, JobRunRecord)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repository_jobs.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `src/driftnote/repository/jobs.py`**

```python
"""job_runs CRUD + helpers used by the scheduler runner and admin/banner code."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from driftnote.models import JobRun

JobName = Literal[
    "daily_prompt",
    "imap_poll",
    "digest_weekly",
    "digest_monthly",
    "digest_yearly",
    "backup",
    "disk_check",
]
RunStatus = Literal["running", "ok", "warn", "error"]


class JobRunRecord(BaseModel):
    id: int
    job: str
    started_at: str
    finished_at: str | None = None
    status: str
    detail: str | None = None
    error_kind: str | None = None
    error_message: str | None = None
    acknowledged_at: str | None = None


def _to_record(r: JobRun) -> JobRunRecord:
    return JobRunRecord(
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


def record_job_run(session: Session, *, job: str, started_at: str) -> int:
    row = JobRun(job=job, started_at=started_at, status="running")
    session.add(row)
    session.flush()
    return row.id


def finish_job_run(
    session: Session,
    *,
    run_id: int,
    finished_at: str,
    status: RunStatus,
    detail: str | None = None,
    error_kind: str | None = None,
    error_message: str | None = None,
) -> None:
    session.execute(
        update(JobRun)
        .where(JobRun.id == run_id)
        .values(
            finished_at=finished_at,
            status=status,
            detail=detail,
            error_kind=error_kind,
            error_message=error_message,
        )
    )


def acknowledge_run(session: Session, *, run_id: int, at: str) -> None:
    session.execute(update(JobRun).where(JobRun.id == run_id).values(acknowledged_at=at))


def last_run(session: Session, job: str) -> JobRunRecord | None:
    stmt = select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(1)
    r = session.scalar(stmt)
    return _to_record(r) if r else None


def last_successful_run(session: Session, job: str) -> JobRunRecord | None:
    stmt = (
        select(JobRun)
        .where(JobRun.job == job, JobRun.status == "ok")
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    r = session.scalar(stmt)
    return _to_record(r) if r else None


def recent_failures(
    session: Session,
    *,
    now: str,
    days: int = 7,
    only_unacknowledged: bool = False,
) -> list[JobRunRecord]:
    """Return error/warn rows started within `days` of `now`, newest first."""
    cutoff = _shift_iso(now, days_delta=-days)
    stmt = (
        select(JobRun)
        .where(JobRun.status.in_(["error", "warn"]))
        .where(JobRun.started_at >= cutoff)
        .order_by(JobRun.started_at.desc())
    )
    if only_unacknowledged:
        stmt = stmt.where(JobRun.acknowledged_at.is_(None))
    return [_to_record(r) for r in session.scalars(stmt)]


def recent_alerts_of_kind(
    session: Session,
    *,
    error_kind: str,
    now: str,
    hours: int = 24,
) -> list[JobRunRecord]:
    cutoff = _shift_iso(now, hours_delta=-hours)
    stmt = (
        select(JobRun)
        .where(JobRun.error_kind == error_kind)
        .where(JobRun.started_at >= cutoff)
        .order_by(JobRun.started_at.desc())
    )
    return [_to_record(r) for r in session.scalars(stmt)]


def _shift_iso(iso: str, *, days_delta: int = 0, hours_delta: int = 0) -> str:
    """Return iso shifted by the given delta. Centralized so callers don't reimplement parsing."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    out = dt + timedelta(days=days_delta, hours=hours_delta)
    return out.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repository_jobs.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/repository/jobs.py tests/unit/test_repository_jobs.py
git commit -m "feat(repository): job_runs CRUD with alert dedup helpers"
```

---

### Task 4.4: `repository/ingested.py` — ingested_messages + pending_prompts + disk_state

**Files:**
- Create: `src/driftnote/repository/ingested.py`
- Create: `tests/unit/test_repository_ingested.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for ingested_messages, pending_prompts, and disk_state repositories."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.entries import EntryRecord, upsert_entry
from driftnote.repository.ingested import (
    PendingPromptRecord,
    clear_threshold_crossed,
    find_prompt_by_message_id,
    get_ingested,
    get_threshold_crossed_at,
    is_ingested,
    mark_imap_moved,
    pending_imap_moves,
    record_ingested,
    record_pending_prompt,
    record_threshold_crossed,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(
            session,
            EntryRecord(
                date="2026-05-06",
                mood=None,
                body_text="x",
                body_md="x",
                created_at="t",
                updated_at="t",
            ),
        )
    return eng


def test_ingested_round_trip(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_ingested(
            session,
            message_id="<m1@gmail>",
            date="2026-05-06",
            eml_path="raw/2026-05-06T21-30-15Z.eml",
            ingested_at="2026-05-06T21:30:20Z",
        )
    with session_scope(engine) as session:
        assert is_ingested(session, "<m1@gmail>")
        rec = get_ingested(session, "<m1@gmail>")
    assert rec is not None
    assert rec.message_id == "<m1@gmail>"
    assert rec.imap_moved == 0


def test_mark_imap_moved_and_pending_query(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_ingested(
            session,
            message_id="<m1@gmail>",
            date="2026-05-06",
            eml_path="raw/x.eml",
            ingested_at="t",
        )
        record_ingested(
            session,
            message_id="<m2@gmail>",
            date="2026-05-06",
            eml_path="raw/y.eml",
            ingested_at="t",
        )
        mark_imap_moved(session, "<m1@gmail>")
    with session_scope(engine) as session:
        pending = pending_imap_moves(session)
    assert {r.message_id for r in pending} == {"<m2@gmail>"}


def test_record_pending_prompt_and_lookup(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="2026-05-06T21:00:00Z",
        )
    with session_scope(engine) as session:
        rec = find_prompt_by_message_id(session, "<prompt-2026-05-06@driftnote>")
    assert isinstance(rec, PendingPromptRecord)
    assert rec.date == "2026-05-06"


def test_disk_state_threshold_lifecycle(engine: Engine) -> None:
    with session_scope(engine) as session:
        assert get_threshold_crossed_at(session, 80) is None
        record_threshold_crossed(session, threshold=80, at="2026-05-06T03:00:00Z")
    with session_scope(engine) as session:
        assert get_threshold_crossed_at(session, 80) == "2026-05-06T03:00:00Z"
    with session_scope(engine) as session:
        clear_threshold_crossed(session, 80)
    with session_scope(engine) as session:
        assert get_threshold_crossed_at(session, 80) is None


def test_pending_prompt_unique_message_id(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_pending_prompt(session, date="2026-05-06", message_id="<m@x>", sent_at="t")
    with session_scope(engine) as session:
        # Re-recording the same date with the same message_id is an upsert (idempotent on the date PK).
        record_pending_prompt(session, date="2026-05-06", message_id="<m@x>", sent_at="t2")
    with session_scope(engine) as session:
        rec = find_prompt_by_message_id(session, "<m@x>")
    assert rec is not None
    assert rec.sent_at == "t2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repository_ingested.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `src/driftnote/repository/ingested.py`**

```python
"""ingested_messages, pending_prompts, disk_state — the email-flow + disk state tables."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from driftnote.models import DiskState, IngestedMessage, PendingPrompt


class IngestedMessageRecord(BaseModel):
    message_id: str
    date: str
    eml_path: str
    ingested_at: str
    imap_moved: int


class PendingPromptRecord(BaseModel):
    date: str
    message_id: str
    sent_at: str


def record_ingested(
    session: Session,
    *,
    message_id: str,
    date: str,
    eml_path: str,
    ingested_at: str,
) -> None:
    session.add(
        IngestedMessage(
            message_id=message_id,
            date=date,
            eml_path=eml_path,
            ingested_at=ingested_at,
            imap_moved=0,
        )
    )


def is_ingested(session: Session, message_id: str) -> bool:
    return session.scalar(select(IngestedMessage.message_id).where(IngestedMessage.message_id == message_id)) is not None


def get_ingested(session: Session, message_id: str) -> IngestedMessageRecord | None:
    row = session.scalar(select(IngestedMessage).where(IngestedMessage.message_id == message_id))
    if row is None:
        return None
    return IngestedMessageRecord(
        message_id=row.message_id,
        date=row.date,
        eml_path=row.eml_path,
        ingested_at=row.ingested_at,
        imap_moved=row.imap_moved,
    )


def mark_imap_moved(session: Session, message_id: str) -> None:
    session.execute(
        update(IngestedMessage)
        .where(IngestedMessage.message_id == message_id)
        .values(imap_moved=1)
    )


def pending_imap_moves(session: Session) -> list[IngestedMessageRecord]:
    rows = session.scalars(select(IngestedMessage).where(IngestedMessage.imap_moved == 0))
    return [
        IngestedMessageRecord(
            message_id=r.message_id,
            date=r.date,
            eml_path=r.eml_path,
            ingested_at=r.ingested_at,
            imap_moved=r.imap_moved,
        )
        for r in rows
    ]


def record_pending_prompt(
    session: Session,
    *,
    date: str,
    message_id: str,
    sent_at: str,
) -> None:
    """Idempotent on `date` (the PK)."""
    stmt = (
        sqlite_insert(PendingPrompt)
        .values(date=date, message_id=message_id, sent_at=sent_at)
        .on_conflict_do_update(
            index_elements=["date"],
            set_={"message_id": message_id, "sent_at": sent_at},
        )
    )
    session.execute(stmt)


def find_prompt_by_message_id(session: Session, message_id: str) -> PendingPromptRecord | None:
    row = session.scalar(select(PendingPrompt).where(PendingPrompt.message_id == message_id))
    if row is None:
        return None
    return PendingPromptRecord(date=row.date, message_id=row.message_id, sent_at=row.sent_at)


def get_threshold_crossed_at(session: Session, threshold: int) -> str | None:
    row = session.scalar(select(DiskState).where(DiskState.threshold_percent == threshold))
    return row.crossed_at if row else None


def record_threshold_crossed(session: Session, *, threshold: int, at: str) -> None:
    stmt = (
        sqlite_insert(DiskState)
        .values(threshold_percent=threshold, crossed_at=at)
        .on_conflict_do_update(
            index_elements=["threshold_percent"],
            set_={"crossed_at": at},
        )
    )
    session.execute(stmt)


def clear_threshold_crossed(session: Session, threshold: int) -> None:
    session.execute(delete(DiskState).where(DiskState.threshold_percent == threshold))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repository_ingested.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/repository/ingested.py tests/unit/test_repository_ingested.py
git commit -m "feat(repository): ingested_messages + pending_prompts + disk_state"
```

---

### Chunk 4 closeout

**Acceptance criteria:**
- [ ] All Chunks 1–4 tests pass: `uv run pytest -v` (≥48 tests).
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] Repository layer covers entries, tags, media, jobs, ingested, pending_prompts, disk_state — no ORM types leak above this layer (lint with a quick grep: `grep -RnE 'from driftnote.models' src/driftnote/web src/driftnote/ingest src/driftnote/scheduler` should be empty when those layers exist).
- [ ] 4 task commits in this chunk with conventional-commit prefixes.

**Hand-off:** Chunks 4 and 5 (mail transport) can run in parallel from the end of Chunk 3 since neither depends on the other. Chunk 6 (ingestion pipeline) needs both.

---

## Chunk 5: Mail transport (IMAP + SMTP via GreenMail)

**Outcome of this chunk:** A `mail/` module that can SMTP-send (subject, body_text, optional body_html, attachments, optional `In-Reply-To`) and IMAP-poll (fetch UNSEEN messages, copy to Processed folder, mark deleted, expunge). Same code path runs against Gmail in prod and GreenMail in dev/CI; transport selection is purely configuration. Integration tests use `testcontainers-python` to spin up GreenMail per test session.

**Adds dependencies (already in pyproject):** `aioimaplib`, `aiosmtplib`, `testcontainers`. No new deps.

### Task 5.1: GreenMail test fixture

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/integration/conftest.py`

- [ ] **Step 1: Extend `tests/conftest.py` with shared mail-server fixture types**

Replace `tests/conftest.py` with:

```python
"""Shared pytest fixtures for Driftnote tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class MailServer:
    """Connection details for a running mail server (GreenMail in tests)."""

    host: str
    smtp_port: int
    imap_port: int
    user: str
    password: str
    address: str


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Iterator[Path]:
    """A temp data directory matching the prod layout."""
    data = tmp_path / "data"
    (data / "entries").mkdir(parents=True)
    yield data
```

- [ ] **Step 2: Create `tests/integration/conftest.py` with the GreenMail container fixture**

```python
"""Integration-test fixtures: a session-scoped GreenMail container."""

from __future__ import annotations

import socket
import time
from collections.abc import Iterator

import pytest
from testcontainers.core.container import DockerContainer

from tests.conftest import MailServer


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"port {host}:{port} not reachable within {timeout}s")


@pytest.fixture(scope="session")
def mail_server() -> Iterator[MailServer]:
    user = "you"
    password = "apppwd"
    address = "you@example.com"
    container = (
        DockerContainer("greenmail/standalone:2.1.4")
        .with_env(
            "GREENMAIL_OPTS",
            (
                "-Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap "
                f"-Dgreenmail.users={user}:{password}:{address} "
                "-Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled"
            ),
        )
        .with_exposed_ports(3025, 3143, 8080)
    )
    container.start()
    try:
        host = container.get_container_host_ip()
        smtp_port = int(container.get_exposed_port(3025))
        imap_port = int(container.get_exposed_port(3143))
        _wait_for_port(host, smtp_port)
        _wait_for_port(host, imap_port)
        yield MailServer(
            host=host,
            smtp_port=smtp_port,
            imap_port=imap_port,
            user=user,
            password=password,
            address=address,
        )
    finally:
        container.stop()
```

- [ ] **Step 3: Verify the fixture starts a real container**

Add a smoke test `tests/integration/test_mail_fixture_smoke.py`:

```python
"""Smoke test that the GreenMail container fixture comes up."""

from __future__ import annotations

import socket

from tests.conftest import MailServer


def test_mail_server_ports_reachable(mail_server: MailServer) -> None:
    for port in (mail_server.smtp_port, mail_server.imap_port):
        with socket.create_connection((mail_server.host, port), timeout=3):
            pass
```

Run: `uv run pytest tests/integration/test_mail_fixture_smoke.py -v`
Expected: 1 passed (takes ~3-5s for the container to come up).

- [ ] **Step 4: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add tests/conftest.py tests/integration/conftest.py tests/integration/test_mail_fixture_smoke.py
git commit -m "test: GreenMail testcontainers fixture for integration tests"
```

---

### Task 5.2: `mail/transport.py` — connection params

**Files:**
- Create: `src/driftnote/mail/__init__.py`
- Create: `src/driftnote/mail/transport.py`
- Create: `tests/unit/test_mail_transport.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for mail transport config translation."""

from __future__ import annotations

from driftnote.config import Config, EmailConfig, ScheduleConfig, PromptConfig, ParsingConfig, DigestsConfig, BackupConfig, DiskConfig, Secrets
from driftnote.mail.transport import ImapTransport, SmtpTransport, transports_from_config

from pydantic import SecretStr


def _config(**email_overrides) -> Config:
    email = EmailConfig(
        imap_folder="Driftnote/Inbox",
        imap_processed_folder="Driftnote/Processed",
        recipient="you@gmail.com",
        sender_name="Driftnote",
        imap_host="imap.gmail.com",
        imap_port=993,
        imap_tls=True,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_tls=False,
        smtp_starttls=True,
    )
    return Config(
        schedule=ScheduleConfig(
            daily_prompt="0 21 * * *",
            weekly_digest="0 8 * * 1",
            monthly_digest="0 8 1 * *",
            yearly_digest="0 8 1 1 *",
            imap_poll="*/5 * * * *",
            timezone="Europe/London",
        ),
        email=email.model_copy(update=email_overrides),
        prompt=PromptConfig(subject_template="[Driftnote] {date}", body_template="t.j2"),
        parsing=ParsingConfig(mood_regex=r"^Mood:\s*(\S+)", tag_regex=r"#(\w+)", max_photos=4, max_videos=2),
        digests=DigestsConfig(weekly_enabled=True, monthly_enabled=True, yearly_enabled=True),
        backup=BackupConfig(retain_months=12, encrypt=False, age_key_path=""),
        disk=DiskConfig(warn_percent=80, alert_percent=95, check_cron="0 */6 * * *", data_path="/var/driftnote/data"),
        secrets=Secrets(
            gmail_user="you@gmail.com",
            gmail_app_password=SecretStr("p"),
            cf_access_aud="aud",
            cf_team_domain="t.example.com",
        ),
    )


def test_transports_from_config_prod() -> None:
    cfg = _config()
    imap, smtp = transports_from_config(cfg)
    assert imap == ImapTransport(
        host="imap.gmail.com",
        port=993,
        tls=True,
        username="you@gmail.com",
        password="p",
        inbox_folder="Driftnote/Inbox",
        processed_folder="Driftnote/Processed",
    )
    assert smtp == SmtpTransport(
        host="smtp.gmail.com",
        port=587,
        tls=False,
        starttls=True,
        username="you@gmail.com",
        password="p",
        sender_address="you@gmail.com",
        sender_name="Driftnote",
    )


def test_transports_from_config_dev_with_overrides() -> None:
    cfg = _config(imap_host="mail", imap_port=3143, imap_tls=False, smtp_host="mail", smtp_port=3025, smtp_starttls=False)
    imap, smtp = transports_from_config(cfg)
    assert imap.host == "mail"
    assert imap.tls is False
    assert smtp.starttls is False
    assert smtp.port == 3025
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_mail_transport.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/mail/__init__.py`** (empty)

```python
"""Mail transport: SMTP send + IMAP poll."""
```

- [ ] **Step 4: Implement `src/driftnote/mail/transport.py`**

```python
"""Connection parameters for IMAP and SMTP transports.

Translated from `Config` once at app startup; passed to send/poll functions.
"""

from __future__ import annotations

from dataclasses import dataclass

from driftnote.config import Config


@dataclass(frozen=True)
class ImapTransport:
    host: str
    port: int
    tls: bool
    username: str
    password: str
    inbox_folder: str
    processed_folder: str


@dataclass(frozen=True)
class SmtpTransport:
    host: str
    port: int
    tls: bool         # implicit TLS (SMTPS, port 465)
    starttls: bool    # opportunistic STARTTLS (port 587)
    username: str
    password: str
    sender_address: str
    sender_name: str


def transports_from_config(cfg: Config) -> tuple[ImapTransport, SmtpTransport]:
    imap = ImapTransport(
        host=cfg.email.imap_host,
        port=cfg.email.imap_port,
        tls=cfg.email.imap_tls,
        username=cfg.secrets.gmail_user,
        password=cfg.secrets.gmail_app_password.get_secret_value(),
        inbox_folder=cfg.email.imap_folder,
        processed_folder=cfg.email.imap_processed_folder,
    )
    smtp = SmtpTransport(
        host=cfg.email.smtp_host,
        port=cfg.email.smtp_port,
        tls=cfg.email.smtp_tls,
        starttls=cfg.email.smtp_starttls,
        username=cfg.secrets.gmail_user,
        password=cfg.secrets.gmail_app_password.get_secret_value(),
        sender_address=cfg.secrets.gmail_user,
        sender_name=cfg.email.sender_name,
    )
    return imap, smtp
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_mail_transport.py -v`
Expected: 2 passed.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/mail/__init__.py src/driftnote/mail/transport.py tests/unit/test_mail_transport.py
git commit -m "feat(mail): immutable transport dataclasses derived from config"
```

---

### Task 5.3: `mail/smtp.py` — async SMTP send

**Files:**
- Create: `src/driftnote/mail/smtp.py`
- Create: `tests/integration/test_mail_smtp.py`

- [ ] **Step 1: Write failing test**

```python
"""Integration test: SMTP send via GreenMail."""

from __future__ import annotations

import asyncio
import imaplib

import pytest

from driftnote.mail.smtp import Attachment, send_email
from driftnote.mail.transport import SmtpTransport
from tests.conftest import MailServer


def _smtp(mail_server: MailServer) -> SmtpTransport:
    return SmtpTransport(
        host=mail_server.host,
        port=mail_server.smtp_port,
        tls=False,
        starttls=False,
        username=mail_server.user,
        password=mail_server.password,
        sender_address=mail_server.address,
        sender_name="Driftnote",
    )


def _fetch_via_imap(mail_server: MailServer) -> bytes:
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select("INBOX")
    typ, data = mb.search(None, "ALL")
    assert typ == "OK"
    ids = data[0].split()
    assert ids, "no message in INBOX"
    typ, msg_data = mb.fetch(ids[-1], "(RFC822)")
    assert typ == "OK"
    raw = msg_data[0][1]
    mb.logout()
    return raw


def test_send_plain_email(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    msg_id = asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="hi",
            body_text="hello there",
        )
    )
    assert msg_id.startswith("<") and msg_id.endswith(">")
    raw = _fetch_via_imap(mail_server)
    assert b"Subject: hi" in raw
    assert b"hello there" in raw
    assert msg_id.encode() in raw


def test_send_with_in_reply_to(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="re: weekly",
            body_text="thread reply",
            in_reply_to="<original-prompt-id@driftnote>",
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"In-Reply-To: <original-prompt-id@driftnote>" in raw
    assert b"References: <original-prompt-id@driftnote>" in raw


def test_send_with_html_alternative(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="alt",
            body_text="plain version",
            body_html="<p>HTML version</p>",
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"multipart/alternative" in raw
    assert b"plain version" in raw
    assert b"<p>HTML version</p>" in raw


def test_send_with_attachment(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="with photo",
            body_text="see attached",
            attachments=[Attachment(filename="photo.jpg", content=b"\xff\xd8\xffJPEG-bytes", mime_type="image/jpeg")],
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"photo.jpg" in raw
    assert b"image/jpeg" in raw


def test_send_with_inline_image_cid(mail_server: MailServer) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        send_email(
            smtp,
            recipient=mail_server.address,
            subject="cid",
            body_text="see body",
            body_html='<img src="cid:photo1@driftnote">',
            attachments=[
                Attachment(
                    filename="photo.jpg",
                    content=b"jpegbytes",
                    mime_type="image/jpeg",
                    content_id="<photo1@driftnote>",
                    inline=True,
                )
            ],
        )
    )
    raw = _fetch_via_imap(mail_server)
    assert b"Content-ID: <photo1@driftnote>" in raw
    assert b"Content-Disposition: inline" in raw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_mail_smtp.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/mail/smtp.py`**

```python
"""Async SMTP send. Builds a MIME message and dispatches via aiosmtplib.

Returns the outgoing Message-ID so callers can persist it (e.g. as the
prompt's anchor for matching incoming replies).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import aiosmtplib

from driftnote.mail.transport import SmtpTransport


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes
    mime_type: str            # e.g. "image/jpeg"
    content_id: str | None = None    # set + inline=True for CID-referenced inline images
    inline: bool = False


async def send_email(
    transport: SmtpTransport,
    *,
    recipient: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    attachments: list[Attachment] | None = None,
    in_reply_to: str | None = None,
) -> str:
    """Send an email and return the generated Message-ID (including angle brackets)."""
    msg = EmailMessage()
    msg["From"] = formataddr((transport.sender_name, transport.sender_address))
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = formatdate(time.time(), localtime=True)
    domain = transport.sender_address.split("@", 1)[-1] or "driftnote"
    message_id = make_msgid(idstring=secrets.token_hex(8), domain=domain)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    for att in attachments or []:
        maintype, _, subtype = att.mime_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        kwargs = {
            "maintype": maintype,
            "subtype": subtype,
            "filename": att.filename,
        }
        if att.inline and att.content_id:
            kwargs["disposition"] = "inline"
            kwargs["cid"] = att.content_id
        msg.add_attachment(att.content, **kwargs)

    await aiosmtplib.send(
        msg,
        hostname=transport.host,
        port=transport.port,
        use_tls=transport.tls,
        start_tls=transport.starttls,
        username=transport.username if transport.username else None,
        password=transport.password if transport.password else None,
    )
    return message_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_mail_smtp.py -v`
Expected: 5 passed (~3s with container reuse).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/mail/smtp.py tests/integration/test_mail_smtp.py
git commit -m "feat(mail): async SMTP send with HTML alt + attachments + inline CIDs"
```

---

### Task 5.4: `mail/imap.py` — async IMAP poll + move

**Files:**
- Create: `src/driftnote/mail/imap.py`
- Create: `tests/integration/test_mail_imap.py`

- [ ] **Step 1: Write failing test**

```python
"""Integration test: IMAP poll + move via GreenMail."""

from __future__ import annotations

import asyncio
import imaplib
from email.message import EmailMessage
from email.utils import make_msgid

import pytest

from driftnote.mail.imap import RawMessage, move_to_processed, poll_unseen
from driftnote.mail.transport import ImapTransport
from tests.conftest import MailServer


def _imap(mail_server: MailServer, *, inbox: str = "INBOX", processed: str = "INBOX.Processed") -> ImapTransport:
    return ImapTransport(
        host=mail_server.host,
        port=mail_server.imap_port,
        tls=False,
        username=mail_server.user,
        password=mail_server.password,
        inbox_folder=inbox,
        processed_folder=processed,
    )


def _drop_into_inbox(mail_server: MailServer, *, subject: str, message_id: str | None = None) -> str:
    """Use raw IMAP APPEND to inject a test message into the user's INBOX."""
    msg = EmailMessage()
    msg["From"] = mail_server.address
    msg["To"] = mail_server.address
    msg["Subject"] = subject
    if message_id is None:
        message_id = make_msgid(domain="driftnote")
    msg["Message-ID"] = message_id
    msg.set_content("body of " + subject)

    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.append("INBOX", "", imaplib.Time2Internaldate(0), msg.as_bytes())
    mb.logout()
    return message_id


def _list_inbox_subjects(mail_server: MailServer, folder: str = "INBOX") -> list[bytes]:
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select(folder)
    typ, data = mb.search(None, "ALL")
    out: list[bytes] = []
    for ident in data[0].split():
        typ, hdr = mb.fetch(ident, "(BODY[HEADER.FIELDS (SUBJECT)])")
        out.append(hdr[0][1])
    mb.logout()
    return out


@pytest.fixture(autouse=True)
def _clean_mailbox(mail_server: MailServer):
    """Empty INBOX + Processed before each test so order-dependent ones don't leak state."""
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    for folder in ("INBOX", "INBOX.Processed"):
        try:
            mb.select(folder)
            mb.store("1:*", "+FLAGS", r"\Deleted")
            mb.expunge()
        except Exception:
            pass
    # Ensure Processed exists (GreenMail auto-creates on append, but explicit create is safer).
    try:
        mb.create("INBOX.Processed")
    except Exception:
        pass
    mb.logout()


def test_poll_unseen_returns_raw_messages(mail_server: MailServer) -> None:
    msg_id = _drop_into_inbox(mail_server, subject="hello driftnote")
    transport = _imap(mail_server)
    messages: list[RawMessage] = asyncio.run(_collect(transport))
    assert len(messages) == 1
    assert messages[0].message_id == msg_id
    assert b"Subject: hello driftnote" in messages[0].raw_bytes


def test_poll_skips_already_seen_messages(mail_server: MailServer) -> None:
    _drop_into_inbox(mail_server, subject="first")
    transport = _imap(mail_server)
    asyncio.run(_collect(transport))  # first poll marks them \Seen
    second = asyncio.run(_collect(transport))
    assert second == []


def test_move_to_processed(mail_server: MailServer) -> None:
    msg_id = _drop_into_inbox(mail_server, subject="movable")
    transport = _imap(mail_server)
    asyncio.run(move_to_processed(transport, message_id=msg_id))
    inbox = _list_inbox_subjects(mail_server, "INBOX")
    processed = _list_inbox_subjects(mail_server, "INBOX.Processed")
    assert all(b"movable" not in s for s in inbox)
    assert any(b"movable" in s for s in processed)


async def _collect(transport: ImapTransport) -> list[RawMessage]:
    out: list[RawMessage] = []
    async for msg in poll_unseen(transport):
        out.append(msg)
    return out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_mail_imap.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/mail/imap.py`**

```python
"""Async IMAP poll + move helpers built on aioimaplib.

`poll_unseen` is an async generator yielding `RawMessage` for each UNSEEN
message in `transport.inbox_folder`. After the consumer has persisted the
message it should call `move_to_processed(transport, message_id=...)` to
copy the message to the Processed folder, mark it deleted in Inbox, and
expunge.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as default_policy

import aioimaplib

from driftnote.mail.transport import ImapTransport


@dataclass(frozen=True)
class RawMessage:
    """A fetched UNSEEN message: original bytes + parsed Message-ID."""

    message_id: str
    raw_bytes: bytes


async def _connect(transport: ImapTransport) -> aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL:
    if transport.tls:
        client: aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL = aioimaplib.IMAP4_SSL(host=transport.host, port=transport.port)
    else:
        client = aioimaplib.IMAP4(host=transport.host, port=transport.port)
    await client.wait_hello_from_server()
    await client.login(transport.username, transport.password)
    return client


async def poll_unseen(transport: ImapTransport) -> AsyncIterator[RawMessage]:
    """Yield each UNSEEN message in transport.inbox_folder. Marks them \\Seen."""
    client = await _connect(transport)
    try:
        await client.select(transport.inbox_folder)
        result, data = await client.search("UNSEEN")
        if result != "OK" or not data or not data[0]:
            return
        ids = data[0].split()
        for ident in ids:
            ident_str = ident.decode("ascii")
            fetch_result, fetch_data = await client.fetch(ident_str, "(RFC822)")
            if fetch_result != "OK":
                continue
            raw = _extract_rfc822(fetch_data)
            if raw is None:
                continue
            parsed = BytesParser(policy=default_policy).parsebytes(raw)
            message_id = (parsed["Message-ID"] or "").strip()
            if not message_id:
                continue
            yield RawMessage(message_id=message_id, raw_bytes=raw)
    finally:
        await client.logout()


async def move_to_processed(transport: ImapTransport, *, message_id: str) -> None:
    """Copy the message to Processed, mark deleted in Inbox, expunge.

    Raises if the message cannot be located by Message-ID.
    """
    client = await _connect(transport)
    try:
        # Ensure the destination folder exists. GreenMail and Gmail both accept
        # CREATE on an existing folder as a no-op (Gmail returns NO; we ignore it).
        try:
            await client.create(transport.processed_folder)
        except Exception:
            pass
        await client.select(transport.inbox_folder)
        # IMAP requires HEADER values containing brackets/@/spaces to be
        # IMAP-quoted. Wrap the Message-ID in double quotes.
        quoted = f'"{message_id}"'
        result, data = await client.search("HEADER", "Message-ID", quoted)
        if result != "OK" or not data or not data[0]:
            raise RuntimeError(f"message {message_id} not found in {transport.inbox_folder}")
        ident = data[0].split()[0].decode("ascii")
        copy_result, _ = await client.copy(ident, transport.processed_folder)
        if copy_result != "OK":
            raise RuntimeError(f"COPY failed: {copy_result}")
        await client.store(ident, "+FLAGS", r"(\Deleted)")
        await client.expunge()
    finally:
        try:
            await client.logout()
        except Exception:
            pass


def _extract_rfc822(fetch_data: list) -> bytes | None:
    """Pull the RFC822 body bytes out of an aioimaplib FETCH response.

    aioimaplib's FETCH returns a list shaped roughly:
        [b'<seqnum> (RFC822 {<size>}', b'<rfc822-bytes>', b')', b'FETCH completed.']

    Anchor on the literal-size prelude (`...{N}`): the body is the immediately
    following bytes chunk. Robust against trailing status lines or multiple
    FETCH responses appearing in the same `data` list.
    """
    for i, chunk in enumerate(fetch_data):
        if not isinstance(chunk, (bytes, bytearray)):
            continue
        stripped = chunk.rstrip()
        if stripped.endswith(b"}") and b"{" in stripped:
            if i + 1 < len(fetch_data) and isinstance(fetch_data[i + 1], (bytes, bytearray)):
                return bytes(fetch_data[i + 1])
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_mail_imap.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/mail/imap.py tests/integration/test_mail_imap.py
git commit -m "feat(mail): async IMAP poll + move-to-Processed helpers"
```

---

### Chunk 5 closeout

**Acceptance criteria:**
- [ ] All Chunks 1–5 tests pass: `uv run pytest -v` (≥58 tests).
- [ ] Integration tests with GreenMail run from a clean checkout (no externally-managed services required).
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] 4 task commits in this chunk with conventional-commit prefixes.

**Hand-off:** Chunk 6 (ingestion pipeline) needs Chunks 3, 4, and 5; with all three landed, ingestion can be implemented next.

---

## Chunk 6: Ingestion pipeline

**Outcome of this chunk:** A `driftnote/ingest/` module that, given a single raw `.eml` byte string + the ambient config + DB engine + data root, produces (or updates) an `entry.md` on disk, derives photo/video files, and upserts the SQLite index — atomically per the spec §3.B failure semantics. Idempotent on `Message-ID` via `ingested_messages` and `imap_moved` flag.

### Task 6.1: `ingest/parse.py` — extract mood/tags/body/attachments from a raw email

**Files:**
- Create: `src/driftnote/ingest/__init__.py`
- Create: `src/driftnote/ingest/parse.py`
- Create: `tests/fixtures/emails/` (directory; `.eml` files dropped here per test)
- Create: `tests/unit/test_ingest_parse.py`

- [ ] **Step 1: Build small `.eml` fixtures**

Create the following fixtures by writing them in the test (so the plan stays self-contained), or commit small `.eml` files to `tests/fixtures/emails/`. The tests below construct `EmailMessage` objects in-memory and serialize to bytes; no separate fixture files are needed.

- [ ] **Step 2: Write failing test**

```python
"""Tests for raw-email parsing."""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import make_msgid

import pytest

from driftnote.ingest.parse import (
    AttachmentMaterial,
    ParsedReply,
    parse_reply,
)


def _eml(
    *,
    subject: str = "[Driftnote] How was 2026-05-06?",
    body_text: str = "Mood: 💪\n\nLong day at work. #work #cooking",
    body_html: str | None = None,
    in_reply_to: str | None = "<prompt-2026-05-06@driftnote>",
    attachments: list[tuple[str, str, bytes]] | None = None,  # (filename, mime, bytes)
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "you@gmail.com"
    msg["To"] = "you@gmail.com"
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="driftnote")
    msg["Date"] = "Wed, 06 May 2026 21:30:15 +0000"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    for filename, mime, payload in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def test_parse_extracts_mood_marker() -> None:
    raw = _eml(body_text="Mood: 💪\n\nGood day.")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.mood == "💪"
    assert parsed.body.strip() == "Good day."


def test_parse_falls_back_to_first_emoji_when_no_mood_marker() -> None:
    raw = _eml(body_text="🎉 yay something happened\n#celebrate")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.mood == "🎉"
    assert "celebrate" in parsed.tags


def test_parse_no_mood_at_all_yields_none() -> None:
    raw = _eml(body_text="Just some plain ASCII text. No mood available.\n#nothing")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.mood is None


def test_parse_extracts_tags_lowercased_deduplicated() -> None:
    raw = _eml(body_text="Mood: 💪\n\n#Work #work #COOKING and #cooking again")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert sorted(parsed.tags) == ["cooking", "work"]


def test_parse_strips_quoted_thread() -> None:
    body = (
        "Mood: 🌧️\n\nRainy walk in the park.\n\n"
        "On Wed, 6 May 2026 at 21:00, Driftnote <you@gmail.com> wrote:\n"
        "> Hi Maciej,\n"
        "> How was today?\n"
    )
    raw = _eml(body_text=body)
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert "Rainy walk in the park." in parsed.body
    assert "How was today?" not in parsed.body
    assert "On Wed" not in parsed.body


def test_parse_returns_in_reply_to() -> None:
    raw = _eml(in_reply_to="<prompt-2026-05-06@driftnote>")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.in_reply_to == "<prompt-2026-05-06@driftnote>"


def test_parse_returns_message_id_and_date() -> None:
    raw = _eml()
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.message_id.startswith("<")
    # Date header parses to datetime
    assert parsed.date_header is not None
    assert parsed.date_header.year == 2026


def test_parse_attachments_split_by_mime_type() -> None:
    raw = _eml(
        attachments=[
            ("photo.jpg", "image/jpeg", b"\xff\xd8\xff\xd9"),
            ("video.mov", "video/quicktime", b"MOOV..."),
            ("notes.pdf", "application/pdf", b"%PDF-..."),
        ]
    )
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    photos = [a for a in parsed.attachments if a.kind == "photo"]
    videos = [a for a in parsed.attachments if a.kind == "video"]
    other = [a for a in parsed.attachments if a.kind == "other"]
    assert [a.filename for a in photos] == ["photo.jpg"]
    assert [a.filename for a in videos] == ["video.mov"]
    assert [a.filename for a in other] == ["notes.pdf"]


def test_parse_attachment_material_round_trips_bytes() -> None:
    raw = _eml(attachments=[("photo.jpg", "image/jpeg", b"\xff\xd8\xffJPG")])
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.attachments[0].content == b"\xff\xd8\xffJPG"


def test_parse_picks_plain_body_over_html_when_both_present() -> None:
    raw = _eml(
        body_text="Mood: 🎉\n\nplain text version",
        body_html="<p>HTML version</p>",
    )
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert "plain text version" in parsed.body
    assert "<p>" not in parsed.body
```

- [ ] **Step 3: Implement `src/driftnote/ingest/__init__.py`** (empty)

```python
"""Ingestion pipeline: raw .eml → entry.md + media + SQLite rows."""
```

- [ ] **Step 4: Implement `src/driftnote/ingest/parse.py`**

```python
"""Parse a raw .eml byte string into a ParsedReply.

We extract:
- message_id, in_reply_to, date_header (from headers)
- body (plain text, with quoted-reply chunks stripped)
- mood (configured regex; falls back to first emoji in body; None if neither)
- tags (configured regex; lowercased + deduplicated)
- attachments (image/* → photo, video/* → video, anything else → other)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Literal


@dataclass(frozen=True)
class AttachmentMaterial:
    filename: str
    mime_type: str
    kind: Literal["photo", "video", "other"]
    content: bytes


@dataclass(frozen=True)
class ParsedReply:
    message_id: str
    in_reply_to: str | None
    date_header: datetime | None
    body: str
    mood: str | None
    tags: list[str]
    attachments: list[AttachmentMaterial]


_QUOTE_HEADER_PATTERNS = (
    re.compile(r"^On\s+.+\s+wrote:\s*$", re.MULTILINE),
    re.compile(r"^From:\s+.+$", re.MULTILINE),  # Outlook-style "From:" thread headers
)


def parse_reply(raw: bytes, *, mood_regex: str, tag_regex: str) -> ParsedReply:
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)  # type: ignore[assignment]

    message_id = (msg["Message-ID"] or "").strip()
    in_reply_to_raw = msg["In-Reply-To"]
    in_reply_to = in_reply_to_raw.strip() if in_reply_to_raw else None
    date_header_raw = msg["Date"]
    date_header = parsedate_to_datetime(date_header_raw) if date_header_raw else None

    body = _extract_plain_body(msg)
    body = _strip_quoted(body)

    mood = _extract_mood(body, mood_regex)
    tags = _extract_tags(body, tag_regex)
    attachments = _collect_attachments(msg)

    return ParsedReply(
        message_id=message_id,
        in_reply_to=in_reply_to,
        date_header=date_header,
        body=body,
        mood=mood,
        tags=tags,
        attachments=attachments,
    )


def _extract_plain_body(msg: EmailMessage) -> str:
    """Prefer text/plain; fall back to a stripped text/html if no plain part exists."""
    plain = msg.get_body(preferencelist=("plain",))
    if plain is not None:
        return plain.get_content().rstrip("\n") + "\n"
    html = msg.get_body(preferencelist=("html",))
    if html is not None:
        return _crude_html_to_text(html.get_content())
    return ""


def _crude_html_to_text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip() + "\n"


def _strip_quoted(body: str) -> str:
    """Remove the quoted-reply portion: everything from `On … wrote:` (or similar) onward,
    plus any block of `>`-prefixed lines at the end."""
    # Find the earliest quote-marker line; truncate there.
    cut_idx: int | None = None
    for pattern in _QUOTE_HEADER_PATTERNS:
        m = pattern.search(body)
        if m and (cut_idx is None or m.start() < cut_idx):
            cut_idx = m.start()
    if cut_idx is not None:
        body = body[:cut_idx]
    # Also trim trailing `>`-prefixed lines (defensive: some clients omit the header).
    lines = body.splitlines()
    while lines and lines[-1].lstrip().startswith(">"):
        lines.pop()
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def _extract_mood(body: str, mood_regex: str) -> str | None:
    m = re.search(mood_regex, body, re.MULTILINE)
    if m:
        return m.group(1)
    # Fallback: first emoji in the body.
    for ch in body:
        if _is_emoji(ch):
            return ch
    return None


def _is_emoji(ch: str) -> bool:
    """Quick-and-dirty emoji classifier — enough for journal mood extraction.

    Categories starting with 'S' (Symbol) are the safest broad bucket; we also
    include common emoji-block code points by Unicode property.
    """
    if not ch:
        return False
    cat = unicodedata.category(ch)
    if cat in {"So", "Sk"}:  # Other-Symbol, Modifier-Symbol
        return True
    cp = ord(ch)
    # Misc Symbols, Pictographs, Emoticons, Transport, Supplemental Symbols, etc.
    return any(
        lo <= cp <= hi
        for lo, hi in (
            (0x1F300, 0x1F6FF),
            (0x1F900, 0x1F9FF),
            (0x1FA70, 0x1FAFF),
            (0x2600, 0x26FF),
            (0x2700, 0x27BF),
        )
    )


def _extract_tags(body: str, tag_regex: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in re.finditer(tag_regex, body):
        normalized = m.group(1).lower()
        seen.setdefault(normalized, None)
    return list(seen)


def _collect_attachments(msg: EmailMessage) -> list[AttachmentMaterial]:
    out: list[AttachmentMaterial] = []
    for part in msg.iter_attachments():
        mime = (part.get_content_type() or "application/octet-stream").lower()
        filename = part.get_filename() or "attachment.bin"
        content = part.get_payload(decode=True) or b""
        if mime.startswith("image/"):
            kind: Literal["photo", "video", "other"] = "photo"
        elif mime.startswith("video/"):
            kind = "video"
        else:
            kind = "other"
        out.append(
            AttachmentMaterial(filename=filename, mime_type=mime, kind=kind, content=content)
        )
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ingest_parse.py -v`
Expected: 10 passed.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/ingest/__init__.py src/driftnote/ingest/parse.py tests/unit/test_ingest_parse.py
git commit -m "feat(ingest): parse raw .eml for mood/tags/body/attachments"
```

---

### Task 6.2: `ingest/attachments.py` — derivatives (web/thumb/poster)

**Files:**
- Create: `src/driftnote/ingest/attachments.py`
- Create: `tests/fixtures/images/tiny.jpg`, `tiny.heic`, `tiny.mov` (small test fixtures)
- Create: `tests/unit/test_ingest_attachments.py`

- [ ] **Step 1: Generate test fixture files**

Build the fixtures programmatically the first time and check them in. Run:

```bash
uv run python - <<'PY'
from pathlib import Path
from io import BytesIO
from PIL import Image

dest = Path("tests/fixtures/images")
dest.mkdir(parents=True, exist_ok=True)

img = Image.new("RGB", (200, 150), color=(180, 100, 60))
img.save(dest / "tiny.jpg", quality=85)

import pillow_heif
pillow_heif.register_heif_opener()
img.save(dest / "tiny.heic", quality=85)
PY

# Generate a tiny test mov via ffmpeg
ffmpeg -y -loglevel error -f lavfi -i "color=c=red:size=64x48:duration=1:rate=2" \
       -pix_fmt yuv420p tests/fixtures/images/tiny.mov
ls -lh tests/fixtures/images/
```

Expected: `tiny.jpg`, `tiny.heic`, `tiny.mov` exist; each <50KB.

- [ ] **Step 2: Write failing test**

```python
"""Tests for image and video derivative generation."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from driftnote.ingest.attachments import (
    AttachmentArtifacts,
    derive_photo,
    derive_video_poster,
)


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "images"


def test_derive_photo_jpeg_creates_web_and_thumb(tmp_path: Path) -> None:
    artifacts = derive_photo(
        original_bytes=(FIXTURE_DIR / "tiny.jpg").read_bytes(),
        original_filename="tiny.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    assert isinstance(artifacts, AttachmentArtifacts)
    assert artifacts.original_path == tmp_path / "originals" / "tiny.jpg"
    assert artifacts.web_path == tmp_path / "web" / "tiny.jpg"
    assert artifacts.thumb_path == tmp_path / "thumbs" / "tiny.jpg"
    assert artifacts.original_path.exists()
    assert artifacts.web_path.exists()
    assert artifacts.thumb_path.exists()
    with Image.open(artifacts.thumb_path) as t:
        assert max(t.size) == 320
    with Image.open(artifacts.web_path) as w:
        # Original is 200x150 — already smaller than 1600 cap, so web copy keeps the orientation.
        assert max(w.size) == 200


def test_derive_photo_heic_converts_to_jpeg(tmp_path: Path) -> None:
    artifacts = derive_photo(
        original_bytes=(FIXTURE_DIR / "tiny.heic").read_bytes(),
        original_filename="tiny.heic",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    # Original is preserved verbatim.
    assert artifacts.original_path.suffix == ".heic"
    # Web/thumb are JPEG for browser compatibility.
    assert artifacts.web_path.suffix == ".jpg"
    assert artifacts.thumb_path.suffix == ".jpg"
    with Image.open(artifacts.web_path) as img:
        assert img.format == "JPEG"


def test_derive_photo_strips_exif_from_derivatives(tmp_path: Path) -> None:
    # Build an in-memory JPEG with embedded EXIF.
    from PIL import Image as _Image
    from PIL.ExifTags import TAGS as _TAGS

    src = _Image.new("RGB", (200, 150), color=(60, 100, 180))
    exif_bytes = b""
    if hasattr(src, "getexif"):
        exif = src.getexif()
        exif[0x010F] = "DriftnoteTestMaker"  # Make
        exif_bytes = exif.tobytes()
    out = tmp_path / "with-exif.jpg"
    src.save(out, "JPEG", exif=exif_bytes)
    raw = out.read_bytes()

    artifacts = derive_photo(
        original_bytes=raw,
        original_filename="with-exif.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    with Image.open(artifacts.web_path) as web:
        web_exif = web.getexif() if hasattr(web, "getexif") else {}
    assert all(tag != 0x010F for tag in web_exif)


def test_derive_video_poster_extracts_frame(tmp_path: Path) -> None:
    poster = derive_video_poster(
        original_bytes=(FIXTURE_DIR / "tiny.mov").read_bytes(),
        original_filename="tiny.mov",
        originals_dir=tmp_path / "originals",
        thumbs_dir=tmp_path / "thumbs",
    )
    assert poster.original_path.exists()
    assert poster.thumb_path.suffix == ".jpg"
    assert poster.thumb_path.exists()
    assert poster.web_path is None
    with Image.open(poster.thumb_path) as img:
        assert img.format == "JPEG"


def test_derive_photo_preserves_original_filename_for_originals_dir(tmp_path: Path) -> None:
    artifacts = derive_photo(
        original_bytes=(FIXTURE_DIR / "tiny.jpg").read_bytes(),
        original_filename="my photo!.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    # Originals are stored with the sender's filename verbatim (they're treated as opaque).
    assert artifacts.original_path.name == "my photo!.jpg"
    # Web/thumb may differ in suffix but should keep the stem.
    assert artifacts.web_path.stem == "my photo!"


def test_derive_photo_handles_unreadable_original(tmp_path: Path) -> None:
    """If the bytes don't decode as an image, original is still saved but web/thumb are None."""
    artifacts = derive_photo(
        original_bytes=b"not an image",
        original_filename="broken.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    assert artifacts.original_path.exists()
    assert artifacts.web_path is None
    assert artifacts.thumb_path is None
```

- [ ] **Step 3: Implement `src/driftnote/ingest/attachments.py`**

```python
"""Generate web/thumb derivatives for photos and a poster frame for videos.

Originals are stored verbatim (treated as opaque bytes). Derivatives:
- Photo web copy: max-axis 1600px, JPEG, EXIF stripped.
- Photo thumbnail: max-axis 320px, JPEG.
- HEIC → JPEG conversion for web/thumb (originals stay HEIC).
- Video poster: ffmpeg-extracted single frame at ~1s, max-axis 320px JPEG.

If decoding fails for any reason, the original is still preserved and
derivative paths come back as None — the UI falls back to a placeholder.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()

WEB_MAX_AXIS = 1600
THUMB_MAX_AXIS = 320


@dataclass(frozen=True)
class AttachmentArtifacts:
    original_path: Path
    web_path: Path | None
    thumb_path: Path | None


def derive_photo(
    *,
    original_bytes: bytes,
    original_filename: str,
    originals_dir: Path,
    web_dir: Path,
    thumbs_dir: Path,
) -> AttachmentArtifacts:
    """Save original bytes verbatim, then attempt to produce web + thumb derivatives.

    Returns artifacts with `web_path`/`thumb_path = None` if derivative
    generation fails; the original is always written as long as the disk
    write itself succeeds.
    """
    originals_dir.mkdir(parents=True, exist_ok=True)
    web_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    original_path = originals_dir / original_filename
    original_path.write_bytes(original_bytes)

    derived_stem = Path(original_filename).stem
    web_path = web_dir / f"{derived_stem}.jpg"
    thumb_path = thumbs_dir / f"{derived_stem}.jpg"

    try:
        with Image.open(BytesIO(original_bytes)) as img:
            img = img.convert("RGB")
            web_img = _resize_max_axis(img, WEB_MAX_AXIS)
            web_img.save(web_path, "JPEG", quality=85, optimize=True)  # EXIF stripped
            thumb_img = _resize_max_axis(img, THUMB_MAX_AXIS)
            thumb_img.save(thumb_path, "JPEG", quality=80, optimize=True)
    except Exception:
        return AttachmentArtifacts(
            original_path=original_path,
            web_path=None,
            thumb_path=None,
        )

    return AttachmentArtifacts(
        original_path=original_path,
        web_path=web_path,
        thumb_path=thumb_path,
    )


def derive_video_poster(
    *,
    original_bytes: bytes,
    original_filename: str,
    originals_dir: Path,
    thumbs_dir: Path,
) -> AttachmentArtifacts:
    """Save original video bytes verbatim and extract a poster frame as a JPEG thumbnail."""
    originals_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    original_path = originals_dir / original_filename
    original_path.write_bytes(original_bytes)

    derived_stem = Path(original_filename).stem
    thumb_path = thumbs_dir / f"{derived_stem}.jpg"

    if shutil.which("ffmpeg") is None:
        return AttachmentArtifacts(original_path=original_path, web_path=None, thumb_path=None)

    with tempfile.NamedTemporaryFile(suffix=".jpg") as raw_thumb:
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel", "error",
                    "-i", str(original_path),
                    "-ss", "00:00:01",     # seek 1s in
                    "-frames:v", "1",
                    "-vf", f"scale='min({THUMB_MAX_AXIS},iw)':-2",
                    raw_thumb.name,
                ],
                check=True,
                timeout=30,
            )
            with Image.open(raw_thumb.name) as img:
                img.convert("RGB").save(thumb_path, "JPEG", quality=80, optimize=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return AttachmentArtifacts(original_path=original_path, web_path=None, thumb_path=None)

    return AttachmentArtifacts(original_path=original_path, web_path=None, thumb_path=thumb_path)


def _resize_max_axis(img: Image.Image, cap: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= cap:
        return img.copy()
    ratio = cap / longest
    new_size = (int(w * ratio), int(h * ratio))
    return img.resize(new_size, Image.Resampling.LANCZOS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ingest_attachments.py -v`
Expected: 6 passed (requires `ffmpeg` and `libheif1` available — already in Containerfile; on the dev host these come from the toolbox image).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/ingest/attachments.py tests/fixtures/images/ tests/unit/test_ingest_attachments.py
git commit -m "feat(ingest): photo derivatives + video poster via Pillow/pillow-heif/ffmpeg"
```

---

### Task 6.3: `ingest/pipeline.py` — orchestration with rollback + idempotency

**Files:**
- Create: `src/driftnote/ingest/pipeline.py`
- Create: `tests/integration/test_ingest_pipeline.py`

This is the heart of the ingestion flow. It composes parse + attachments + filesystem + repository, applies per-date locking, and implements the spec §3.B failure semantics (whole-message rollback on any pre-IMAP-move failure; `imap_moved=0` retry path on IMAP-move failure).

- [ ] **Step 1: Write failing test**

```python
"""End-to-end tests for ingestion pipeline (no real IMAP/SMTP)."""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.config import (
    BackupConfig, Config, DigestsConfig, DiskConfig, EmailConfig,
    ParsingConfig, PromptConfig, ScheduleConfig, Secrets,
)
from driftnote.db import init_db, make_engine, session_scope
from driftnote.ingest.pipeline import IngestionResult, ingest_one
from driftnote.repository.entries import get_entry, list_entries_by_tag
from driftnote.repository.ingested import get_ingested, is_ingested
from driftnote.repository.media import list_media

from pydantic import SecretStr


def _eml_bytes(*, subject="[Driftnote] How was 2026-05-06?",
               body_text="Mood: 💪\n\nLong day at work. #work",
               in_reply_to="<prompt-2026-05-06@driftnote>",
               attachments=None,
               message_id=None) -> tuple[bytes, str]:
    msg = EmailMessage()
    msg["From"] = "you@gmail.com"
    msg["To"] = "you@gmail.com"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id or make_msgid(domain="driftnote")
    msg["Date"] = "Wed, 06 May 2026 21:30:15 +0000"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body_text)
    for filename, mime, payload in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes(), msg["Message-ID"]


def _config(*, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)") -> Config:
    return Config(
        schedule=ScheduleConfig(
            daily_prompt="0 21 * * *", weekly_digest="0 8 * * 1",
            monthly_digest="0 8 1 * *", yearly_digest="0 8 1 1 *",
            imap_poll="*/5 * * * *", timezone="Europe/London",
        ),
        email=EmailConfig(
            imap_folder="INBOX", imap_processed_folder="INBOX.Processed",
            recipient="you@gmail.com", sender_name="Driftnote",
            imap_host="x", imap_port=993, imap_tls=True,
            smtp_host="x", smtp_port=587, smtp_tls=False, smtp_starttls=True,
        ),
        prompt=PromptConfig(subject_template="[Driftnote] {date}", body_template="t.j2"),
        parsing=ParsingConfig(mood_regex=mood_regex, tag_regex=tag_regex, max_photos=4, max_videos=2),
        digests=DigestsConfig(weekly_enabled=True, monthly_enabled=True, yearly_enabled=True),
        backup=BackupConfig(retain_months=12, encrypt=False, age_key_path=""),
        disk=DiskConfig(warn_percent=80, alert_percent=95, check_cron="0 */6 * * *", data_path="/var/driftnote/data"),
        secrets=Secrets(
            gmail_user="you@gmail.com", gmail_app_password=SecretStr("p"),
            cf_access_aud="aud", cf_team_domain="t.example.com",
        ),
    )


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Engine, Path, Config]:
    engine = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(engine)
    data_root = tmp_path / "data"
    cfg = _config()
    return engine, data_root, cfg


def test_ingest_creates_entry_and_db_row(setup) -> None:
    engine, data_root, cfg = setup
    raw, mid = _eml_bytes()

    with session_scope(engine) as session:
        # Pre-record the prompt that this is in reply to, so the date anchor works.
        from driftnote.repository.ingested import record_pending_prompt
        record_pending_prompt(
            session,
            date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>",
            sent_at="2026-05-06T21:00:00Z",
        )

    result = ingest_one(
        raw=raw,
        config=cfg,
        engine=engine,
        data_root=data_root,
        received_at=datetime(2026, 5, 6, 21, 30, 15, tzinfo=timezone.utc),
    )

    assert isinstance(result, IngestionResult)
    assert result.ingested is True
    assert result.entry_date == "2026-05-06"
    assert (data_root / "entries" / "2026" / "05" / "06" / "entry.md").exists()
    assert (data_root / "entries" / "2026" / "05" / "06" / "raw" / "2026-05-06T21-30-15Z.eml").exists()

    with session_scope(engine) as session:
        entry = get_entry(session, "2026-05-06")
        ing = get_ingested(session, mid)
        tagged = list_entries_by_tag(session, "work")
    assert entry is not None
    assert entry.mood == "💪"
    assert ing is not None and ing.imap_moved == 0
    assert [e.date for e in tagged] == ["2026-05-06"]


def test_ingest_is_idempotent_on_message_id(setup) -> None:
    engine, data_root, cfg = setup
    raw, mid = _eml_bytes()

    with session_scope(engine) as session:
        from driftnote.repository.ingested import record_pending_prompt
        record_pending_prompt(session, date="2026-05-06", message_id="<prompt-2026-05-06@driftnote>", sent_at="t")

    received_at = datetime(2026, 5, 6, 21, 30, 15, tzinfo=timezone.utc)
    r1 = ingest_one(raw=raw, config=cfg, engine=engine, data_root=data_root, received_at=received_at)
    r2 = ingest_one(raw=raw, config=cfg, engine=engine, data_root=data_root, received_at=received_at)
    assert r1.ingested is True
    assert r2.ingested is False  # second call short-circuits — already ingested
    # Only one raw .eml file exists (no duplicate).
    raws = list((data_root / "entries" / "2026" / "05" / "06" / "raw").glob("*.eml"))
    assert len(raws) == 1


def test_ingest_appends_for_second_reply_same_date(setup) -> None:
    engine, data_root, cfg = setup

    with session_scope(engine) as session:
        from driftnote.repository.ingested import record_pending_prompt
        record_pending_prompt(session, date="2026-05-06", message_id="<prompt-2026-05-06@driftnote>", sent_at="t")

    raw1, _ = _eml_bytes(body_text="Mood: 💪\n\nfirst section #work")
    raw2, _ = _eml_bytes(body_text="afterthought #cooking")

    ingest_one(raw=raw1, config=cfg, engine=engine, data_root=data_root,
               received_at=datetime(2026, 5, 6, 21, 30, 15, tzinfo=timezone.utc))
    ingest_one(raw=raw2, config=cfg, engine=engine, data_root=data_root,
               received_at=datetime(2026, 5, 7, 2, 15, 22, tzinfo=timezone.utc))

    entry_md = (data_root / "entries" / "2026" / "05" / "06" / "entry.md").read_text()
    assert "first section" in entry_md
    assert "afterthought" in entry_md
    assert "\n---\n" in entry_md.split("\n---\n", 2)[-1]  # body separator between sections

    with session_scope(engine) as session:
        tagged_work = list_entries_by_tag(session, "work")
        tagged_cook = list_entries_by_tag(session, "cooking")
    assert tagged_work and tagged_cook  # tags accumulate across sections


def test_ingest_falls_back_to_date_header_when_no_matching_prompt(setup) -> None:
    engine, data_root, cfg = setup
    raw, _ = _eml_bytes(in_reply_to=None)
    received_at = datetime(2026, 5, 6, 21, 30, 15, tzinfo=timezone.utc)

    result = ingest_one(raw=raw, config=cfg, engine=engine, data_root=data_root, received_at=received_at)

    assert result.ingested is True
    # Entry date taken from the message Date header (Wed, 06 May 2026 21:30:15 +0000)
    assert result.entry_date == "2026-05-06"


def test_ingest_drops_attachments_over_limits(setup) -> None:
    engine, data_root, cfg = setup
    cfg = cfg.model_copy(update={"parsing": cfg.parsing.model_copy(update={"max_photos": 1})})
    raw, _ = _eml_bytes(
        attachments=[
            ("a.jpg", "image/jpeg", b"\xff\xd8\xff\xd9"),
            ("b.jpg", "image/jpeg", b"\xff\xd8\xff\xd9"),
        ],
    )

    with session_scope(engine) as session:
        from driftnote.repository.ingested import record_pending_prompt
        record_pending_prompt(session, date="2026-05-06", message_id="<prompt-2026-05-06@driftnote>", sent_at="t")

    received_at = datetime(2026, 5, 6, 21, 30, 15, tzinfo=timezone.utc)
    ingest_one(raw=raw, config=cfg, engine=engine, data_root=data_root, received_at=received_at)

    with session_scope(engine) as session:
        media_rows = list_media(session, "2026-05-06")
    assert [m.filename for m in media_rows] == ["a.jpg"]


def test_ingest_rolls_back_on_filesystem_failure(setup, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, data_root, cfg = setup
    raw, mid = _eml_bytes()

    with session_scope(engine) as session:
        from driftnote.repository.ingested import record_pending_prompt
        record_pending_prompt(session, date="2026-05-06", message_id="<prompt-2026-05-06@driftnote>", sent_at="t")

    # Simulate a filesystem failure in markdown write.
    from driftnote.filesystem import markdown_io as _mdio

    def _explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(_mdio, "write_entry", _explode)

    with pytest.raises(OSError):
        ingest_one(
            raw=raw, config=cfg, engine=engine, data_root=data_root,
            received_at=datetime(2026, 5, 6, 21, 30, 15, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        assert not is_ingested(session, mid)
    # No partial entry.md or raw/*.eml left behind.
    entry_dir = data_root / "entries" / "2026" / "05" / "06"
    assert not entry_dir.exists() or not any(entry_dir.iterdir())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_ingest_pipeline.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/ingest/pipeline.py`**

```python
"""Orchestrate ingestion of one raw email into the entry store + index.

Implements the spec §3.B failure semantics:
- Idempotency on Message-ID via `ingested_messages`.
- Per-date `fcntl.flock` so two replies for the same date serialize.
- Whole-message rollback on any pre-IMAP-move failure: no entry.md mutation,
  no raw.eml written, no SQLite row.
- The IMAP-move retry path is *not* in this function — it lives in the
  poll job (Chunk 7), which calls `mark_imap_moved()` after a successful move.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine

from driftnote.config import Config
from driftnote.db import session_scope
from driftnote.filesystem.layout import EntryPaths, entry_paths_for, raw_eml_filename
from driftnote.filesystem.locks import entry_lock
from driftnote.filesystem.markdown_io import (
    EntryDocument,
    PhotoRef,
    VideoRef,
    read_entry,
    write_entry,
)
from driftnote.ingest.attachments import (
    AttachmentArtifacts,
    derive_photo,
    derive_video_poster,
)
from driftnote.ingest.parse import AttachmentMaterial, ParsedReply, parse_reply
from driftnote.repository.entries import EntryRecord, replace_tags, upsert_entry
from driftnote.repository.ingested import (
    find_prompt_by_message_id,
    is_ingested,
    record_ingested,
)
from driftnote.repository.media import MediaInput, replace_media


@dataclass(frozen=True)
class IngestionResult:
    ingested: bool       # False if message_id was already ingested (no-op)
    entry_date: str      # 'YYYY-MM-DD'
    message_id: str


def ingest_one(
    *,
    raw: bytes,
    config: Config,
    engine: Engine,
    data_root: Path,
    received_at: datetime,
) -> IngestionResult:
    parsed = parse_reply(
        raw,
        mood_regex=config.parsing.mood_regex,
        tag_regex=config.parsing.tag_regex,
    )

    # Idempotency: if we've already ingested this message-id, no-op early.
    with session_scope(engine) as session:
        if is_ingested(session, parsed.message_id):
            entry_date = _entry_date_from_db_or_parsed(session, parsed)
            return IngestionResult(ingested=False, entry_date=entry_date, message_id=parsed.message_id)

    entry_date = _resolve_entry_date(parsed, engine)

    # Per-date lock: serialize concurrent same-date ingestions.
    with entry_lock(data_root, _date(entry_date)):
        paths = entry_paths_for(data_root, _date(entry_date))
        # Track resources written so we can roll them back on failure.
        created_dirs: list[Path] = []
        created_files: list[Path] = []

        try:
            existing_doc = read_entry(paths.entry_md) if paths.entry_md.exists() else None

            # Cap attachments per config.
            photos = [a for a in parsed.attachments if a.kind == "photo"][: config.parsing.max_photos]
            videos = [a for a in parsed.attachments if a.kind == "video"][: config.parsing.max_videos]

            # Write raw .eml *first* — this is the canonical input record.
            paths.raw_dir.mkdir(parents=True, exist_ok=True)
            created_dirs.append(paths.raw_dir)
            received_utc = received_at.astimezone(timezone.utc)
            eml_filename = raw_eml_filename(received_utc)
            eml_path = paths.raw_dir / eml_filename
            eml_path.write_bytes(raw)
            created_files.append(eml_path)

            # Save originals + derive web/thumb/poster.
            photo_artifacts: list[tuple[AttachmentMaterial, AttachmentArtifacts]] = []
            for material in photos:
                art = derive_photo(
                    original_bytes=material.content,
                    original_filename=material.filename,
                    originals_dir=paths.originals_dir,
                    web_dir=paths.web_dir,
                    thumbs_dir=paths.thumbs_dir,
                )
                photo_artifacts.append((material, art))
                _track_artifact_files(art, created_files)

            video_artifacts: list[tuple[AttachmentMaterial, AttachmentArtifacts]] = []
            for material in videos:
                art = derive_video_poster(
                    original_bytes=material.content,
                    original_filename=material.filename,
                    originals_dir=paths.originals_dir,
                    thumbs_dir=paths.thumbs_dir,
                )
                video_artifacts.append((material, art))
                _track_artifact_files(art, created_files)

            # Compose new EntryDocument. If a prior doc exists, append this section's body
            # and union the tags + media.
            doc = _compose_entry_doc(
                entry_date=entry_date,
                parsed=parsed,
                received_utc=received_utc,
                eml_filename=eml_filename,
                photos=photo_artifacts,
                videos=video_artifacts,
                existing=existing_doc,
            )
            write_entry(paths.entry_md, doc)
            created_files.append(paths.entry_md)

            # Upsert into SQLite (entries + tags + media + ingested_messages).
            with session_scope(engine) as session:
                upsert_entry(
                    session,
                    EntryRecord(
                        date=entry_date,
                        mood=doc.mood,
                        body_text=doc.body,
                        body_md=doc.body,
                        created_at=doc.created_at,
                        updated_at=doc.updated_at,
                    ),
                )
                replace_tags(session, entry_date, list(doc.tags))
                replace_media(
                    session,
                    entry_date,
                    [MediaInput(kind="photo", filename=p.filename, caption=p.caption) for p in doc.photos]
                    + [MediaInput(kind="video", filename=v.filename, caption=v.caption) for v in doc.videos],
                )
                record_ingested(
                    session,
                    message_id=parsed.message_id,
                    date=entry_date,
                    eml_path=str(eml_path.relative_to(paths.dir)),
                    ingested_at=received_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
        except BaseException:
            _rollback_files(created_files, created_dirs, paths)
            raise

    return IngestionResult(ingested=True, entry_date=entry_date, message_id=parsed.message_id)


def _date(s: str):
    from datetime import date
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def _resolve_entry_date(parsed: ParsedReply, engine: Engine) -> str:
    """Map a reply to its entry date. Prefer the In-Reply-To anchor; else use the
    Date header in the configured tz; else today (UTC)."""
    if parsed.in_reply_to:
        with session_scope(engine) as session:
            pending = find_prompt_by_message_id(session, parsed.in_reply_to)
        if pending is not None:
            return pending.date
    if parsed.date_header is not None:
        return parsed.date_header.astimezone(timezone.utc).date().isoformat()
    return datetime.now(tz=timezone.utc).date().isoformat()


def _entry_date_from_db_or_parsed(session, parsed: ParsedReply) -> str:
    from driftnote.repository.ingested import get_ingested
    rec = get_ingested(session, parsed.message_id)
    if rec is not None:
        return rec.date
    return parsed.date_header.astimezone(timezone.utc).date().isoformat() if parsed.date_header else datetime.now(tz=timezone.utc).date().isoformat()


def _compose_entry_doc(
    *,
    entry_date: str,
    parsed: ParsedReply,
    received_utc: datetime,
    eml_filename: str,
    photos: list[tuple[AttachmentMaterial, AttachmentArtifacts]],
    videos: list[tuple[AttachmentMaterial, AttachmentArtifacts]],
    existing: EntryDocument | None,
) -> EntryDocument:
    iso_now = received_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    new_section = parsed.body.strip("\n")

    if existing is None:
        body = new_section + ("\n" if new_section else "")
        tags = list(parsed.tags)
        photo_refs = [PhotoRef(filename=m.filename) for m, _ in photos]
        video_refs = [VideoRef(filename=m.filename) for m, _ in videos]
        return EntryDocument(
            date=_date(entry_date),
            mood=parsed.mood,
            tags=tags,
            photos=photo_refs,
            videos=video_refs,
            created_at=iso_now,
            updated_at=iso_now,
            sources=[f"raw/{eml_filename}"],
            body=body,
        )

    # Append a new section separated by ---.
    appended_body = (existing.body.rstrip("\n") + "\n\n---\n\n" + new_section).rstrip("\n") + "\n"
    union_tags: list[str] = list(existing.tags)
    seen = set(union_tags)
    for t in parsed.tags:
        if t not in seen:
            seen.add(t)
            union_tags.append(t)
    photo_refs = list(existing.photos) + [PhotoRef(filename=m.filename) for m, _ in photos]
    video_refs = list(existing.videos) + [VideoRef(filename=m.filename) for m, _ in videos]
    sources = list(existing.sources) + [f"raw/{eml_filename}"]
    return EntryDocument(
        date=_date(entry_date),
        mood=existing.mood or parsed.mood,
        tags=union_tags,
        photos=photo_refs,
        videos=video_refs,
        created_at=existing.created_at,
        updated_at=iso_now,
        sources=sources,
        body=appended_body,
    )


def _track_artifact_files(art: AttachmentArtifacts, sink: list[Path]) -> None:
    for p in (art.original_path, art.web_path, art.thumb_path):
        if p is not None:
            sink.append(p)


def _rollback_files(files: list[Path], _dirs: list[Path], paths: EntryPaths) -> None:
    """Remove any files created during a failed ingest. Empty subdirs are removed too.

    The whole-entry directory is removed only if it was created in this call (i.e.
    no prior entry.md existed). We approximate this by checking whether the entry.md
    is present and not in `files` (meaning it pre-existed).
    """
    for f in files:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass
    # Cleanup obviously-empty subdirs we created.
    for sub in (paths.raw_dir, paths.web_dir, paths.thumbs_dir, paths.originals_dir):
        if sub.exists() and not any(sub.iterdir()):
            try:
                sub.rmdir()
            except OSError:
                pass
    if paths.dir.exists() and not any(paths.dir.iterdir()):
        try:
            shutil.rmtree(paths.dir)
        except OSError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_ingest_pipeline.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/ingest/pipeline.py tests/integration/test_ingest_pipeline.py
git commit -m "feat(ingest): orchestrated pipeline with rollback + idempotency"
```

---

### Chunk 6 closeout

**Acceptance criteria:**
- [ ] All Chunks 1–6 tests pass: `uv run pytest -v` (≥81 tests).
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] `tests/fixtures/images/` contains `tiny.jpg`, `tiny.heic`, `tiny.mov`.
- [ ] 3 task commits in this chunk with conventional-commit prefixes.

**Hand-off:** With ingestion complete, Chunks 7 (scheduler+jobs), 8 (digest rendering), and 9 (web layer) can be developed in parallel worktrees.

---

## Chunk 7: Scheduler, jobs, alerts

**Outcome of this chunk:** APScheduler-based runner with a `job_run` context manager that records each scheduled invocation in SQLite. Concrete jobs: daily prompt send, IMAP poll → ingest, disk-usage check with threshold alerts. Self-emailing alerts module with 24-hour dedup. Digest jobs are introduced in Chunk 8 alongside the digest renderers.

### Task 7.1: `alerts.py` — self-email with 24h dedup

**Files:**
- Create: `src/driftnote/alerts.py`
- Create: `tests/unit/test_alerts.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for alert dispatch with 24h dedup."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.alerts import AlertSender, dispatch_alert
from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import finish_job_run, record_job_run


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


class _FakeSender(AlertSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []  # (kind, subject, body)

    async def send(self, *, kind: str, subject: str, body: str) -> None:
        self.sent.append((kind, subject, body))


def test_dispatch_alert_sends_first_time(engine: Engine) -> None:
    sender = _FakeSender()
    import asyncio
    asyncio.run(
        dispatch_alert(
            engine=engine,
            sender=sender,
            kind="imap_auth",
            subject="IMAP login failing",
            body="repeated failure",
            now="2026-05-06T20:00:00Z",
        )
    )
    assert sender.sent == [("imap_auth", "IMAP login failing", "repeated failure")]


def test_dispatch_alert_dedups_within_24h(engine: Engine) -> None:
    # Pre-populate a recent alert of the same kind.
    with session_scope(engine) as session:
        rid = record_job_run(session, job="alert", started_at="2026-05-06T08:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-05-06T08:00:01Z",
            status="error",
            error_kind="imap_auth",
            error_message="prior alert",
        )

    sender = _FakeSender()
    import asyncio
    asyncio.run(
        dispatch_alert(
            engine=engine,
            sender=sender,
            kind="imap_auth",
            subject="again",
            body="dup",
            now="2026-05-06T20:00:00Z",
        )
    )
    assert sender.sent == []  # deduped


def test_dispatch_alert_records_a_job_run_row(engine: Engine) -> None:
    sender = _FakeSender()
    import asyncio
    asyncio.run(
        dispatch_alert(
            engine=engine,
            sender=sender,
            kind="disk_warn",
            subject="disk 80%",
            body="...",
            now="2026-05-06T22:00:00Z",
        )
    )
    from driftnote.repository.jobs import last_run
    with session_scope(engine) as session:
        row = last_run(session, "alert")
    assert row is not None
    assert row.error_kind == "disk_warn"
    assert row.status == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_alerts.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/alerts.py`**

```python
"""Self-emailing alerts with 24h dedup keyed on `error_kind`.

Callers pass an `AlertSender` so tests can substitute an in-memory fake while
production wires in an SMTP-backed sender.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.repository.jobs import (
    finish_job_run,
    recent_alerts_of_kind,
    record_job_run,
)


class AlertSender(Protocol):
    async def send(self, *, kind: str, subject: str, body: str) -> None: ...


async def dispatch_alert(
    *,
    engine: Engine,
    sender: AlertSender,
    kind: str,
    subject: str,
    body: str,
    now: str,
) -> None:
    """Send an alert email, deduplicated against any prior alert of the same `kind`
    within the last 24 hours. Always records a job_runs row with job='alert'."""
    with session_scope(engine) as session:
        recent = recent_alerts_of_kind(session, error_kind=kind, now=now, hours=24)

    run_id: int
    with session_scope(engine) as session:
        run_id = record_job_run(session, job="alert", started_at=now)

    if recent:
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=now,
                status="ok",
                detail="deduped",
                error_kind=kind,
            )
        return

    try:
        await sender.send(kind=kind, subject=subject, body=body)
    except Exception as exc:
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=now,
                status="error",
                error_kind=kind,
                error_message=str(exc)[:2000],
            )
        raise

    with session_scope(engine) as session:
        finish_job_run(
            session,
            run_id=run_id,
            finished_at=now,
            status="ok",
            detail="sent",
            error_kind=kind,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_alerts.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/alerts.py tests/unit/test_alerts.py
git commit -m "feat(alerts): self-email dispatch with 24h dedup"
```

---

### Task 7.2: `scheduler/runner.py` — APScheduler + job_run context manager

**Files:**
- Create: `src/driftnote/scheduler/__init__.py`
- Create: `src/driftnote/scheduler/runner.py`
- Create: `tests/unit/test_scheduler_runner.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for the job_run context manager + APScheduler bootstrap."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import freezegun
import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import last_run
from driftnote.scheduler.runner import build_scheduler, job_run


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def test_job_run_records_ok_on_success(engine: Engine) -> None:
    with freezegun.freeze_time("2026-05-06T21:00:00Z"):
        with job_run(engine, "imap_poll") as run:
            run.detail("ingested 1")
    with session_scope(engine) as session:
        row = last_run(session, "imap_poll")
    assert row is not None
    assert row.status == "ok"
    assert row.detail == "ingested 1"
    assert row.finished_at is not None


def test_job_run_records_error_on_exception(engine: Engine) -> None:
    with freezegun.freeze_time("2026-05-06T21:00:00Z"):
        with pytest.raises(RuntimeError):
            with job_run(engine, "imap_poll") as run:
                run.set_error_kind("imap_auth")
                raise RuntimeError("boom")
    with session_scope(engine) as session:
        row = last_run(session, "imap_poll")
    assert row is not None
    assert row.status == "error"
    assert row.error_kind == "imap_auth"
    assert "boom" in (row.error_message or "")


def test_build_scheduler_uses_configured_timezone() -> None:
    sched = build_scheduler(timezone="Europe/London")
    assert str(sched.timezone) == "Europe/London"


def test_build_scheduler_starts_paused() -> None:
    """build_scheduler returns a configured but not-yet-running scheduler."""
    sched = build_scheduler(timezone="Europe/London")
    assert sched.running is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_scheduler_runner.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement scheduler module**

`src/driftnote/scheduler/__init__.py`:

```python
"""Scheduler: APScheduler runner + concrete jobs."""
```

`src/driftnote/scheduler/runner.py`:

```python
"""Async APScheduler runner + a `job_run` context manager that records each
scheduled invocation as a row in `job_runs` (running → ok|error|warn)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Self
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.repository.jobs import finish_job_run, record_job_run


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _RunHandle:
    """Returned by `job_run(...)`. Callers fill in `detail` / `error_kind`."""

    _detail: str | None = None
    _error_kind: str | None = None
    _status: str = "ok"

    def detail(self, text: str) -> None:
        self._detail = text

    def set_error_kind(self, kind: str) -> None:
        self._error_kind = kind

    def warn(self) -> None:
        self._status = "warn"


@contextmanager
def job_run(engine: Engine, job: str) -> Iterator[_RunHandle]:
    """Wrap one scheduled-job invocation. Records `running` on enter; on exit
    records `ok`, `warn`, or `error` and captures any raised exception."""
    started_at = _utcnow_iso()
    with session_scope(engine) as session:
        run_id = record_job_run(session, job=job, started_at=started_at)

    handle = _RunHandle()
    try:
        yield handle
    except BaseException as exc:
        finished_at = _utcnow_iso()
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=finished_at,
                status="error",
                detail=handle._detail,
                error_kind=handle._error_kind,
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
            )
        raise
    else:
        finished_at = _utcnow_iso()
        with session_scope(engine) as session:
            finish_job_run(
                session,
                run_id=run_id,
                finished_at=finished_at,
                status=handle._status,
                detail=handle._detail,
                error_kind=handle._error_kind,
            )


def build_scheduler(*, timezone: str) -> AsyncIOScheduler:
    """Return a configured (but not started) AsyncIOScheduler in the given tz."""
    tz = ZoneInfo(timezone)
    return AsyncIOScheduler(timezone=tz)


def cron(expr: str, tz: str) -> CronTrigger:
    """Build a CronTrigger from a 5-field cron string in the given tz."""
    minute, hour, day, month, day_of_week = expr.split()
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=ZoneInfo(tz),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_scheduler_runner.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/scheduler/__init__.py src/driftnote/scheduler/runner.py tests/unit/test_scheduler_runner.py
git commit -m "feat(scheduler): runner + job_run context manager + cron helper"
```

---

### Task 7.3: `scheduler/prompt_job.py` — daily prompt sender

**Files:**
- Create: `src/driftnote/scheduler/prompt_job.py`
- Create: `tests/integration/test_scheduler_prompt_job.py`

- [ ] **Step 1: Write failing test**

```python
"""Integration test: the daily prompt job sends a prompt and records pending_prompts."""

from __future__ import annotations

import asyncio
from datetime import date as _date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.mail.transport import SmtpTransport
from driftnote.repository.ingested import find_prompt_by_message_id
from driftnote.scheduler.prompt_job import run_prompt_job
from tests.conftest import MailServer


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def _smtp(mail_server: MailServer) -> SmtpTransport:
    return SmtpTransport(
        host=mail_server.host,
        port=mail_server.smtp_port,
        tls=False,
        starttls=False,
        username=mail_server.user,
        password=mail_server.password,
        sender_address=mail_server.address,
        sender_name="Driftnote",
    )


def test_run_prompt_job_sends_and_anchors(mail_server: MailServer, engine: Engine) -> None:
    smtp = _smtp(mail_server)
    asyncio.run(
        run_prompt_job(
            engine=engine,
            smtp=smtp,
            recipient=mail_server.address,
            subject_template="[Driftnote] How was {date}?",
            body_template_text="Hi! Reply with `Mood: <emoji>` and your day. — {date}",
            today=_date(2026, 5, 6),
        )
    )
    with session_scope(engine) as session:
        # We don't know the message-id ahead of time; look up by date instead.
        from driftnote.models import PendingPrompt
        from sqlalchemy import select
        rec = session.scalar(select(PendingPrompt).where(PendingPrompt.date == "2026-05-06"))
    assert rec is not None
    msg_id = rec.message_id
    found = find_prompt_by_message_id_via_engine(engine, msg_id)
    assert found is not None
    assert found.date == "2026-05-06"


def find_prompt_by_message_id_via_engine(engine: Engine, mid: str):
    from driftnote.repository.ingested import find_prompt_by_message_id
    with session_scope(engine) as session:
        return find_prompt_by_message_id(session, mid)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_scheduler_prompt_job.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/scheduler/prompt_job.py`**

```python
"""Daily prompt job: render and send the prompt; record pending_prompts row."""

from __future__ import annotations

from datetime import date as _date

from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.mail.smtp import send_email
from driftnote.mail.transport import SmtpTransport
from driftnote.repository.ingested import record_pending_prompt


async def run_prompt_job(
    *,
    engine: Engine,
    smtp: SmtpTransport,
    recipient: str,
    subject_template: str,
    body_template_text: str,
    today: _date,
) -> None:
    """Render the prompt for `today`, send it via SMTP, and persist the
    outgoing Message-ID as the date anchor for matching incoming replies."""
    iso = today.isoformat()
    subject = subject_template.format(date=iso)
    body = body_template_text.format(date=iso)

    message_id = await send_email(
        smtp,
        recipient=recipient,
        subject=subject,
        body_text=body,
    )

    with session_scope(engine) as session:
        record_pending_prompt(
            session,
            date=iso,
            message_id=message_id,
            sent_at=_iso_now_utc(),
        )


def _iso_now_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_scheduler_prompt_job.py -v`
Expected: 1 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/scheduler/prompt_job.py tests/integration/test_scheduler_prompt_job.py
git commit -m "feat(scheduler): daily prompt sender with pending_prompts anchor"
```

---

### Task 7.4: `scheduler/poll_job.py` — IMAP poll → ingest

**Files:**
- Create: `src/driftnote/scheduler/poll_job.py`
- Create: `tests/integration/test_scheduler_poll_job.py`

- [ ] **Step 1: Write failing test**

```python
"""Integration test: poll job fetches UNSEEN, ingests, then moves to Processed."""

from __future__ import annotations

import asyncio
import imaplib
from datetime import date as _date
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.mail.transport import ImapTransport
from driftnote.repository.entries import get_entry
from driftnote.repository.ingested import (
    get_ingested,
    is_ingested,
    record_pending_prompt,
)
from driftnote.scheduler.poll_job import run_poll_job
from tests.conftest import MailServer


def _imap(mail_server: MailServer) -> ImapTransport:
    return ImapTransport(
        host=mail_server.host,
        port=mail_server.imap_port,
        tls=False,
        username=mail_server.user,
        password=mail_server.password,
        inbox_folder="INBOX",
        processed_folder="INBOX.Processed",
    )


def _drop_reply(mail_server: MailServer, *, in_reply_to: str | None, body: str) -> str:
    msg = EmailMessage()
    msg["From"] = mail_server.address
    msg["To"] = mail_server.address
    msg["Subject"] = "Re: [Driftnote] How was 2026-05-06?"
    msg["Message-ID"] = make_msgid(domain="example")
    msg["Date"] = "Wed, 06 May 2026 21:30:15 +0000"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)

    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.append("INBOX", "", imaplib.Time2Internaldate(0), msg.as_bytes())
    mb.logout()
    return msg["Message-ID"]


@pytest.fixture(autouse=True)
def _clean_mailbox(mail_server: MailServer):
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    for folder in ("INBOX", "INBOX.Processed"):
        try:
            mb.select(folder)
            mb.store("1:*", "+FLAGS", r"\Deleted")
            mb.expunge()
        except Exception:
            pass
    try:
        mb.create("INBOX.Processed")
    except Exception:
        pass
    mb.logout()


@pytest.fixture
def engine_data(tmp_path: Path) -> tuple[Engine, Path]:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    return eng, tmp_path / "data"


def test_poll_ingests_message_and_moves_to_processed(mail_server: MailServer, engine_data) -> None:
    engine, data_root = engine_data
    with session_scope(engine) as session:
        record_pending_prompt(
            session, date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>", sent_at="2026-05-06T21:00:00Z",
        )
    mid = _drop_reply(
        mail_server,
        in_reply_to="<prompt-2026-05-06@driftnote>",
        body="Mood: 💪\n\nGood day. #work",
    )

    from driftnote.config import (
        BackupConfig, Config, DigestsConfig, DiskConfig, EmailConfig,
        ParsingConfig, PromptConfig, ScheduleConfig, Secrets,
    )
    from pydantic import SecretStr

    cfg = Config(
        schedule=ScheduleConfig(
            daily_prompt="0 21 * * *", weekly_digest="0 8 * * 1",
            monthly_digest="0 8 1 * *", yearly_digest="0 8 1 1 *",
            imap_poll="*/5 * * * *", timezone="Europe/London",
        ),
        email=EmailConfig(
            imap_folder="INBOX", imap_processed_folder="INBOX.Processed",
            recipient=mail_server.address, sender_name="Driftnote",
            imap_host=mail_server.host, imap_port=mail_server.imap_port, imap_tls=False,
            smtp_host="x", smtp_port=587, smtp_tls=False, smtp_starttls=False,
        ),
        prompt=PromptConfig(subject_template="x", body_template="t.j2"),
        parsing=ParsingConfig(mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)", max_photos=4, max_videos=2),
        digests=DigestsConfig(weekly_enabled=True, monthly_enabled=True, yearly_enabled=True),
        backup=BackupConfig(retain_months=12, encrypt=False, age_key_path=""),
        disk=DiskConfig(warn_percent=80, alert_percent=95, check_cron="0 */6 * * *", data_path=str(data_root)),
        secrets=Secrets(
            gmail_user=mail_server.user, gmail_app_password=SecretStr(mail_server.password),
            cf_access_aud="aud", cf_team_domain="t.example.com",
        ),
    )

    asyncio.run(run_poll_job(config=cfg, engine=engine, data_root=data_root, imap=_imap(mail_server)))

    with session_scope(engine) as session:
        entry = get_entry(session, "2026-05-06")
        ing = get_ingested(session, mid)
    assert entry is not None
    assert ing is not None
    assert ing.imap_moved == 1

    # Message has moved out of Inbox into Processed.
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select("INBOX")
    typ, data = mb.search(None, "ALL")
    assert data == [b""]  # empty INBOX
    mb.select("INBOX.Processed")
    typ, data = mb.search(None, "ALL")
    assert data and data[0]
    mb.logout()


def test_poll_retries_imap_move_on_imap_moved_zero(mail_server: MailServer, engine_data, monkeypatch: pytest.MonkeyPatch) -> None:
    """If a previous poll ingested but failed to move, the next poll should
    retry only the IMAP move without re-ingesting."""
    engine, data_root = engine_data
    with session_scope(engine) as session:
        record_pending_prompt(
            session, date="2026-05-06",
            message_id="<prompt-2026-05-06@driftnote>", sent_at="t",
        )
    _drop_reply(mail_server, in_reply_to="<prompt-2026-05-06@driftnote>",
                body="Mood: 💪\n\nrecovered #work")

    # First call: succeed at ingest, simulate failure on move.
    from driftnote.scheduler import poll_job as _poll

    async def _fail_move(*args, **kwargs):
        raise RuntimeError("simulated IMAP move failure")

    real_move = _poll._move_to_processed
    monkeypatch.setattr(_poll, "_move_to_processed", _fail_move)

    from driftnote.config import (
        BackupConfig, Config, DigestsConfig, DiskConfig, EmailConfig,
        ParsingConfig, PromptConfig, ScheduleConfig, Secrets,
    )
    from pydantic import SecretStr

    cfg = Config(
        schedule=ScheduleConfig(
            daily_prompt="0 21 * * *", weekly_digest="0 8 * * 1",
            monthly_digest="0 8 1 * *", yearly_digest="0 8 1 1 *",
            imap_poll="*/5 * * * *", timezone="Europe/London",
        ),
        email=EmailConfig(
            imap_folder="INBOX", imap_processed_folder="INBOX.Processed",
            recipient=mail_server.address, sender_name="Driftnote",
            imap_host=mail_server.host, imap_port=mail_server.imap_port, imap_tls=False,
            smtp_host="x", smtp_port=587, smtp_tls=False, smtp_starttls=False,
        ),
        prompt=PromptConfig(subject_template="x", body_template="t.j2"),
        parsing=ParsingConfig(mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)", max_photos=4, max_videos=2),
        digests=DigestsConfig(weekly_enabled=True, monthly_enabled=True, yearly_enabled=True),
        backup=BackupConfig(retain_months=12, encrypt=False, age_key_path=""),
        disk=DiskConfig(warn_percent=80, alert_percent=95, check_cron="0 */6 * * *", data_path=str(data_root)),
        secrets=Secrets(
            gmail_user=mail_server.user, gmail_app_password=SecretStr(mail_server.password),
            cf_access_aud="aud", cf_team_domain="t.example.com",
        ),
    )

    with pytest.raises(RuntimeError):
        asyncio.run(run_poll_job(config=cfg, engine=engine, data_root=data_root, imap=_imap(mail_server)))

    # imap_moved still 0
    with session_scope(engine) as session:
        from driftnote.repository.ingested import pending_imap_moves
        pending = pending_imap_moves(session)
    assert len(pending) == 1

    # Second call: restore real move, message should be moved without re-ingesting.
    monkeypatch.setattr(_poll, "_move_to_processed", real_move)
    asyncio.run(run_poll_job(config=cfg, engine=engine, data_root=data_root, imap=_imap(mail_server)))

    with session_scope(engine) as session:
        from driftnote.repository.ingested import pending_imap_moves
        pending = pending_imap_moves(session)
    assert pending == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_scheduler_poll_job.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/scheduler/poll_job.py`**

```python
"""IMAP poll job: fetch UNSEEN replies, ingest each, then move to Processed.

Two paths:
- Normal: per-message UNSEEN → ingest → IMAP-move → set imap_moved=1.
- Retry: at job start, drain any rows with imap_moved=0 from prior polls and
  attempt the IMAP move again. This implements the spec §3.B retry path
  cleanly without the ingest pipeline needing to know about it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine

from driftnote.config import Config
from driftnote.db import session_scope
from driftnote.ingest.pipeline import ingest_one
from driftnote.mail.imap import RawMessage, move_to_processed as _move_to_processed, poll_unseen
from driftnote.mail.transport import ImapTransport
from driftnote.repository.ingested import (
    is_ingested,
    mark_imap_moved,
    pending_imap_moves,
)


async def run_poll_job(
    *,
    config: Config,
    engine: Engine,
    data_root: Path,
    imap: ImapTransport,
) -> None:
    # Step 1: retry any prior IMAP-move failures.
    with session_scope(engine) as session:
        retry_targets = pending_imap_moves(session)
    for row in retry_targets:
        await _move_to_processed(imap, message_id=row.message_id)
        with session_scope(engine) as session:
            mark_imap_moved(session, row.message_id)

    # Step 2: poll new UNSEEN messages.
    async for raw_msg in poll_unseen(imap):
        await _handle_one(raw_msg, config=config, engine=engine, data_root=data_root, imap=imap)


async def _handle_one(
    raw_msg: RawMessage,
    *,
    config: Config,
    engine: Engine,
    data_root: Path,
    imap: ImapTransport,
) -> None:
    # Idempotency check upfront — if already ingested, skip directly to IMAP move
    # (the ingest pipeline also no-ops, but this avoids re-parsing).
    with session_scope(engine) as session:
        already = is_ingested(session, raw_msg.message_id)

    if not already:
        ingest_one(
            raw=raw_msg.raw_bytes,
            config=config,
            engine=engine,
            data_root=data_root,
            received_at=datetime.now(tz=timezone.utc),
        )

    await _move_to_processed(imap, message_id=raw_msg.message_id)
    with session_scope(engine) as session:
        mark_imap_moved(session, raw_msg.message_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_scheduler_poll_job.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/scheduler/poll_job.py tests/integration/test_scheduler_poll_job.py
git commit -m "feat(scheduler): IMAP poll → ingest → move job with retry path"
```

---

### Task 7.5: `scheduler/disk_job.py` — disk-usage check + threshold alerts

**Files:**
- Create: `src/driftnote/scheduler/disk_job.py`
- Create: `tests/unit/test_scheduler_disk_job.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for disk-usage threshold tracking + alert triggering."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.alerts import AlertSender
from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.ingested import (
    clear_threshold_crossed,
    get_threshold_crossed_at,
    record_threshold_crossed,
)
from driftnote.repository.jobs import last_run
from driftnote.scheduler.disk_job import run_disk_check


class _FakeSender(AlertSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, *, kind: str, subject: str, body: str) -> None:
        self.sent.append((kind, subject, body))


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def test_disk_check_no_alert_below_warn(engine: Engine) -> None:
    sender = _FakeSender()
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (1_000, 5_000),  # 20% used
            now="2026-05-06T22:00:00Z",
        )
    )
    assert sender.sent == []


def test_disk_check_alerts_on_warn_crossing(engine: Engine) -> None:
    sender = _FakeSender()
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (8_500, 10_000),  # 85%
            now="2026-05-06T22:00:00Z",
        )
    )
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == "disk_warn"


def test_disk_check_does_not_realert_after_warn_already_crossed(engine: Engine) -> None:
    sender = _FakeSender()
    with session_scope(engine) as session:
        record_threshold_crossed(session, threshold=80, at="2026-05-05T08:00:00Z")
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (8_500, 10_000),
            now="2026-05-06T22:00:00Z",
        )
    )
    assert sender.sent == []


def test_disk_check_clears_warn_state_after_drop_below(engine: Engine) -> None:
    sender = _FakeSender()
    with session_scope(engine) as session:
        record_threshold_crossed(session, threshold=80, at="2026-05-05T08:00:00Z")
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (5_000, 10_000),
            now="2026-05-06T22:00:00Z",
        )
    )
    with session_scope(engine) as session:
        assert get_threshold_crossed_at(session, 80) is None


def test_disk_check_records_job_run_with_detail(engine: Engine) -> None:
    sender = _FakeSender()
    asyncio.run(
        run_disk_check(
            engine=engine,
            sender=sender,
            data_path="/",
            warn_percent=80,
            alert_percent=95,
            measure=lambda _path: (8_500, 10_000),
            now="2026-05-06T22:00:00Z",
        )
    )
    with session_scope(engine) as session:
        row = last_run(session, "disk_check")
    assert row is not None
    assert row.status == "ok"
    assert row.detail is not None
    assert "8500" in row.detail
    assert "10000" in row.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_scheduler_disk_job.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/scheduler/disk_job.py`**

```python
"""Disk-usage check job: measure usage, manage threshold-state edges, alert on crossing."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable

from sqlalchemy import Engine

from driftnote.alerts import AlertSender, dispatch_alert
from driftnote.db import session_scope
from driftnote.repository.ingested import (
    clear_threshold_crossed,
    get_threshold_crossed_at,
    record_threshold_crossed,
)
from driftnote.repository.jobs import finish_job_run, record_job_run

DiskMeasure = Callable[[str], tuple[int, int]]
"""Returns (used_bytes, total_bytes) for the given path. Defaults to shutil.disk_usage."""


def _default_measure(path: str) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.used, usage.total


async def run_disk_check(
    *,
    engine: Engine,
    sender: AlertSender,
    data_path: str,
    warn_percent: int,
    alert_percent: int,
    measure: DiskMeasure | None = None,
    now: str,
) -> None:
    measure_fn = measure or _default_measure
    used, total = measure_fn(data_path)
    percent = (used / total) * 100 if total else 0.0
    detail = json.dumps({"used_bytes": used, "total_bytes": total, "percent": round(percent, 2)})

    with session_scope(engine) as session:
        run_id = record_job_run(session, job="disk_check", started_at=now)

    try:
        await _maybe_alert(
            engine=engine, sender=sender,
            threshold=warn_percent, kind="disk_warn",
            percent=percent, used=used, total=total, now=now,
        )
        await _maybe_alert(
            engine=engine, sender=sender,
            threshold=alert_percent, kind="disk_alert",
            percent=percent, used=used, total=total, now=now,
        )
    except Exception as exc:
        with session_scope(engine) as session:
            finish_job_run(
                session, run_id=run_id, finished_at=now, status="error",
                detail=detail, error_kind="disk_check", error_message=str(exc)[:2000],
            )
        raise

    with session_scope(engine) as session:
        finish_job_run(session, run_id=run_id, finished_at=now, status="ok", detail=detail)


async def _maybe_alert(
    *,
    engine: Engine,
    sender: AlertSender,
    threshold: int,
    kind: str,
    percent: float,
    used: int,
    total: int,
    now: str,
) -> None:
    with session_scope(engine) as session:
        prior = get_threshold_crossed_at(session, threshold)

    if percent >= threshold:
        if prior is not None:
            return  # already alerted; don't re-alert until the level drops below
        with session_scope(engine) as session:
            record_threshold_crossed(session, threshold=threshold, at=now)
        await dispatch_alert(
            engine=engine,
            sender=sender,
            kind=kind,
            subject=f"Driftnote disk usage at {percent:.1f}%",
            body=f"used={used}B total={total}B percent={percent:.1f}% threshold={threshold}%",
            now=now,
        )
    else:
        if prior is not None:
            with session_scope(engine) as session:
                clear_threshold_crossed(session, threshold)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_scheduler_disk_job.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/scheduler/disk_job.py tests/unit/test_scheduler_disk_job.py
git commit -m "feat(scheduler): disk-usage threshold check with stateful alerts"
```

---

### Chunk 7 closeout

**Acceptance criteria:**
- [ ] All Chunks 1–7 tests pass: `uv run pytest -v`.
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] 5 task commits in this chunk with conventional-commit prefixes.

**Hand-off:** Chunk 8 (digest rendering) and Chunk 9 (web layer) can be developed in parallel from the end of Chunk 7. Chunk 8 also adds `scheduler/digest_jobs.py` since renderer + scheduler binding is one logical unit.

---

## Chunk 8: Digest rendering

**Outcome of this chunk:** Pure rendering functions that take SQL-derived data and produce email-ready HTML for weekly, monthly, and yearly digests. Includes the moodboard renderer, the monthly highlights heuristic with progressive fallback, and the yearly contribution-grid. Plus `scheduler/digest_jobs.py` that ties each digest to its cron and an enable flag in config.

### Task 8.1: `digest/moodboard.py` + helpers

**Files:**
- Create: `src/driftnote/digest/__init__.py`
- Create: `src/driftnote/digest/moodboard.py`
- Create: `src/driftnote/digest/inputs.py`
- Create: `tests/unit/test_digest_moodboard.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for moodboard rendering helpers."""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.moodboard import (
    weekly_moodboard,
    monthly_moodboard_grid,
    yearly_moodboard_grid,
)


def _day(d: str, mood: str | None = "💪") -> DayInput:
    return DayInput(date=date.fromisoformat(d), mood=mood, tags=[], photo_thumb=None, body_html="")


def test_weekly_moodboard_seven_cells_with_emojis_or_dot() -> None:
    days = [_day("2026-04-27"), _day("2026-04-29", mood=None), _day("2026-05-03", mood="🎉")]
    cells = weekly_moodboard(week_start=date(2026, 4, 27), days=days)
    assert len(cells) == 7
    assert cells[0].emoji == "💪"
    assert cells[2].emoji is None  # Wed (no day with mood)
    assert cells[6].emoji == "🎉"
    assert cells[0].label == "Mon"


def test_monthly_moodboard_returns_calendar_rows() -> None:
    days = [_day("2026-05-01"), _day("2026-05-15", mood="🌧️"), _day("2026-05-31", mood="🎉")]
    rows = monthly_moodboard_grid(year=2026, month=5, days=days)
    # May 2026 spans 6 calendar weeks.
    assert len(rows) >= 5
    flat = [c for row in rows for c in row]
    moods = [c.emoji for c in flat if c.in_month and c.day_of_month == 1]
    assert moods == ["💪"]


def test_yearly_grid_53_weeks_max() -> None:
    days = [_day("2026-01-01"), _day("2026-12-31", mood="🌧️")]
    grid = yearly_moodboard_grid(year=2026, days=days)
    # 7 rows (Mon..Sun), <=53 columns
    assert len(grid) == 7
    assert all(len(row) <= 53 for row in grid)
    # Find the cell for 2026-01-01 and 2026-12-31; confirm emojis.
    cells = [c for row in grid for c in row if c.in_year]
    by_date = {c.date: c.emoji for c in cells}
    assert by_date[date(2026, 1, 1)] == "💪"
    assert by_date[date(2026, 12, 31)] == "🌧️"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_digest_moodboard.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `src/driftnote/digest/__init__.py`** (empty marker)

```python
"""Digest rendering: weekly, monthly, yearly."""
```

- [ ] **Step 4: Implement `src/driftnote/digest/inputs.py`** — input data structures

```python
"""Pydantic-friendly inputs for digest rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class DayInput:
    """One day's worth of data needed for digest rendering."""

    date: date
    mood: str | None
    tags: list[str]
    photo_thumb: str | None    # URL fragment / "cid:..." reference
    body_html: str             # rendered markdown → safe HTML


@dataclass(frozen=True)
class HighlightInput:
    date: date
    mood: str | None
    summary_html: str          # first ~2 sentences as HTML
    photo_thumb: str | None    # CID reference for inline image
```

- [ ] **Step 5: Implement `src/driftnote/digest/moodboard.py`**

```python
"""Moodboard renderers: weekly row, monthly calendar grid, yearly 7×53 grid."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from driftnote.digest.inputs import DayInput

_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class WeeklyCell:
    label: str          # "Mon" .. "Sun"
    date: date
    emoji: str | None


@dataclass(frozen=True)
class MonthlyCell:
    date: date
    in_month: bool      # False for grid pad cells outside this month
    day_of_month: int | None
    emoji: str | None


@dataclass(frozen=True)
class YearlyCell:
    date: date
    in_year: bool
    emoji: str | None


def weekly_moodboard(*, week_start: date, days: list[DayInput]) -> list[WeeklyCell]:
    """Return 7 cells starting at `week_start` (which must be a Monday)."""
    by_date = {d.date: d.mood for d in days}
    out: list[WeeklyCell] = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        out.append(WeeklyCell(label=_WEEKDAY_LABELS[i], date=d, emoji=by_date.get(d)))
    return out


def monthly_moodboard_grid(*, year: int, month: int, days: list[DayInput]) -> list[list[MonthlyCell]]:
    """Calendar grid: rows = weeks, columns = Mon..Sun. Cells outside the
    target month carry `in_month=False`."""
    by_date = {d.date: d.mood for d in days}

    first = date(year, month, 1)
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)

    # Snap to the Monday of the week containing the 1st.
    grid_start = first - timedelta(days=first.weekday())
    rows: list[list[MonthlyCell]] = []
    cur = grid_start
    while cur < next_first or cur.weekday() != 0:
        row: list[MonthlyCell] = []
        for _ in range(7):
            in_month = cur.month == month and cur.year == year
            row.append(MonthlyCell(
                date=cur,
                in_month=in_month,
                day_of_month=cur.day if in_month else None,
                emoji=by_date.get(cur) if in_month else None,
            ))
            cur += timedelta(days=1)
        rows.append(row)
    return rows


def yearly_moodboard_grid(*, year: int, days: list[DayInput]) -> list[list[YearlyCell]]:
    """GitHub-style contribution grid: 7 rows (Mon..Sun) × up to 53 columns."""
    by_date = {d.date: d.mood for d in days}
    first = date(year, 1, 1)
    last = date(year, 12, 31)

    grid_start = first - timedelta(days=first.weekday())
    columns: list[list[YearlyCell]] = []
    cur = grid_start
    while cur <= last or cur.weekday() != 0:
        col: list[YearlyCell] = []
        for _ in range(7):
            in_year = cur.year == year
            col.append(YearlyCell(date=cur, in_year=in_year, emoji=by_date.get(cur) if in_year else None))
            cur += timedelta(days=1)
        columns.append(col)
    # Transpose: rows = weekday (Mon..Sun), cols = week index.
    rows: list[list[YearlyCell]] = [[col[r] for col in columns] for r in range(7)]
    return rows
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_digest_moodboard.py -v`
Expected: 3 passed.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/digest/__init__.py src/driftnote/digest/inputs.py src/driftnote/digest/moodboard.py tests/unit/test_digest_moodboard.py
git commit -m "feat(digest): moodboard cell builders for week/month/year"
```

---

### Task 8.2: `digest/weekly.py` — week digest body builder

**Files:**
- Create: `src/driftnote/digest/weekly.py`
- Create: `tests/unit/test_digest_weekly.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for weekly digest body composition (HTML)."""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.weekly import build_weekly_digest


def _day(d: str, body: str = "<p>hi</p>", mood: str = "💪", tags: list[str] | None = None, thumb: str | None = None) -> DayInput:
    return DayInput(
        date=date.fromisoformat(d),
        mood=mood,
        tags=tags or [],
        photo_thumb=thumb,
        body_html=body,
    )


def test_subject_includes_week_range() -> None:
    digest = build_weekly_digest(
        week_start=date(2026, 4, 27),
        days=[_day("2026-04-27")],
        web_base_url="https://driftnote.example.com",
    )
    assert "2026-04-27" in digest.subject
    assert "2026-05-03" in digest.subject


def test_html_lists_every_day_section_in_order() -> None:
    digest = build_weekly_digest(
        week_start=date(2026, 4, 27),
        days=[_day("2026-04-29"), _day("2026-04-27"), _day("2026-05-02")],
        web_base_url="https://driftnote.example.com",
    )
    html = digest.html
    i_27 = html.index("2026-04-27")
    i_29 = html.index("2026-04-29")
    i_02 = html.index("2026-05-02")
    assert i_27 < i_29 < i_02


def test_html_includes_moodboard_row_with_emojis() -> None:
    digest = build_weekly_digest(
        week_start=date(2026, 4, 27),
        days=[_day("2026-04-27", mood="💪"), _day("2026-05-03", mood="🎉")],
        web_base_url="https://driftnote.example.com",
    )
    assert "💪" in digest.html
    assert "🎉" in digest.html


def test_html_links_to_web_ui() -> None:
    digest = build_weekly_digest(
        week_start=date(2026, 4, 27),
        days=[_day("2026-04-27")],
        web_base_url="https://driftnote.example.com",
    )
    assert "https://driftnote.example.com/entry/2026-04-27" in digest.html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_digest_weekly.py -v`

- [ ] **Step 3: Implement `src/driftnote/digest/weekly.py`**

```python
"""Weekly digest body builder.

Produces a `Digest(subject, html)` with:
- 7-emoji moodboard row at the top
- One section per day in chronological order with mood, tags, body HTML, optional thumbnail
- Footer with link to the web UI
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from driftnote.digest.inputs import DayInput
from driftnote.digest.moodboard import weekly_moodboard


@dataclass(frozen=True)
class Digest:
    subject: str
    html: str


def build_weekly_digest(
    *,
    week_start: date,
    days: list[DayInput],
    web_base_url: str,
) -> Digest:
    week_end = week_start + timedelta(days=6)
    subject = f"[Driftnote] Week of {week_start.isoformat()} → {week_end.isoformat()}"

    cells = weekly_moodboard(week_start=week_start, days=days)
    moodboard_html = "".join(
        f'<td style="text-align:center;padding:6px;font-size:24px">'
        f'<div style="font-size:11px;color:#888">{escape(c.label)}</div>'
        f'<div>{escape(c.emoji or "·")}</div>'
        f"</td>"
        for c in cells
    )

    days_sorted = sorted(days, key=lambda d: d.date)
    sections_html = "".join(_render_day_section(d, web_base_url=web_base_url) for d in days_sorted)

    footer_html = (
        f'<p style="margin-top:24px;color:#888"><a href="{escape(web_base_url)}">Open in Driftnote</a></p>'
    )

    body_html = f"""
    <html><body style="font-family:system-ui,sans-serif;max-width:640px;margin:auto;padding:16px">
      <h1 style="margin-bottom:8px">Week of {escape(week_start.isoformat())} → {escape(week_end.isoformat())}</h1>
      <table cellspacing="0" cellpadding="0" style="margin:8px 0 24px"><tr>{moodboard_html}</tr></table>
      {sections_html}
      {footer_html}
    </body></html>
    """.strip()

    return Digest(subject=subject, html=body_html)


def _render_day_section(d: DayInput, *, web_base_url: str) -> str:
    mood = escape(d.mood) if d.mood else ""
    tags = " ".join(f'<span style="color:#888;margin-right:6px">#{escape(t)}</span>' for t in d.tags)
    thumb_html = (
        f'<img src="{escape(d.photo_thumb)}" style="max-width:100%;border-radius:8px;margin-top:8px"/>'
        if d.photo_thumb else ""
    )
    return f"""
    <section style="margin:16px 0;padding-top:12px;border-top:1px solid #eee">
      <h2 style="margin:0">
        <a href="{escape(web_base_url)}/entry/{escape(d.date.isoformat())}" style="color:#222;text-decoration:none">
          {escape(d.date.isoformat())} <span style="font-size:24px">{mood}</span>
        </a>
      </h2>
      <p style="margin:4px 0 8px">{tags}</p>
      <div>{d.body_html}</div>
      {thumb_html}
    </section>
    """.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_digest_weekly.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/digest/weekly.py tests/unit/test_digest_weekly.py
git commit -m "feat(digest): weekly digest HTML builder"
```

---

### Task 8.3: `digest/monthly.py` — with progressive highlights

**Files:**
- Create: `src/driftnote/digest/monthly.py`
- Create: `tests/unit/test_digest_monthly.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for monthly digest builder including the progressive-highlights heuristic."""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.monthly import build_monthly_digest, select_highlights


def _day(d: str, *, mood: str = "💪", tags=None, thumb: str | None = None) -> DayInput:
    return DayInput(
        date=date.fromisoformat(d),
        mood=mood,
        tags=tags or [],
        photo_thumb=thumb,
        body_html="<p>body</p>",
    )


def test_select_highlights_prefers_photo_plus_rare_tag() -> None:
    days = [
        _day("2026-05-01", thumb="cid:1", tags=["work"]),                 # work appears 5×
        _day("2026-05-02", thumb="cid:2", tags=["holiday", "work"]),       # holiday rare
        _day("2026-05-03", thumb="cid:3", tags=["birthday"]),              # birthday rare, no photo
        _day("2026-05-04", thumb="cid:4", tags=["work"]),
        _day("2026-05-05", thumb="cid:5", tags=["work"]),
        _day("2026-05-06", thumb="cid:6", tags=["work"]),
    ]
    highlights = select_highlights(days, target=4)
    # 2026-05-02 qualifies (photo + rare tag). With only 1 qualifying, fallback expands.
    assert any(h.date == date(2026, 5, 2) for h in highlights)


def test_select_highlights_fallback_when_no_photo_plus_rare() -> None:
    """If nothing matches photo+rare, fall back to days with rare tag OR photo, then to most-photos."""
    days = [
        _day(f"2026-05-0{i}", thumb=f"cid:{i}", tags=["common"])
        for i in range(1, 8)
    ]
    highlights = select_highlights(days, target=4)
    # Length up to target — heuristic should still emit something.
    assert len(highlights) <= 4


def test_select_highlights_no_padding_when_few_candidates() -> None:
    """Heuristic does not pad: if nothing qualifies even after full fallback, emit fewer."""
    highlights = select_highlights([], target=4)
    assert highlights == []


def test_subject_is_month_year() -> None:
    digest = build_monthly_digest(year=2026, month=5, days=[_day("2026-05-01")], web_base_url="https://x")
    assert "2026" in digest.subject
    assert "May" in digest.subject or "05" in digest.subject


def test_html_includes_calendar_grid_and_stats() -> None:
    days = [_day("2026-05-01", tags=["work"]), _day("2026-05-15", mood="🌧️", tags=["rest"])]
    digest = build_monthly_digest(year=2026, month=5, days=days, web_base_url="https://x")
    assert "💪" in digest.html
    assert "🌧️" in digest.html
    assert "work" in digest.html or "Work" in digest.html
    assert "Stats" in digest.html or "stats" in digest.html or "entries" in digest.html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_digest_monthly.py -v`

- [ ] **Step 3: Implement `src/driftnote/digest/monthly.py`**

```python
"""Monthly digest builder.

Subject: `[Driftnote] Month YYYY` (e.g. "[Driftnote] May 2026")
Body:
- Calendar-grid moodboard.
- Stats line: count of entries, top mood, top tags.
- Up to 6 highlight days, target minimum 4. Selection is progressive:
  1) days with a photo AND at least one rare tag (used <3× this month);
  2) days with photo OR rare tag;
  3) days with the most photos (proxied by photo_thumb being non-null).
- Link to web UI.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from html import escape

from driftnote.digest.inputs import DayInput, HighlightInput
from driftnote.digest.moodboard import monthly_moodboard_grid
from driftnote.digest.weekly import Digest

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def select_highlights(days: list[DayInput], *, target: int = 4) -> list[HighlightInput]:
    if not days:
        return []
    tag_counts: Counter[str] = Counter()
    for d in days:
        tag_counts.update(d.tags)
    rare_tags = {t for t, c in tag_counts.items() if c < 3}

    def _has_photo(d: DayInput) -> bool:
        return d.photo_thumb is not None

    def _has_rare_tag(d: DayInput) -> bool:
        return any(t in rare_tags for t in d.tags)

    pass1 = [d for d in days if _has_photo(d) and _has_rare_tag(d)]
    if len(pass1) >= target:
        chosen = pass1
    else:
        pass2 = [d for d in days if _has_photo(d) or _has_rare_tag(d)]
        if len(pass2) >= target:
            chosen = pass2
        else:
            with_photo = [d for d in days if _has_photo(d)]
            chosen = with_photo if with_photo else days

    chosen = sorted(chosen, key=lambda d: d.date)[:6]
    return [
        HighlightInput(
            date=d.date, mood=d.mood,
            summary_html=_first_n_sentences(d.body_html, 2),
            photo_thumb=d.photo_thumb,
        )
        for d in chosen
    ]


def build_monthly_digest(
    *, year: int, month: int, days: list[DayInput], web_base_url: str,
) -> Digest:
    name = _MONTH_NAMES[month]
    subject = f"[Driftnote] {name} {year}"

    cells = monthly_moodboard_grid(year=year, month=month, days=days)
    grid_html = "".join(_row_html(row) for row in cells)

    moods = Counter(d.mood for d in days if d.mood)
    tags = Counter(t for d in days for t in d.tags)
    top_mood = moods.most_common(1)
    top_tags = tags.most_common(3)
    stats_html = (
        f"<p><strong>Stats:</strong> {len(days)} entries"
        + (f" • top emoji {escape(top_mood[0][0])} ({top_mood[0][1]})" if top_mood else "")
        + (
            " • top tags " + ", ".join(f"#{escape(t)}" for t, _ in top_tags)
            if top_tags else ""
        )
        + "</p>"
    )

    highlights_html = "".join(
        f"""
        <section style="margin:16px 0;padding-top:12px;border-top:1px solid #eee">
          <h3 style="margin:0">
            <a href="{escape(web_base_url)}/entry/{escape(h.date.isoformat())}" style="color:#222;text-decoration:none">
              {escape(h.date.isoformat())} <span style="font-size:20px">{escape(h.mood or "")}</span>
            </a>
          </h3>
          {h.summary_html}
          {f'<img src="{escape(h.photo_thumb)}" style="max-width:100%;border-radius:8px"/>' if h.photo_thumb else ""}
        </section>
        """.strip()
        for h in select_highlights(days)
    )

    body_html = f"""
    <html><body style="font-family:system-ui,sans-serif;max-width:640px;margin:auto;padding:16px">
      <h1>{escape(name)} {year}</h1>
      <table cellspacing="0" cellpadding="2" style="border-collapse:collapse;margin:8px 0 16px">
        {grid_html}
      </table>
      {stats_html}
      {highlights_html}
      <p style="margin-top:24px;color:#888"><a href="{escape(web_base_url)}">Open in Driftnote</a></p>
    </body></html>
    """.strip()
    return Digest(subject=subject, html=body_html)


def _row_html(row) -> str:
    return "<tr>" + "".join(
        f'<td style="text-align:center;width:32px;height:32px;'
        f'color:{"#222" if c.in_month else "#ccc"};font-size:18px">'
        f'{escape(c.emoji or ("·" if c.in_month else ""))}'
        f"</td>"
        for c in row
    ) + "</tr>"


def _first_n_sentences(html: str, n: int) -> str:
    """Naive sentence trim: split on `. `, take first n, retain HTML wrapper."""
    import re
    text = re.sub(r"<[^>]+>", "", html).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    snippet = " ".join(parts[:n])
    return f"<p>{escape(snippet)}</p>"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_digest_monthly.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/digest/monthly.py tests/unit/test_digest_monthly.py
git commit -m "feat(digest): monthly digest with progressive highlights heuristic"
```

---

### Task 8.4: `digest/yearly.py` — yearly review

**Files:**
- Create: `src/driftnote/digest/yearly.py`
- Create: `tests/unit/test_digest_yearly.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for yearly digest builder."""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.yearly import build_yearly_digest


def _day(d: str, mood: str | None = "💪", tags=None, thumb=None) -> DayInput:
    return DayInput(
        date=date.fromisoformat(d), mood=mood, tags=tags or [], photo_thumb=thumb,
        body_html="<p>x</p>",
    )


def test_subject_is_year_in_review() -> None:
    digest = build_yearly_digest(
        year=2026,
        days=[_day("2026-01-01")],
        web_base_url="https://x",
    )
    assert "2026" in digest.subject
    assert "review" in digest.subject.lower()


def test_html_includes_yearly_grid_and_streak_stats() -> None:
    days = [_day(f"2026-01-{i:02d}") for i in range(1, 11)]  # 10-day streak
    days += [_day("2026-06-15")]  # break in streak
    digest = build_yearly_digest(year=2026, days=days, web_base_url="https://x")
    assert "💪" in digest.html
    assert "Stats" in digest.html or "stats" in digest.html
    assert "11" in digest.html or "entries" in digest.html


def test_html_includes_one_photo_per_month_when_available() -> None:
    days = [
        _day(f"2026-{m:02d}-15", thumb=f"cid:photo-{m}", tags=["holiday" if m == 7 else "work"])
        for m in range(1, 13)
    ]
    digest = build_yearly_digest(year=2026, days=days, web_base_url="https://x")
    assert "cid:photo-1" in digest.html
    assert "cid:photo-12" in digest.html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_digest_yearly.py -v`

- [ ] **Step 3: Implement `src/driftnote/digest/yearly.py`**

```python
"""Yearly digest builder.

Body:
- 7×~53 contribution-grid moodboard
- Stats: total entries, longest streak, top 10 emojis, top 10 tags
- One photo per month (most-tagged day's first photo, fallback any photo)
- Link to web UI
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from driftnote.digest.inputs import DayInput
from driftnote.digest.moodboard import yearly_moodboard_grid
from driftnote.digest.weekly import Digest


def build_yearly_digest(*, year: int, days: list[DayInput], web_base_url: str) -> Digest:
    subject = f"[Driftnote] {year} in review"

    grid = yearly_moodboard_grid(year=year, days=days)
    grid_html = "<table cellspacing='1' cellpadding='0' style='border-collapse:separate'>"
    for row in grid:
        grid_html += "<tr>" + "".join(
            f'<td style="width:14px;height:14px;font-size:11px;text-align:center;'
            f'color:{"#222" if c.in_year else "#ddd"}">{escape(c.emoji or "")}</td>'
            for c in row
        ) + "</tr>"
    grid_html += "</table>"

    moods = Counter(d.mood for d in days if d.mood)
    tags = Counter(t for d in days for t in d.tags)
    top10_moods = ", ".join(f"{escape(m)} ({n})" for m, n in moods.most_common(10))
    top10_tags = ", ".join(f"#{escape(t)} ({n})" for t, n in tags.most_common(10))
    streak = _longest_streak({d.date for d in days})

    stats_html = (
        f"<p><strong>Stats</strong>: {len(days)} entries • longest streak {streak} days<br>"
        f"Top emojis: {top10_moods}<br>"
        f"Top tags: {top10_tags}</p>"
    )

    monthly_photos = _one_photo_per_month(days)
    photo_strip = "".join(
        f'<img src="{escape(thumb)}" style="max-width:100px;border-radius:6px;margin:4px"/>'
        for thumb in monthly_photos.values()
    )

    body_html = f"""
    <html><body style="font-family:system-ui,sans-serif;max-width:640px;margin:auto;padding:16px">
      <h1>{year} in review</h1>
      {grid_html}
      {stats_html}
      <p>{photo_strip}</p>
      <p style="margin-top:24px;color:#888"><a href="{escape(web_base_url)}">Open in Driftnote</a></p>
    </body></html>
    """.strip()
    return Digest(subject=subject, html=body_html)


def _longest_streak(dates: set[date]) -> int:
    if not dates:
        return 0
    sorted_dates = sorted(dates)
    longest = 1
    cur = 1
    for prev, nxt in zip(sorted_dates, sorted_dates[1:]):
        if nxt == prev + timedelta(days=1):
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 1
    return longest


def _one_photo_per_month(days: list[DayInput]) -> dict[int, str]:
    by_month: dict[int, str] = {}
    # Group days by month, prefer most-tagged then any with a thumb.
    from collections import defaultdict
    grouped: dict[int, list[DayInput]] = defaultdict(list)
    for d in days:
        if d.photo_thumb is None:
            continue
        grouped[d.date.month].append(d)
    for month, ds in grouped.items():
        ds_sorted = sorted(ds, key=lambda x: (-len(x.tags), x.date))
        by_month[month] = ds_sorted[0].photo_thumb  # type: ignore[assignment]
    return by_month
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_digest_yearly.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/digest/yearly.py tests/unit/test_digest_yearly.py
git commit -m "feat(digest): yearly review with grid + streak + monthly photo strip"
```

---

### Task 8.5: `scheduler/digest_jobs.py` — wire digests into APScheduler

**Files:**
- Create: `src/driftnote/scheduler/digest_jobs.py`
- Create: `src/driftnote/digest/queries.py` (DB → DayInput translation)
- Create: `tests/integration/test_digest_jobs.py`

- [ ] **Step 1: Write failing test**

```python
"""Integration test: digest jobs query DB, render HTML, send via SMTP."""

from __future__ import annotations

import asyncio
import imaplib
from datetime import date as _date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.mail.transport import SmtpTransport
from driftnote.repository.entries import EntryRecord, replace_tags, upsert_entry
from driftnote.scheduler.digest_jobs import run_weekly_digest, run_monthly_digest, run_yearly_digest
from tests.conftest import MailServer


def _smtp(mail_server: MailServer) -> SmtpTransport:
    return SmtpTransport(
        host=mail_server.host, port=mail_server.smtp_port,
        tls=False, starttls=False,
        username=mail_server.user, password=mail_server.password,
        sender_address=mail_server.address, sender_name="Driftnote",
    )


@pytest.fixture
def engine_with_data(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        for d, mood, tags in [
            ("2026-04-27", "💪", ["work"]),
            ("2026-04-30", "🎉", ["birthday"]),
            ("2026-05-01", "☕", ["work", "rest"]),
        ]:
            upsert_entry(session, EntryRecord(date=d, mood=mood, body_text="t", body_md="t", created_at="t", updated_at="t"))
            replace_tags(session, d, tags)
    return eng


@pytest.fixture(autouse=True)
def _clean_mailbox(mail_server: MailServer):
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    try:
        mb.select("INBOX")
        mb.store("1:*", "+FLAGS", r"\Deleted")
        mb.expunge()
    except Exception:
        pass
    mb.logout()


def _last_subject(mail_server: MailServer) -> bytes:
    mb = imaplib.IMAP4(mail_server.host, mail_server.imap_port)
    mb.login(mail_server.user, mail_server.password)
    mb.select("INBOX")
    typ, data = mb.search(None, "ALL")
    ids = data[0].split()
    typ, hdr = mb.fetch(ids[-1], "(BODY[HEADER.FIELDS (SUBJECT)])")
    mb.logout()
    return hdr[0][1]


def test_weekly_digest_sends(mail_server: MailServer, engine_with_data: Engine) -> None:
    asyncio.run(
        run_weekly_digest(
            engine=engine_with_data,
            smtp=_smtp(mail_server),
            recipient=mail_server.address,
            week_start=_date(2026, 4, 27),
            web_base_url="https://x",
        )
    )
    assert b"Week of 2026-04-27" in _last_subject(mail_server)


def test_monthly_digest_sends(mail_server: MailServer, engine_with_data: Engine) -> None:
    asyncio.run(
        run_monthly_digest(
            engine=engine_with_data,
            smtp=_smtp(mail_server),
            recipient=mail_server.address,
            year=2026, month=4,
            web_base_url="https://x",
        )
    )
    assert b"April 2026" in _last_subject(mail_server)


def test_yearly_digest_sends(mail_server: MailServer, engine_with_data: Engine) -> None:
    asyncio.run(
        run_yearly_digest(
            engine=engine_with_data,
            smtp=_smtp(mail_server),
            recipient=mail_server.address,
            year=2026,
            web_base_url="https://x",
        )
    )
    assert b"2026 in review" in _last_subject(mail_server)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_digest_jobs.py -v`

- [ ] **Step 3: Implement `src/driftnote/digest/queries.py`** — turn DB rows into `DayInput`s

```python
"""Queries that hydrate digest renderers from SQLite."""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.digest.inputs import DayInput
from driftnote.repository.entries import list_entries_in_range
from driftnote.repository.media import list_media


def days_in_range(engine: Engine, *, start: _date, end: _date) -> list[DayInput]:
    with session_scope(engine) as session:
        entries = list_entries_in_range(session, start.isoformat(), end.isoformat())
    out: list[DayInput] = []
    for e in entries:
        with session_scope(engine) as session:
            media = list_media(session, e.date)
        thumb = next((m.filename for m in media if m.kind == "photo"), None)
        photo_thumb = f"cid:{thumb}" if thumb else None
        # Body HTML = naive paragraph wrap of stored body_md.
        from html import escape
        body_html = "".join(f"<p>{escape(line)}</p>" for line in e.body_md.split("\n\n") if line.strip())
        out.append(
            DayInput(
                date=_date.fromisoformat(e.date),
                mood=e.mood,
                tags=[],  # tags filled below
                photo_thumb=photo_thumb,
                body_html=body_html,
            )
        )
    # Backfill tags via a single query.
    with session_scope(engine) as session:
        from driftnote.models import Tag
        from sqlalchemy import select
        tag_rows = session.scalars(
            select(Tag).where(Tag.date.between(start.isoformat(), end.isoformat()))
        ).all()
    tags_by_date: dict[str, list[str]] = {}
    for t in tag_rows:
        tags_by_date.setdefault(t.date, []).append(t.tag)
    return [
        DayInput(date=d.date, mood=d.mood, tags=tags_by_date.get(d.date.isoformat(), []),
                 photo_thumb=d.photo_thumb, body_html=d.body_html)
        for d in out
    ]
```

- [ ] **Step 4: Implement `src/driftnote/scheduler/digest_jobs.py`**

```python
"""Wire digest renderers into SMTP send. The scheduler module-level functions are
called by APScheduler once Chunk 10 wires them in via cron triggers."""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from sqlalchemy import Engine

from driftnote.digest.monthly import build_monthly_digest
from driftnote.digest.queries import days_in_range
from driftnote.digest.weekly import build_weekly_digest
from driftnote.digest.yearly import build_yearly_digest
from driftnote.mail.smtp import send_email
from driftnote.mail.transport import SmtpTransport


async def run_weekly_digest(
    *, engine: Engine, smtp: SmtpTransport, recipient: str,
    week_start: _date, web_base_url: str,
) -> None:
    week_end = week_start + timedelta(days=6)
    days = days_in_range(engine, start=week_start, end=week_end)
    digest = build_weekly_digest(week_start=week_start, days=days, web_base_url=web_base_url)
    await send_email(
        smtp, recipient=recipient, subject=digest.subject,
        body_text=_html_to_text(digest.html), body_html=digest.html,
    )


async def run_monthly_digest(
    *, engine: Engine, smtp: SmtpTransport, recipient: str,
    year: int, month: int, web_base_url: str,
) -> None:
    start = _date(year, month, 1)
    end = _date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    days = days_in_range(engine, start=start, end=end)
    digest = build_monthly_digest(year=year, month=month, days=days, web_base_url=web_base_url)
    await send_email(
        smtp, recipient=recipient, subject=digest.subject,
        body_text=_html_to_text(digest.html), body_html=digest.html,
    )


async def run_yearly_digest(
    *, engine: Engine, smtp: SmtpTransport, recipient: str,
    year: int, web_base_url: str,
) -> None:
    start = _date(year, 1, 1)
    end = _date(year, 12, 31)
    days = days_in_range(engine, start=start, end=end)
    digest = build_yearly_digest(year=year, days=days, web_base_url=web_base_url)
    await send_email(
        smtp, recipient=recipient, subject=digest.subject,
        body_text=_html_to_text(digest.html), body_html=digest.html,
    )


def _html_to_text(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html).strip()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_digest_jobs.py -v`
Expected: 3 passed.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/digest/queries.py src/driftnote/scheduler/digest_jobs.py tests/integration/test_digest_jobs.py
git commit -m "feat(digest): wire weekly/monthly/yearly to SMTP send"
```

---

### Chunk 8 closeout

**Acceptance criteria:**
- [ ] All Chunks 1–8 tests pass: `uv run pytest -v`.
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] 5 task commits in this chunk with conventional-commit prefixes.

**Hand-off:** Chunk 9 (web layer) follows. Chunks 8 and 9 had no shared dependencies and could have run in parallel from the end of Chunk 7.

---

## Chunk 9: Web layer

**Outcome of this chunk:** A FastAPI app surface with: Cloudflare Access JWT middleware (skipped in dev); `/healthz` + `/readyz`; calendar/entry/tags/search browse; entry edit; media serving (original/web/thumb); admin dashboard with banners. Server-rendered Jinja2 + HTMX, no SPA build.

### Task 9.1: `web/auth.py` — Cloudflare Access JWT middleware

**Files:**
- Create: `src/driftnote/web/__init__.py`
- Create: `src/driftnote/web/auth.py`
- Create: `tests/unit/test_web_auth.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for Cloudflare Access JWT middleware."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from driftnote.web.auth import CloudflareAccessAuth, install_cf_access_middleware


def _hs256_token(secret: str, *, aud: str, exp_offset: int = 60, **extras: Any) -> str:
    payload = {"aud": aud, "iat": int(time.time()), "exp": int(time.time()) + exp_offset, **extras}
    return jwt.encode(payload, secret, algorithm="HS256")


def _build(app: FastAPI, *, environment: str, audience: str = "aud", team_domain: str = "t.example.com") -> FastAPI:
    auth = CloudflareAccessAuth(
        audience=audience,
        team_domain=team_domain,
        environment=environment,
        # Test override: validate via shared HS256 secret so we don't need JWKS HTTP.
        signing_keys={"k1": "shared-secret"},
        algorithms=["HS256"],
    )
    install_cf_access_middleware(app, auth)
    return app


def test_dev_environment_bypasses_jwt() -> None:
    app = FastAPI()
    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}
    _build(app, environment="dev")
    r = TestClient(app).get("/x")
    assert r.status_code == 200


def test_prod_rejects_missing_jwt() -> None:
    app = FastAPI()
    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}
    _build(app, environment="prod")
    r = TestClient(app).get("/x")
    assert r.status_code == 403
    assert r.json()["detail"] == "missing access token"


def test_prod_accepts_valid_jwt() -> None:
    app = FastAPI()
    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}
    _build(app, environment="prod")
    token = _hs256_token("shared-secret", aud="aud", email="me@example.com")
    r = TestClient(app).get("/x", headers={"Cf-Access-Jwt-Assertion": token})
    assert r.status_code == 200


def test_prod_rejects_wrong_audience() -> None:
    app = FastAPI()
    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}
    _build(app, environment="prod")
    bad = _hs256_token("shared-secret", aud="someone-else")
    r = TestClient(app).get("/x", headers={"Cf-Access-Jwt-Assertion": bad})
    assert r.status_code == 403


def test_prod_rejects_expired_jwt() -> None:
    app = FastAPI()
    @app.get("/x")
    async def _x() -> dict[str, str]:
        return {"ok": "yes"}
    _build(app, environment="prod")
    expired = _hs256_token("shared-secret", aud="aud", exp_offset=-1)
    r = TestClient(app).get("/x", headers={"Cf-Access-Jwt-Assertion": expired})
    assert r.status_code == 403


def test_health_endpoints_skip_auth() -> None:
    app = FastAPI()
    @app.get("/healthz")
    async def _hz() -> dict[str, str]:
        return {"status": "ok"}
    _build(app, environment="prod")
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_web_auth.py -v`

- [ ] **Step 3: Implement `src/driftnote/web/__init__.py`** (empty)

```python
"""Web layer: FastAPI routes, auth middleware, templates."""
```

- [ ] **Step 4: Implement `src/driftnote/web/auth.py`**

```python
"""Cloudflare Access JWT verification middleware.

In production, the `Cf-Access-Jwt-Assertion` header is verified against
Cloudflare's JWKS endpoint at `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`.
For tests we substitute static signing keys + HS256 to avoid network IO.
In dev (`environment='dev'`), the middleware bypasses verification entirely.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_SKIP_PATHS = ("/healthz", "/readyz")


@dataclass
class CloudflareAccessAuth:
    audience: str
    team_domain: str
    environment: str = "prod"
    signing_keys: dict[str, str] | None = None  # for tests
    algorithms: list[str] = field(default_factory=lambda: ["RS256"])
    _jwks_cache: dict[str, str] = field(default_factory=dict)
    _jwks_cached_at: float = 0.0

    @property
    def issuer(self) -> str:
        return f"https://{self.team_domain}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/cdn-cgi/access/certs"

    def _resolve_key(self, kid: str) -> str | None:
        if self.signing_keys is not None:
            return self.signing_keys.get(kid) or next(iter(self.signing_keys.values()), None)
        # JWKS cache (1h TTL)
        if not self._jwks_cache or time.time() - self._jwks_cached_at > 3600:
            try:
                resp = httpx.get(self.jwks_url, timeout=5.0)
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError):
                return None
            cache: dict[str, str] = {}
            for jwk in payload.get("keys", []):
                key_id = jwk.get("kid", "")
                cache[key_id] = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)  # type: ignore[arg-type]
            self._jwks_cache = cache
            self._jwks_cached_at = time.time()
        return self._jwks_cache.get(kid)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            unverified = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise PermissionError(f"malformed token: {exc}") from exc
        kid = unverified.get("kid", "")
        key = self._resolve_key(kid)
        if key is None:
            raise PermissionError("signing key not found")
        try:
            return jwt.decode(token, key, algorithms=self.algorithms, audience=self.audience)
        except jwt.InvalidTokenError as exc:
            raise PermissionError(f"invalid token: {exc}") from exc


class _CFAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, auth: CloudflareAccessAuth) -> None:
        super().__init__(app)
        self.auth = auth

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        if self.auth.environment == "dev":
            return await call_next(request)
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)
        token = request.headers.get("Cf-Access-Jwt-Assertion")
        if not token:
            return JSONResponse({"detail": "missing access token"}, status_code=403)
        try:
            self.auth.verify(token)
        except PermissionError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=403)
        return await call_next(request)


def install_cf_access_middleware(app: FastAPI, auth: CloudflareAccessAuth) -> None:
    app.add_middleware(_CFAccessMiddleware, auth=auth)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_web_auth.py -v`
Expected: 6 passed.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/web/__init__.py src/driftnote/web/auth.py tests/unit/test_web_auth.py
git commit -m "feat(web): Cloudflare Access JWT middleware with dev bypass"
```

---

### Task 9.2: `web/routes_health.py` + `web/banners.py` — health endpoints + banner state

**Files:**
- Create: `src/driftnote/web/routes_health.py`
- Create: `src/driftnote/web/banners.py`
- Create: `tests/unit/test_web_banners.py`
- Create: `tests/integration/test_web_routes_health.py`

- [ ] **Step 1: Write failing test for banners**

```python
"""Tests for banner state derivation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import finish_job_run, record_job_run
from driftnote.repository.ingested import record_threshold_crossed
from driftnote.web.banners import Banner, compute_banners


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    return eng


def test_no_banners_for_clean_state(engine: Engine) -> None:
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    assert banners == []


def test_unacknowledged_failure_in_last_7_days(engine: Engine) -> None:
    with session_scope(engine) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-05T12:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-05-05T12:00:01Z", status="error", error_kind="imap_auth")
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    levels = [b.level for b in banners]
    assert "error" in levels


def test_old_failure_outside_window_does_not_show(engine: Engine) -> None:
    with session_scope(engine) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-04-01T12:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-04-01T12:00:01Z", status="error", error_kind="imap_auth")
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    assert all(b.level != "error" for b in banners)


def test_disk_threshold_crossed_shows_warning(engine: Engine) -> None:
    with session_scope(engine) as session:
        record_threshold_crossed(session, threshold=80, at="2026-05-06T03:00:00Z")
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    assert any(b.level == "warn" and "disk" in b.message.lower() for b in banners)


def test_no_recent_backup_warning(engine: Engine) -> None:
    """If backup hasn't succeeded in >35 days, surface an amber banner."""
    with session_scope(engine) as session:
        rid = record_job_run(session, job="backup", started_at="2026-03-01T03:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-03-01T03:00:10Z", status="ok")
    banners = compute_banners(engine, now="2026-05-06T12:00:00Z")
    assert any(b.level == "warn" and "backup" in b.message.lower() for b in banners)
```

- [ ] **Step 2: Write failing test for health endpoints**

```python
"""Smoke test that /healthz + /readyz are wired and return JSON."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from driftnote.web.routes_health import install_health_routes


def test_healthz_returns_ok() -> None:
    app = FastAPI()
    install_health_routes(app, db_ok=lambda: True, last_imap_poll_status=lambda: ("2026-05-06T20:55:00Z", "ok"))
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["last_imap_poll_status"] == "ok"


def test_healthz_reports_db_failure() -> None:
    app = FastAPI()
    install_health_routes(app, db_ok=lambda: False, last_imap_poll_status=lambda: (None, None))
    r = TestClient(app).get("/healthz")
    body = r.json()
    assert body["db"] == "error"


def test_readyz_only_returns_when_ready() -> None:
    app = FastAPI()
    state = {"ready": False}
    install_health_routes(
        app,
        db_ok=lambda: True,
        last_imap_poll_status=lambda: (None, None),
        readiness=lambda: state["ready"],
    )
    r = TestClient(app).get("/readyz")
    assert r.status_code == 503
    state["ready"] = True
    r = TestClient(app).get("/readyz")
    assert r.status_code == 200
```

- [ ] **Step 3: Implement `src/driftnote/web/banners.py`**

```python
"""Banner state derived from job_runs + disk_state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.repository.ingested import get_threshold_crossed_at
from driftnote.repository.jobs import last_successful_run, recent_failures


@dataclass(frozen=True)
class Banner:
    level: str       # 'error' | 'warn'
    message: str
    link: str | None = None


def compute_banners(engine: Engine, *, now: str) -> list[Banner]:
    out: list[Banner] = []

    with session_scope(engine) as session:
        unack = recent_failures(session, now=now, days=7, only_unacknowledged=True)
    if unack:
        out.append(
            Banner(
                level="error",
                message=f"{len(unack)} unacknowledged failure(s) in the last 7 days.",
                link="/admin",
            )
        )

    with session_scope(engine) as session:
        last_backup = last_successful_run(session, "backup")
    if last_backup is None or _days_since(last_backup.started_at, now) > 35:
        out.append(Banner(level="warn", message="Last successful backup is older than 35 days.", link="/admin"))

    with session_scope(engine) as session:
        warn_at = get_threshold_crossed_at(session, 80)
        alert_at = get_threshold_crossed_at(session, 95)
    if alert_at is not None:
        out.append(Banner(level="error", message="Disk usage above 95%.", link="/admin"))
    elif warn_at is not None:
        out.append(Banner(level="warn", message="Disk usage above 80%.", link="/admin"))

    return out


def _days_since(iso: str, now: str) -> float:
    a = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    b = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return (b - a).total_seconds() / 86400.0
```

- [ ] **Step 4: Implement `src/driftnote/web/routes_health.py`**

```python
"""Health and readiness HTTP routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Response


def install_health_routes(
    app: FastAPI,
    *,
    db_ok: Callable[[], bool],
    last_imap_poll_status: Callable[[], tuple[str | None, str | None]],
    readiness: Callable[[], bool] | None = None,
) -> None:
    @app.get("/healthz")
    async def healthz() -> dict[str, str | None]:
        last_at, last_status = last_imap_poll_status()
        return {
            "status": "ok",
            "db": "ok" if db_ok() else "error",
            "last_imap_poll": last_at,
            "last_imap_poll_status": last_status,
        }

    if readiness is None:
        @app.get("/readyz")
        async def readyz_default() -> dict[str, str]:
            return {"status": "ok"}
    else:
        @app.get("/readyz")
        async def readyz_dyn(response: Response) -> dict[str, str]:
            if not readiness():
                response.status_code = 503
                return {"status": "starting"}
            return {"status": "ok"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_web_banners.py tests/integration/test_web_routes_health.py -v`
Expected: 8 passed.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/web/banners.py src/driftnote/web/routes_health.py tests/unit/test_web_banners.py tests/integration/test_web_routes_health.py
git commit -m "feat(web): banner state + /healthz and /readyz endpoints"
```

---

### Task 9.3: Templates + static assets + minimal browse routes

**Files:**
- Create: `src/driftnote/web/templates/base.html.j2`
- Create: `src/driftnote/web/templates/calendar.html.j2`
- Create: `src/driftnote/web/templates/entry.html.j2`
- Create: `src/driftnote/web/templates/tags.html.j2`
- Create: `src/driftnote/web/templates/search.html.j2`
- Create: `src/driftnote/web/static/style.css`
- Create: `src/driftnote/web/static/htmx.min.js` (vendor; download in step)
- Create: `src/driftnote/web/routes_browse.py`
- Create: `tests/integration/test_web_routes_browse.py`

The full template set is included so the executor doesn't need to invent layout. Polish CSS as desired in a follow-up task; nothing here is meant to be "final design".

- [ ] **Step 1: Vendor htmx**

```bash
curl -L -o src/driftnote/web/static/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
test -s src/driftnote/web/static/htmx.min.js
```

- [ ] **Step 2: Create `base.html.j2`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{% block title %}Driftnote{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/htmx.min.js" defer></script>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/">Driftnote</a>
    <nav>
      <a href="/">Calendar</a>
      <a href="/tags">Tags</a>
      <a href="/search">Search</a>
      <a href="/admin">Admin</a>
    </nav>
  </header>
  {% if banners %}
    <section class="banners">
      {% for b in banners %}
        <div class="banner banner-{{ b.level }}">
          {{ b.message }}
          {% if b.link %}<a href="{{ b.link }}">view</a>{% endif %}
        </div>
      {% endfor %}
    </section>
  {% endif %}
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

- [ ] **Step 3: Create `calendar.html.j2`, `entry.html.j2`, `tags.html.j2`, `search.html.j2`**

`calendar.html.j2`:

```html
{% extends "base.html.j2" %}
{% block title %}{{ year }}-{{ "%02d"|format(month) }} — Driftnote{% endblock %}
{% block content %}
<h1>{{ month_name }} {{ year }}</h1>
<nav class="month-nav">
  <a href="/?year={{ prev_year }}&month={{ prev_month }}">‹ prev</a>
  <a href="/?year={{ next_year }}&month={{ next_month }}">next ›</a>
</nav>
<table class="calendar">
  <thead><tr>
    {% for label in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"] %}<th>{{ label }}</th>{% endfor %}
  </tr></thead>
  <tbody>
    {% for row in cells %}
      <tr>
      {% for c in row %}
        <td class="{% if not c.in_month %}dim{% endif %}">
          {% if c.in_month %}
            <a href="/entry/{{ c.date.isoformat() }}">
              <div class="dom">{{ c.day_of_month }}</div>
              <div class="emoji">{{ c.emoji or "·" }}</div>
            </a>
          {% endif %}
        </td>
      {% endfor %}
      </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`entry.html.j2`:

```html
{% extends "base.html.j2" %}
{% block title %}{{ entry.date }} — Driftnote{% endblock %}
{% block content %}
<article class="entry">
  <h1>{{ entry.date }} {% if entry.mood %}<span class="mood">{{ entry.mood }}</span>{% endif %}</h1>
  <p class="tags">{% for t in tags %}<a href="/?tag={{ t }}">#{{ t }}</a>{% endfor %}</p>
  <div class="body">{{ body_html|safe }}</div>
  <section class="media">
    {% for m in media if m.kind == "photo" %}
      <a href="/media/{{ entry.date }}/web/{{ m.filename | replace('.heic', '.jpg') }}">
        <img src="/media/{{ entry.date }}/thumb/{{ m.filename | replace('.heic', '.jpg') }}" alt="">
      </a>
    {% endfor %}
    {% for m in media if m.kind == "video" %}
      <video controls preload="none" poster="/media/{{ entry.date }}/thumb/{{ m.filename | replace('.', '_') }}.jpg">
        <source src="/media/{{ entry.date }}/original/{{ m.filename }}">
      </video>
    {% endfor %}
  </section>
  <p><a href="/entry/{{ entry.date }}/edit">Edit</a></p>
</article>
{% endblock %}
```

`tags.html.j2`:

```html
{% extends "base.html.j2" %}
{% block title %}Tags — Driftnote{% endblock %}
{% block content %}
<h1>Tags</h1>
<ul class="tag-cloud">
  {% for tag, count in tags %}
    <li><a href="/?tag={{ tag }}" style="font-size:{{ 0.8 + (count*0.1) }}rem">#{{ tag }} ({{ count }})</a></li>
  {% endfor %}
</ul>
{% endblock %}
```

`search.html.j2`:

```html
{% extends "base.html.j2" %}
{% block title %}Search — Driftnote{% endblock %}
{% block content %}
<h1>Search</h1>
<form method="get" action="/search">
  <input type="search" name="q" value="{{ q or '' }}" placeholder="quick brown fox" autofocus>
  <button>Search</button>
</form>
<ul class="search-results">
  {% for e in results %}
    <li><a href="/entry/{{ e.date }}">{{ e.date }} {{ e.mood or "" }}</a> — {{ e.body_text|truncate(160) }}</li>
  {% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 4: Create `static/style.css`** (minimal, focused)

```css
:root { --bg:#fafafa; --fg:#222; --muted:#888; --warn:#f5c542; --error:#e74c3c; }
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--fg);
       margin: 0; padding: 0 16px; max-width: 960px; margin-inline: auto; }
.topbar { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #eee; }
.topbar nav a { margin-left: 12px; color: var(--fg); text-decoration: none; }
.brand { font-weight: 700; text-decoration: none; color: var(--fg); }
.banners { display: flex; flex-direction: column; gap: 6px; margin: 12px 0; }
.banner { padding: 8px 12px; border-radius: 6px; }
.banner-warn  { background: #fff8e0; border-left: 4px solid var(--warn); }
.banner-error { background: #fdecea; border-left: 4px solid var(--error); }
.calendar { width: 100%; border-collapse: collapse; }
.calendar th, .calendar td { padding: 4px; text-align: center; border: 1px solid #eee; height: 56px; }
.calendar td.dim { color: #ccc; }
.calendar .emoji { font-size: 20px; }
.calendar .dom { font-size: 11px; color: var(--muted); }
.tag-cloud { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.tag-cloud a { color: var(--fg); text-decoration: none; }
.entry .mood { font-size: 26px; }
.entry .tags a { color: var(--muted); margin-right: 6px; text-decoration: none; }
.entry .media img { max-width: 240px; border-radius: 8px; margin: 4px; }
.entry .media video { max-width: 100%; border-radius: 8px; }
.search-results li { margin: 6px 0; }
```

- [ ] **Step 5: Implement `src/driftnote/web/routes_browse.py`**

```python
"""Calendar / entry / tags / search browse routes."""

from __future__ import annotations

import calendar as _cal
from collections.abc import Callable
from datetime import date as _date
from html import escape
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.digest.inputs import DayInput
from driftnote.digest.moodboard import monthly_moodboard_grid
from driftnote.repository.entries import (
    list_entries_by_month,
    list_entries_by_tag,
    list_entries_in_range,
    search_fts,
    tag_frequencies_in_range,
    get_entry,
)
from driftnote.repository.media import list_media
from driftnote.web.banners import compute_banners

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def install_browse_routes(
    app: FastAPI,
    *,
    engine: Engine,
    iso_now: Callable[[], str],
) -> None:
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    def _ctx(request: Request, **extras) -> dict:
        return {"request": request, "banners": compute_banners(engine, now=iso_now()), **extras}

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        year: int | None = Query(None),
        month: int | None = Query(None),
        tag: str | None = Query(None),
    ):
        if tag:
            with session_scope(engine) as session:
                entries = list_entries_by_tag(session, tag)
            return templates.TemplateResponse(
                "search.html.j2",
                _ctx(request, q=f"#{tag}", results=entries),
            )

        today = _date.today()
        y = year or today.year
        m = month or today.month
        with session_scope(engine) as session:
            entries = list_entries_by_month(session, y, m)
        days = [
            DayInput(date=_date.fromisoformat(e.date), mood=e.mood, tags=[], photo_thumb=None, body_html="")
            for e in entries
        ]
        cells = monthly_moodboard_grid(year=y, month=m, days=days)
        prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
        next_y, next_m = (y, m + 1) if m < 12 else (y + 1, 1)
        return templates.TemplateResponse(
            "calendar.html.j2",
            _ctx(
                request,
                year=y, month=m, month_name=_cal.month_name[m],
                cells=cells,
                prev_year=prev_y, prev_month=prev_m,
                next_year=next_y, next_month=next_m,
            ),
        )

    @app.get("/entry/{date_str}", response_class=HTMLResponse)
    async def entry_detail(request: Request, date_str: str):
        with session_scope(engine) as session:
            entry = get_entry(session, date_str)
            media = list_media(session, date_str) if entry else []
        if entry is None:
            return HTMLResponse("Not found", status_code=404)
        # Crude markdown → HTML rendering: handled inline for simplicity.
        from markdown_it import MarkdownIt
        md = MarkdownIt("commonmark")
        body_html = md.render(entry.body_md)
        # Tags via Tag table:
        from driftnote.models import Tag
        from sqlalchemy import select
        with session_scope(engine) as session:
            tag_rows = session.scalars(select(Tag).where(Tag.date == date_str)).all()
        return templates.TemplateResponse(
            "entry.html.j2",
            _ctx(request, entry=entry, body_html=body_html, media=media, tags=[t.tag for t in tag_rows]),
        )

    @app.get("/tags", response_class=HTMLResponse)
    async def tags_view(request: Request):
        with session_scope(engine) as session:
            freq = tag_frequencies_in_range(session, "0001-01-01", "9999-12-31")
        ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
        return templates.TemplateResponse("tags.html.j2", _ctx(request, tags=ranked))

    @app.get("/search", response_class=HTMLResponse)
    async def search_view(request: Request, q: str | None = Query(None)):
        results = []
        if q:
            with session_scope(engine) as session:
                results = search_fts(session, q)
        return templates.TemplateResponse("search.html.j2", _ctx(request, q=q, results=results))


def install_static(app: FastAPI) -> None:
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
```

- [ ] **Step 6: Write integration test**

```python
"""Smoke tests for the browse routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.entries import EntryRecord, replace_tags, upsert_entry
from driftnote.web.routes_browse import install_browse_routes, install_static


@pytest.fixture
def app_with_data(tmp_path: Path) -> tuple[FastAPI, Engine]:
    eng = make_engine(tmp_path / "index.sqlite")
    init_db(eng)
    with session_scope(eng) as session:
        upsert_entry(session, EntryRecord(date="2026-05-06", mood="💪", body_text="risotto night", body_md="# Risotto night\n\nIt was great.", created_at="t", updated_at="t"))
        replace_tags(session, "2026-05-06", ["work", "cooking"])
    app = FastAPI()
    install_browse_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z")
    install_static(app)
    return app, eng


def test_calendar_page_renders(app_with_data) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    assert "💪" in r.text


def test_entry_page_renders_markdown(app_with_data) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/entry/2026-05-06")
    assert r.status_code == 200
    assert "<h1>Risotto night</h1>" in r.text
    assert "#work" in r.text or "work" in r.text


def test_tags_page_lists_tags(app_with_data) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/tags")
    assert r.status_code == 200
    assert "work" in r.text
    assert "cooking" in r.text


def test_search_returns_fts_hits(app_with_data) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/search?q=risotto")
    assert r.status_code == 200
    assert "2026-05-06" in r.text
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_web_routes_browse.py -v`
Expected: 4 passed.

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/web/templates/ src/driftnote/web/static/ src/driftnote/web/routes_browse.py tests/integration/test_web_routes_browse.py
git commit -m "feat(web): browse routes (calendar, entry, tags, search) + templates"
```

---

### Task 9.4: `web/routes_edit.py` — entry editor with HTMX preview

**Files:**
- Create: `src/driftnote/web/routes_edit.py`
- Create: `src/driftnote/web/templates/entry_edit.html.j2`
- Create: `tests/integration/test_web_routes_edit.py`

- [ ] **Step 1: Write failing test**

```python
"""Edit-route smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.filesystem.markdown_io import EntryDocument, write_entry
from driftnote.filesystem.layout import entry_paths_for
from driftnote.repository.entries import EntryRecord, get_entry, upsert_entry
from driftnote.web.routes_edit import install_edit_routes


@pytest.fixture
def app(tmp_path: Path) -> tuple[FastAPI, Engine, Path]:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    data_root = tmp_path / "data"
    # Pre-seed an entry on disk + index.
    from datetime import date as _date
    paths = entry_paths_for(data_root, _date(2026, 5, 6))
    paths.dir.mkdir(parents=True, exist_ok=True)
    write_entry(
        paths.entry_md,
        EntryDocument(
            date=_date(2026, 5, 6), mood="💪", tags=["work"], created_at="t", updated_at="t",
            sources=["raw/x.eml"], body="initial body\n",
        ),
    )
    with session_scope(eng) as session:
        upsert_entry(session, EntryRecord(date="2026-05-06", mood="💪", body_text="initial body", body_md="initial body", created_at="t", updated_at="t"))
    app = FastAPI()
    install_edit_routes(app, engine=eng, data_root=data_root, iso_now=lambda: "2026-05-07T08:00:00Z")
    return app, eng, data_root


def test_edit_form_renders(app) -> None:
    fapp, _, _ = app
    r = TestClient(fapp).get("/entry/2026-05-06/edit")
    assert r.status_code == 200
    assert "initial body" in r.text


def test_edit_post_updates_entry_md_and_db(app) -> None:
    fapp, eng, data_root = app
    r = TestClient(fapp).post(
        "/entry/2026-05-06",
        data={"mood": "🎉", "tags": "work, party", "body": "updated body"},
    )
    assert r.status_code in (200, 303)
    with session_scope(eng) as session:
        entry = get_entry(session, "2026-05-06")
    assert entry is not None
    assert entry.mood == "🎉"
    assert "updated body" in entry.body_md

    from driftnote.filesystem.layout import entry_paths_for
    from datetime import date as _date
    md_text = entry_paths_for(data_root, _date(2026, 5, 6)).entry_md.read_text()
    assert "updated body" in md_text
    assert "🎉" in md_text
    assert "raw/x.eml" in md_text  # raw sources preserved


def test_preview_endpoint_renders_markdown_to_html(app) -> None:
    fapp, _, _ = app
    r = TestClient(fapp).post("/preview", data={"body": "# hi\n\n**there**"})
    assert r.status_code == 200
    assert "<h1>hi</h1>" in r.text
    assert "<strong>there</strong>" in r.text
```

- [ ] **Step 2: Create `entry_edit.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}Edit {{ entry.date }} — Driftnote{% endblock %}
{% block content %}
<form method="post" action="/entry/{{ entry.date }}" class="entry-edit">
  <h1>Edit {{ entry.date }}</h1>
  <label>Mood (one emoji): <input name="mood" value="{{ entry.mood or '' }}"></label>
  <label>Tags (comma-separated): <input name="tags" value="{{ tags_csv }}" style="width:100%"></label>
  <label>Body (markdown):</label>
  <textarea name="body" rows="14"
            hx-post="/preview" hx-target="#preview" hx-trigger="keyup changed delay:400ms"
            style="width:100%">{{ entry.body_md }}</textarea>
  <h3>Preview</h3>
  <div id="preview" class="preview">{{ initial_preview|safe }}</div>
  <p><button type="submit">Save</button> <a href="/entry/{{ entry.date }}">Cancel</a></p>
</form>
{% endblock %}
```

- [ ] **Step 3: Implement `src/driftnote/web/routes_edit.py`**

```python
"""Entry edit form, save handler, live-preview endpoint."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as _date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from sqlalchemy import Engine

from driftnote.db import session_scope
from driftnote.filesystem.layout import entry_paths_for
from driftnote.filesystem.locks import entry_lock
from driftnote.filesystem.markdown_io import (
    EntryDocument,
    PhotoRef,
    VideoRef,
    read_entry,
    write_entry,
)
from driftnote.repository.entries import (
    EntryRecord,
    get_entry,
    replace_tags,
    upsert_entry,
)
from driftnote.web.banners import compute_banners

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_md = MarkdownIt("commonmark")


def install_edit_routes(
    app: FastAPI,
    *,
    engine: Engine,
    data_root: Path,
    iso_now: Callable[[], str],
) -> None:
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    @app.get("/entry/{date_str}/edit", response_class=HTMLResponse)
    async def edit_form(request: Request, date_str: str):
        with session_scope(engine) as session:
            entry = get_entry(session, date_str)
        if entry is None:
            return HTMLResponse("Not found", status_code=404)
        from driftnote.models import Tag
        from sqlalchemy import select
        with session_scope(engine) as session:
            tags = [t.tag for t in session.scalars(select(Tag).where(Tag.date == date_str))]
        ctx = {
            "request": request,
            "banners": compute_banners(engine, now=iso_now()),
            "entry": entry,
            "tags_csv": ", ".join(tags),
            "initial_preview": _md.render(entry.body_md),
        }
        return templates.TemplateResponse("entry_edit.html.j2", ctx)

    @app.post("/entry/{date_str}", response_class=HTMLResponse)
    async def save_entry(
        date_str: str,
        mood: str = Form(""),
        tags: str = Form(""),
        body: str = Form(""),
    ):
        d = _date.fromisoformat(date_str)
        paths = entry_paths_for(data_root, d)
        if not paths.entry_md.exists():
            return HTMLResponse("Not found", status_code=404)
        new_tags = [t.strip().lower() for t in tags.split(",") if t.strip()]
        with entry_lock(data_root, d):
            existing = read_entry(paths.entry_md)
            updated = EntryDocument(
                date=existing.date,
                mood=(mood.strip() or None),
                tags=new_tags,
                photos=existing.photos,
                videos=existing.videos,
                created_at=existing.created_at,
                updated_at=iso_now(),
                sources=existing.sources,
                body=body if body.endswith("\n") else body + "\n",
            )
            write_entry(paths.entry_md, updated)
            with session_scope(engine) as session:
                upsert_entry(
                    session,
                    EntryRecord(
                        date=date_str,
                        mood=updated.mood,
                        body_text=updated.body,
                        body_md=updated.body,
                        created_at=updated.created_at,
                        updated_at=updated.updated_at,
                    ),
                )
                replace_tags(session, date_str, new_tags)
        return RedirectResponse(f"/entry/{date_str}", status_code=303)

    @app.post("/preview", response_class=HTMLResponse)
    async def preview(body: str = Form("")):
        return HTMLResponse(_md.render(body))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_web_routes_edit.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/web/templates/entry_edit.html.j2 src/driftnote/web/routes_edit.py tests/integration/test_web_routes_edit.py
git commit -m "feat(web): entry edit form with HTMX live preview"
```

---

### Task 9.5: `web/routes_media.py` + `web/routes_admin.py`

**Files:**
- Create: `src/driftnote/web/routes_media.py`
- Create: `src/driftnote/web/routes_admin.py`
- Create: `src/driftnote/web/templates/admin.html.j2`
- Create: `tests/integration/test_web_routes_media_and_admin.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for media-serving and admin dashboard routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.repository.jobs import finish_job_run, record_job_run
from driftnote.web.routes_admin import install_admin_routes
from driftnote.web.routes_media import install_media_routes


@pytest.fixture
def setup(tmp_path: Path) -> tuple[FastAPI, Engine, Path]:
    eng = make_engine(tmp_path / "data" / "index.sqlite")
    init_db(eng)
    data_root = tmp_path / "data"
    # Drop a tiny image into the entries tree.
    entry_dir = data_root / "entries" / "2026" / "05" / "06"
    (entry_dir / "originals").mkdir(parents=True)
    (entry_dir / "web").mkdir()
    (entry_dir / "thumbs").mkdir()
    (entry_dir / "originals" / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (entry_dir / "web" / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (entry_dir / "thumbs" / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    app = FastAPI()
    install_media_routes(app, data_root=data_root)
    install_admin_routes(app, engine=eng, iso_now=lambda: "2026-05-06T12:00:00Z")
    return app, eng, data_root


def test_media_serves_thumb(setup) -> None:
    fapp, _, _ = setup
    r = TestClient(fapp).get("/media/2026-05-06/thumb/photo.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert r.content[:2] == b"\xff\xd8"


def test_media_404_for_missing_file(setup) -> None:
    fapp, _, _ = setup
    r = TestClient(fapp).get("/media/2026-05-06/web/missing.jpg")
    assert r.status_code == 404


def test_media_rejects_path_traversal(setup) -> None:
    fapp, _, _ = setup
    r = TestClient(fapp).get("/media/2026-05-06/thumb/..%2F..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_admin_index_lists_each_job_card(setup) -> None:
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-05-06T08:00:01Z", status="ok", detail="ingested 1")
    r = TestClient(fapp).get("/admin")
    assert r.status_code == 200
    assert "imap_poll" in r.text
    assert "ingested 1" in r.text


def test_admin_acknowledge(setup) -> None:
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(session, run_id=rid, finished_at="2026-05-06T08:00:01Z", status="error", error_kind="imap_auth")
    r = TestClient(fapp).post(f"/admin/runs/{rid}/ack")
    assert r.status_code in (200, 303)
    from driftnote.repository.jobs import recent_failures
    with session_scope(eng) as session:
        unack = recent_failures(session, now="2026-05-06T12:00:00Z", days=7, only_unacknowledged=True)
    assert unack == []
```

- [ ] **Step 2: Implement `src/driftnote/web/routes_media.py`**

```python
"""Serve original / web / thumb media from the entries tree."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def install_media_routes(app: FastAPI, *, data_root: Path) -> None:
    @app.get("/media/{date_str}/{kind}/{filename}")
    async def media(date_str: str, kind: str, filename: str):
        if kind not in {"original", "web", "thumb"}:
            raise HTTPException(status_code=400, detail="invalid kind")
        # Defense against path traversal: filename and date_str are exact path components.
        if "/" in filename or ".." in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="invalid filename")
        try:
            y, m, d = date_str.split("-")
            int(y), int(m), int(d)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid date") from exc
        sub = "originals" if kind == "original" else ("web" if kind == "web" else "thumbs")
        path = data_root / "entries" / y / m / d / sub / filename
        try:
            resolved = path.resolve(strict=True)
            data_root.resolve(strict=True)
            if not str(resolved).startswith(str(data_root.resolve())):
                raise HTTPException(status_code=400, detail="bad path")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        return FileResponse(resolved)
```

- [ ] **Step 3: Create `admin.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}Admin — Driftnote{% endblock %}
{% block content %}
<h1>Admin</h1>
<section class="job-cards">
{% for card in cards %}
  <article class="card">
    <h2>{{ card.job }}</h2>
    <p>Last: {{ card.last_started_at or "(never)" }} — {{ card.last_status or "—" }}</p>
    <p>Last success: {{ card.last_success_at or "(never)" }}</p>
    <p>Failures (30d): {{ card.failures_30d }}</p>
    <a href="/admin/runs/{{ card.job }}">history</a>
  </article>
{% endfor %}
</section>

{% if recent_runs is defined %}
<h2>Runs for {{ job_filter }}</h2>
<table class="runs">
  <thead><tr><th>Started</th><th>Status</th><th>Detail</th><th>Error</th><th>Ack</th></tr></thead>
  <tbody>
  {% for r in recent_runs %}
    <tr class="status-{{ r.status }}">
      <td>{{ r.started_at }}</td>
      <td>{{ r.status }}</td>
      <td>{{ r.detail or "" }}</td>
      <td>{{ (r.error_kind or "") }} {{ (r.error_message or "") }}</td>
      <td>
        {% if r.status in ('error', 'warn') and not r.acknowledged_at %}
          <form method="post" action="/admin/runs/{{ r.id }}/ack" style="display:inline">
            <button>ack</button>
          </form>
        {% else %}
          {{ r.acknowledged_at or "" }}
        {% endif %}
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Implement `src/driftnote/web/routes_admin.py`**

```python
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
_JOBS = ["daily_prompt", "imap_poll", "digest_weekly", "digest_monthly", "digest_yearly", "backup", "disk_check"]


@dataclass(frozen=True)
class _JobCard:
    job: str
    last_started_at: str | None
    last_status: str | None
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
            cards.append(_JobCard(
                job=job,
                last_started_at=last.started_at if last else None,
                last_status=last.status if last else None,
                last_success_at=last_ok.started_at if last_ok else None,
                failures_30d=failures_30d,
            ))
        return cards

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_index(request: Request):
        now = iso_now()
        return templates.TemplateResponse(
            "admin.html.j2",
            {"request": request, "banners": compute_banners(engine, now=now), "cards": _build_cards(now)},
        )

    @app.get("/admin/runs/{job}", response_class=HTMLResponse)
    async def admin_drill(request: Request, job: str):
        now = iso_now()
        with session_scope(engine) as session:
            stmt = select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(100)
            rows = [
                JobRunRecord(
                    id=r.id, job=r.job, started_at=r.started_at, finished_at=r.finished_at,
                    status=r.status, detail=r.detail, error_kind=r.error_kind,
                    error_message=r.error_message, acknowledged_at=r.acknowledged_at,
                )
                for r in session.scalars(stmt)
            ]
        return templates.TemplateResponse(
            "admin.html.j2",
            {
                "request": request, "banners": compute_banners(engine, now=now),
                "cards": _build_cards(now), "recent_runs": rows, "job_filter": job,
            },
        )

    @app.post("/admin/runs/{run_id}/ack")
    async def admin_ack(run_id: int):
        with session_scope(engine) as session:
            acknowledge_run(session, run_id=run_id, at=iso_now())
        return RedirectResponse("/admin", status_code=303)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_web_routes_media_and_admin.py -v`
Expected: 5 passed.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/web/routes_media.py src/driftnote/web/routes_admin.py src/driftnote/web/templates/admin.html.j2 tests/integration/test_web_routes_media_and_admin.py
git commit -m "feat(web): media serving + admin dashboard with drill-down + ack"
```

---

### Chunk 9 closeout

**Acceptance criteria:**
- [ ] All Chunks 1–9 tests pass: `uv run pytest -v`.
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] 5 task commits in this chunk.

**Hand-off:** Chunk 10 wires CLI + full app composition (lifespan, scheduler startup, all middleware/routes installed in `create_app`).

---

## Chunk 10: CLI + full app composition

**Outcome of this chunk:** A Typer CLI with `serve`, `reindex`, `restore-imap`, `send-prompt` subcommands. The `create_app` factory now loads config, opens the DB, installs all middleware + routes, and starts the scheduler in a FastAPI lifespan.

### Task 10.1: `cli.py` — Typer commands

**Files:**
- Replace: `src/driftnote/cli.py` (was a placeholder; this version is the real one)
- Create: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for the CLI commands."""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import pytest
from sqlalchemy import Engine
from typer.testing import CliRunner

from driftnote.cli import app as cli_app
from driftnote.db import init_db, make_engine, session_scope
from driftnote.filesystem.layout import entry_paths_for
from driftnote.filesystem.markdown_io import EntryDocument, write_entry
from driftnote.repository.entries import EntryRecord, get_entry, upsert_entry


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_filesystem_only(data_root: Path, *, day: str = "2026-05-06", body: str = "from disk\n") -> None:
    paths = entry_paths_for(data_root, _date.fromisoformat(day))
    paths.dir.mkdir(parents=True, exist_ok=True)
    write_entry(
        paths.entry_md,
        EntryDocument(
            date=_date.fromisoformat(day), mood="💪", tags=["work"],
            created_at="2026-05-06T21:00:00Z", updated_at="2026-05-06T21:00:00Z",
            sources=["raw/x.eml"], body=body,
        ),
    )


def test_reindex_rebuilds_sqlite_from_filesystem(tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    db_path = data_root / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = make_engine(db_path)
    init_db(eng)
    _seed_filesystem_only(data_root)

    monkeypatch.setenv("DRIFTNOTE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("DRIFTNOTE_DB_PATH", str(db_path))

    result = runner.invoke(cli_app, ["reindex"])
    assert result.exit_code == 0, result.output

    eng2 = make_engine(db_path)
    with session_scope(eng2) as session:
        entry = get_entry(session, "2026-05-06")
    assert entry is not None
    assert entry.body_md == "from disk\n"
    assert entry.mood == "💪"


def test_reindex_warns_on_uiedited_entries_without_force(tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    db_path = data_root / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    make_engine(db_path)  # creates dir
    init_db(make_engine(db_path))
    paths = entry_paths_for(data_root, _date(2026, 5, 6))
    paths.dir.mkdir(parents=True, exist_ok=True)
    write_entry(
        paths.entry_md,
        EntryDocument(
            date=_date(2026, 5, 6), mood="💪", tags=[], created_at="2026-05-06T21:00:00Z",
            updated_at="2026-05-07T08:00:00Z",  # updated > created => UI edit
            sources=["raw/x.eml"], body="hand-edited\n",
        ),
    )

    monkeypatch.setenv("DRIFTNOTE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("DRIFTNOTE_DB_PATH", str(db_path))

    result = runner.invoke(cli_app, ["reindex", "--from-raw"])
    assert result.exit_code != 0
    assert "force" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_cli.py -v`

- [ ] **Step 3: Replace `src/driftnote/cli.py`**

```python
"""Typer CLI entrypoints: serve, reindex, restore-imap, send-prompt."""

from __future__ import annotations

import asyncio
import os
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path

import typer
from sqlalchemy import Engine

from driftnote.db import init_db, make_engine, session_scope
from driftnote.filesystem.layout import entry_paths_for
from driftnote.filesystem.markdown_io import read_entry
from driftnote.repository.entries import EntryRecord, replace_tags, upsert_entry
from driftnote.repository.media import MediaInput, replace_media

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Driftnote CLI")


def _data_root() -> Path:
    return Path(os.environ.get("DRIFTNOTE_DATA_ROOT", "/var/driftnote/data"))


def _db_path() -> Path:
    explicit = os.environ.get("DRIFTNOTE_DB_PATH")
    if explicit:
        return Path(explicit)
    return _data_root() / "index.sqlite"


def _walk_entries(data_root: Path):
    base = data_root / "entries"
    if not base.exists():
        return
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            for day_dir in sorted(month_dir.iterdir()):
                if (day_dir / "entry.md").exists():
                    yield day_dir / "entry.md"


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the FastAPI app via uvicorn."""
    import uvicorn
    from driftnote.app import create_app
    uvicorn.run(create_app, factory=True, host=host, port=port)


@app.command()
def reindex(
    from_raw: bool = typer.Option(False, "--from-raw", help="Re-derive entry.md from raw/*.eml"),
    force: bool = typer.Option(False, "--force", help="Override the UI-edits guard"),
) -> None:
    """Rebuild SQLite index from filesystem entries (and optionally re-parse raw .eml)."""
    data_root = _data_root()
    db_path = _db_path()
    engine = make_engine(db_path)
    init_db(engine)

    if from_raw and not force:
        for entry_md in _walk_entries(data_root):
            doc = read_entry(entry_md)
            if doc.updated_at > doc.created_at:
                typer.echo(
                    f"refusing to overwrite UI-edited entry {entry_md} "
                    "(updated_at > created_at). Pass --force to override.",
                    err=True,
                )
                raise typer.Exit(2)

    if from_raw:
        # Iterate every entry, parse all raw/*.eml in order, rewrite entry.md.
        from driftnote.config import load_config
        config_path = Path(os.environ["DRIFTNOTE_CONFIG"])
        config = load_config(config_path)
        from driftnote.ingest.pipeline import ingest_one
        for entry_md in _walk_entries(data_root):
            day_dir = entry_md.parent
            (day_dir / "entry.md").unlink(missing_ok=True)
            for eml in sorted((day_dir / "raw").glob("*.eml")):
                received_at = _parse_received_from_filename(eml.name)
                ingest_one(
                    raw=eml.read_bytes(), config=config, engine=engine,
                    data_root=data_root, received_at=received_at,
                )

    # Rebuild SQLite from current entry.md state.
    for entry_md in _walk_entries(data_root):
        doc = read_entry(entry_md)
        with session_scope(engine) as session:
            upsert_entry(
                session,
                EntryRecord(
                    date=doc.date.isoformat(),
                    mood=doc.mood,
                    body_text=doc.body,
                    body_md=doc.body,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                ),
            )
            replace_tags(session, doc.date.isoformat(), list(doc.tags))
            replace_media(
                session, doc.date.isoformat(),
                [MediaInput(kind="photo", filename=p.filename, caption=p.caption) for p in doc.photos]
                + [MediaInput(kind="video", filename=v.filename, caption=v.caption) for v in doc.videos],
            )

    typer.echo("reindex complete")


@app.command(name="restore-imap")
def restore_imap(
    since: str = typer.Option(..., "--since", help="YYYY-MM-DD"),
    until: str | None = typer.Option(None, "--until", help="YYYY-MM-DD (inclusive)"),
) -> None:
    """Re-fetch matching emails from IMAP and run them through ingestion."""
    asyncio.run(_run_restore(since, until))


@app.command(name="send-prompt")
def send_prompt(date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD; default today")) -> None:
    """Manually send today's (or another day's) prompt."""
    asyncio.run(_run_send_prompt(date))


async def _run_restore(since: str, until: str | None) -> None:
    from driftnote.config import load_config
    config = load_config(Path(os.environ["DRIFTNOTE_CONFIG"]))
    engine = make_engine(_db_path())
    init_db(engine)

    from driftnote.mail.imap import _connect, _extract_rfc822  # type: ignore[attr-defined]
    from driftnote.mail.transport import transports_from_config
    imap_t, _ = transports_from_config(config)

    client = await _connect(imap_t)
    try:
        for folder in (imap_t.inbox_folder, imap_t.processed_folder):
            await client.select(folder)
            criteria = f'SINCE {_imap_date(since)}'
            if until:
                criteria += f' BEFORE {_imap_date(_inclusive_until(until))}'
            result, data = await client.search(criteria)
            if result != "OK" or not data or not data[0]:
                continue
            for ident in data[0].split():
                ident_str = ident.decode("ascii")
                fetch_result, fetch_data = await client.fetch(ident_str, "(RFC822)")
                raw = _extract_rfc822(fetch_data)
                if raw is None:
                    continue
                from driftnote.ingest.pipeline import ingest_one
                ingest_one(
                    raw=raw, config=config, engine=engine,
                    data_root=_data_root(), received_at=datetime.now(tz=timezone.utc),
                )
    finally:
        try:
            await client.logout()
        except Exception:
            pass

    typer.echo("restore-imap complete")


async def _run_send_prompt(date_str: str | None) -> None:
    from driftnote.config import load_config
    from driftnote.mail.transport import transports_from_config
    from driftnote.scheduler.prompt_job import run_prompt_job

    config = load_config(Path(os.environ["DRIFTNOTE_CONFIG"]))
    engine = make_engine(_db_path())
    init_db(engine)
    _, smtp = transports_from_config(config)

    today = _date.fromisoformat(date_str) if date_str else _date.today()

    body_template_path = Path("src/driftnote/web/templates") / config.prompt.body_template.split("/")[-1]
    body = body_template_path.read_text() if body_template_path.exists() else "How was {date}?"

    await run_prompt_job(
        engine=engine, smtp=smtp, recipient=config.email.recipient,
        subject_template=config.prompt.subject_template,
        body_template_text=body, today=today,
    )
    typer.echo("prompt sent")


def _imap_date(iso: str) -> str:
    """Convert YYYY-MM-DD to IMAP DD-Mon-YYYY."""
    d = _date.fromisoformat(iso)
    return d.strftime("%d-%b-%Y")


def _inclusive_until(iso: str) -> str:
    from datetime import timedelta
    d = _date.fromisoformat(iso)
    return (d + timedelta(days=1)).isoformat()


def _parse_received_from_filename(name: str) -> datetime:
    from driftnote.filesystem.layout import parse_eml_received_at
    return parse_eml_received_at(name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_cli.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run mypy
git add src/driftnote/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): typer commands serve/reindex/restore-imap/send-prompt"
```

---

### Task 10.2: Full `create_app` with lifespan + scheduler

**Files:**
- Replace: `src/driftnote/app.py`
- Create: `src/driftnote/web/templates/emails/prompt.txt.j2`
- Create: `tests/integration/test_app_full.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for the fully-composed FastAPI app."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine


def _write_minimal_config(path: Path) -> None:
    path.write_text(
        '[schedule]\n'
        'daily_prompt   = "0 21 * * *"\n'
        'weekly_digest  = "0 8 * * 1"\n'
        'monthly_digest = "0 8 1 * *"\n'
        'yearly_digest  = "0 8 1 1 *"\n'
        'imap_poll      = "*/5 * * * *"\n'
        'timezone       = "Europe/London"\n'
        '[email]\n'
        'imap_folder            = "INBOX"\n'
        'imap_processed_folder  = "INBOX.Processed"\n'
        'recipient              = "you@example.com"\n'
        'sender_name            = "Driftnote"\n'
        'imap_host              = "x"\n'
        'imap_port              = 993\n'
        'imap_tls               = true\n'
        'smtp_host              = "x"\n'
        'smtp_port              = 587\n'
        'smtp_tls               = false\n'
        'smtp_starttls          = true\n'
        '[prompt]\n'
        'subject_template = "[Driftnote] How was {date}?"\n'
        'body_template    = "templates/emails/prompt.txt.j2"\n'
        '[parsing]\n'
        'mood_regex = \'^\\\\s*Mood:\\\\s*(\\\\S+)\'\n'
        'tag_regex  = \'#(\\\\w+)\'\n'
        'max_photos = 4\n'
        'max_videos = 2\n'
        '[digests]\n'
        'weekly_enabled  = true\n'
        'monthly_enabled = true\n'
        'yearly_enabled  = true\n'
        '[backup]\n'
        'retain_months = 12\n'
        'encrypt       = false\n'
        'age_key_path  = ""\n'
        '[disk]\n'
        'warn_percent  = 80\n'
        'alert_percent = 95\n'
        'check_cron    = "0 */6 * * *"\n'
        'data_path     = "/tmp"\n'
    )


def test_full_app_boots_and_serves_calendar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.toml"
    _write_minimal_config(cfg_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("DRIFTNOTE_CONFIG", str(cfg_path))
    monkeypatch.setenv("DRIFTNOTE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", "u@example.com")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", "p")
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    monkeypatch.setenv("DRIFTNOTE_ENVIRONMENT", "dev")

    from driftnote.app import create_app
    app = create_app(skip_startup_jobs=True)
    client = TestClient(app)

    healthz = client.get("/healthz")
    assert healthz.status_code == 200
    calendar = client.get("/")
    assert calendar.status_code == 200
```

- [ ] **Step 2: Create the prompt email template**

`src/driftnote/web/templates/emails/prompt.txt.j2`:

```
Hi,

How was {date}? Reply to this email with:

  Mood: <one emoji>

  Then a short paragraph or two (markdown supported).

  #hashtags anywhere in the body to tag it.

Up to 4 photos and 2 videos as attachments.

Just hit reply.

— Driftnote
```

- [ ] **Step 3: Replace `src/driftnote/app.py`**

```python
"""Full FastAPI app factory: config, DB, middleware, routes, scheduler."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI

from driftnote.alerts import AlertSender
from driftnote.config import Config, load_config
from driftnote.db import init_db, make_engine, session_scope
from driftnote.logging import configure_logging
from driftnote.mail.smtp import send_email
from driftnote.mail.transport import transports_from_config
from driftnote.scheduler.disk_job import run_disk_check
from driftnote.scheduler.poll_job import run_poll_job
from driftnote.scheduler.prompt_job import run_prompt_job
from driftnote.scheduler.runner import build_scheduler, cron, job_run
from driftnote.scheduler.digest_jobs import (
    run_monthly_digest,
    run_weekly_digest,
    run_yearly_digest,
)
from driftnote.web.auth import CloudflareAccessAuth, install_cf_access_middleware
from driftnote.web.routes_admin import install_admin_routes
from driftnote.web.routes_browse import install_browse_routes, install_static
from driftnote.web.routes_edit import install_edit_routes
from driftnote.web.routes_health import install_health_routes
from driftnote.web.routes_media import install_media_routes


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _SmtpAlertSender(AlertSender):
    def __init__(self, config: Config) -> None:
        _, self._smtp = transports_from_config(config)
        self._recipient = config.email.recipient

    async def send(self, *, kind: str, subject: str, body: str) -> None:
        await send_email(self._smtp, recipient=self._recipient, subject=subject, body_text=body)


def create_app(*, skip_startup_jobs: bool = False) -> FastAPI:
    """Compose the full app. `skip_startup_jobs=True` is for tests."""
    configure_logging(level="INFO", json_output=os.environ.get("DRIFTNOTE_ENVIRONMENT", "prod") != "dev")

    config_path = Path(os.environ["DRIFTNOTE_CONFIG"])
    config = load_config(config_path)
    data_root = Path(os.environ.get("DRIFTNOTE_DATA_ROOT", "/var/driftnote/data"))
    db_path = data_root / "index.sqlite"

    engine = make_engine(db_path)
    init_db(engine)

    web_base_url = os.environ.get("DRIFTNOTE_WEB_BASE_URL", "https://driftnote.example.com")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if skip_startup_jobs:
            yield
            return
        scheduler = build_scheduler(timezone=config.schedule.timezone)
        imap_t, smtp_t = transports_from_config(config)
        sender = _SmtpAlertSender(config)
        prompt_body = (Path(__file__).parent / "web" / config.prompt.body_template).read_text()

        async def _prompt_tick() -> None:
            with job_run(engine, "daily_prompt"):
                from datetime import date as _date
                await run_prompt_job(
                    engine=engine, smtp=smtp_t, recipient=config.email.recipient,
                    subject_template=config.prompt.subject_template,
                    body_template_text=prompt_body, today=_date.today(),
                )

        async def _poll_tick() -> None:
            with job_run(engine, "imap_poll"):
                await run_poll_job(config=config, engine=engine, data_root=data_root, imap=imap_t)

        async def _disk_tick() -> None:
            await run_disk_check(
                engine=engine, sender=sender, data_path=config.disk.data_path,
                warn_percent=config.disk.warn_percent, alert_percent=config.disk.alert_percent,
                now=_iso_now(),
            )

        scheduler.add_job(_prompt_tick, cron(config.schedule.daily_prompt, config.schedule.timezone))
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
                        engine=engine, smtp=smtp_t, recipient=config.email.recipient,
                        week_start=week_start, web_base_url=web_base_url,
                    )
            scheduler.add_job(_weekly_tick, cron(config.schedule.weekly_digest, config.schedule.timezone))

        if config.digests.monthly_enabled:
            async def _monthly_tick() -> None:
                from datetime import date as _date
                with job_run(engine, "digest_monthly"):
                    today = _date.today()
                    prev_month_year = today.year if today.month > 1 else today.year - 1
                    prev_month = today.month - 1 if today.month > 1 else 12
                    await run_monthly_digest(
                        engine=engine, smtp=smtp_t, recipient=config.email.recipient,
                        year=prev_month_year, month=prev_month, web_base_url=web_base_url,
                    )
            scheduler.add_job(_monthly_tick, cron(config.schedule.monthly_digest, config.schedule.timezone))

        if config.digests.yearly_enabled:
            async def _yearly_tick() -> None:
                from datetime import date as _date
                with job_run(engine, "digest_yearly"):
                    today = _date.today()
                    await run_yearly_digest(
                        engine=engine, smtp=smtp_t, recipient=config.email.recipient,
                        year=today.year - 1, web_base_url=web_base_url,
                    )
            scheduler.add_job(_yearly_tick, cron(config.schedule.yearly_digest, config.schedule.timezone))

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_app_full.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the FULL test suite — everything from all chunks**

Run: `uv run pytest -m "not live" -v`
Expected: all tests pass (full suite from Chunks 1–10).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy
git add src/driftnote/app.py src/driftnote/web/templates/emails/prompt.txt.j2 tests/integration/test_app_full.py
git commit -m "feat(app): full create_app with lifespan, scheduler, and all routes"
```

---

### Chunk 10 closeout

**Acceptance criteria:**
- [ ] Full test suite passes: `uv run pytest -v -m "not live"`.
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` is clean.
- [ ] `driftnote --help` lists the four subcommands.
- [ ] 2 task commits in this chunk.

**Hand-off:** Chunk 11 packages the artifact (Containerfile push, GHCR build workflow, systemd quadlet/timer, backup script, README/docs).

---

## Chunk 11: Deployment + docs

**Outcome of this chunk:** Production-deployable artifact: backup script + alert-email helper, systemd quadlet for the container, systemd backup timer, GHCR build workflow, complete README + Implementation.md + runbook. After this chunk Driftnote is ready to install on the RPi.

### Task 11.1: `scripts/backup.sh` + `scripts/alert-email.py`

**Files:**
- Create: `scripts/backup.sh`
- Create: `scripts/alert-email.py`

- [ ] **Step 1: Create `scripts/backup.sh`**

```bash
#!/usr/bin/env bash
# Monthly backup: tar.zst of data/entries + config.toml.
# Writes a row into /var/driftnote/data/index.sqlite job_runs.
# Optionally encrypts the archive via age if BACKUP_ENCRYPT=true.
#
# Invoked by /etc/systemd/system/driftnote-backup.service (oneshot timer).

set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/var/driftnote}"
BACKUP_DIR="$DATA_ROOT/backups"
NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MONTH_TAG="$(date -u +%Y-%m)"
ARCHIVE="$BACKUP_DIR/driftnote-$MONTH_TAG.tar.zst"
RETAIN_MONTHS="${RETAIN_MONTHS:-12}"
ENCRYPT="${BACKUP_ENCRYPT:-false}"
AGE_KEY_PATH="${AGE_KEY_PATH:-}"

mkdir -p "$BACKUP_DIR"

cd "$DATA_ROOT"
tar --zstd -cf "$ARCHIVE" config.toml data/entries

if [[ "$ENCRYPT" == "true" ]]; then
    if [[ -z "$AGE_KEY_PATH" || ! -f "$AGE_KEY_PATH" ]]; then
        echo "BACKUP_ENCRYPT=true but AGE_KEY_PATH unset/missing" >&2
        exit 2
    fi
    age -R "$AGE_KEY_PATH" -o "$ARCHIVE.age" "$ARCHIVE"
    rm -f "$ARCHIVE"
    ARCHIVE="$ARCHIVE.age"
fi

# Prune older than retention.
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'driftnote-*.tar.zst' -o -name 'driftnote-*.tar.zst.age' \) \
    -printf '%T@ %p\n' \
  | sort -nr \
  | tail -n +"$((RETAIN_MONTHS + 1))" \
  | awk '{print $2}' \
  | xargs -r rm -f

# Record success row in SQLite.
SIZE=$(stat -c%s "$ARCHIVE")
DETAIL=$(printf '{"archive":"%s","size_bytes":%s}' "$(basename "$ARCHIVE")" "$SIZE")
sqlite3 "$DATA_ROOT/data/index.sqlite" \
    "INSERT INTO job_runs(job, started_at, finished_at, status, detail) \
     VALUES('backup', '$NOW_ISO', '$NOW_ISO', 'ok', '$DETAIL');"

echo "backup ok: $ARCHIVE ($SIZE bytes)"
```

Make it executable:

```bash
chmod +x scripts/backup.sh
```

- [ ] **Step 2: Create `scripts/alert-email.py`**

```python
#!/usr/bin/env python3
"""Stand-alone alert-email helper.

Invoked by /etc/systemd/system/driftnote-backup.service via OnFailure=. Reads
SMTP credentials from the same env file the app uses. Subject + body come from
$1 and $2.
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: alert-email.py <subject> <body>", file=sys.stderr)
        return 2

    subject, body = sys.argv[1], sys.argv[2]

    user = os.environ["DRIFTNOTE_GMAIL_USER"]
    password = os.environ["DRIFTNOTE_GMAIL_APP_PASSWORD"]
    host = os.environ.get("DRIFTNOTE_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("DRIFTNOTE_SMTP_PORT", "587"))
    starttls = os.environ.get("DRIFTNOTE_SMTP_STARTTLS", "true").lower() == "true"

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = user
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if starttls:
            smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Smoke-test the backup script in dev**

```bash
mkdir -p /tmp/dn-backup-smoke/{data/entries,backups,config_src}
cp config/config.example.toml /tmp/dn-backup-smoke/config.toml
echo "demo" > /tmp/dn-backup-smoke/data/entries/dummy.md
sqlite3 /tmp/dn-backup-smoke/data/index.sqlite \
    "CREATE TABLE job_runs(id INTEGER PRIMARY KEY, job TEXT, started_at TEXT, finished_at TEXT, status TEXT, detail TEXT);"
DATA_ROOT=/tmp/dn-backup-smoke RETAIN_MONTHS=3 ./scripts/backup.sh
ls -lh /tmp/dn-backup-smoke/backups/
sqlite3 /tmp/dn-backup-smoke/data/index.sqlite "SELECT status, detail FROM job_runs;"
rm -rf /tmp/dn-backup-smoke
```

Expected: archive created, `status=ok` row inserted, output prints "backup ok: …".

- [ ] **Step 4: Commit**

```bash
git add scripts/backup.sh scripts/alert-email.py
git commit -m "ops: backup script + alert-email helper"
```

---

### Task 11.2: systemd quadlet + backup unit files

**Files:**
- Create: `deploy/driftnote.container`
- Create: `deploy/driftnote-backup.service`
- Create: `deploy/driftnote-backup.timer`
- Create: `deploy/README.md`

- [ ] **Step 1: `deploy/driftnote.container`**

```ini
# Install: copy to /etc/containers/systemd/driftnote.container, then
#   systemctl daemon-reload && systemctl enable --now driftnote.container
[Unit]
Description=Driftnote app
After=network-online.target
Wants=network-online.target

[Container]
Image=ghcr.io/maciej-makowski/driftnote:latest
Volume=/var/driftnote:/var/driftnote:Z
Environment=DRIFTNOTE_CONFIG=/var/driftnote/config.toml
Environment=DRIFTNOTE_DATA_ROOT=/var/driftnote/data
EnvironmentFile=/etc/driftnote/driftnote.env
PublishPort=127.0.0.1:8000:8000

[Service]
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: `deploy/driftnote-backup.service`**

```ini
# Install: copy to /etc/systemd/system/driftnote-backup.service.
[Unit]
Description=Driftnote monthly backup
OnFailure=driftnote-backup-failure.service

[Service]
Type=oneshot
EnvironmentFile=/etc/driftnote/driftnote.env
ExecStart=/usr/local/lib/driftnote/scripts/backup.sh
User=driftnote
Group=driftnote
```

- [ ] **Step 3: `deploy/driftnote-backup.timer`**

```ini
[Unit]
Description=Driftnote monthly backup timer

[Timer]
OnCalendar=*-*-01 03:00:00
Persistent=true
Unit=driftnote-backup.service

[Install]
WantedBy=timers.target
```

Plus `deploy/driftnote-backup-failure.service` for the OnFailure hook:

```ini
[Unit]
Description=Driftnote backup failure alert

[Service]
Type=oneshot
EnvironmentFile=/etc/driftnote/driftnote.env
ExecStart=/usr/local/lib/driftnote/scripts/alert-email.py "Driftnote backup failed" "See journalctl -u driftnote-backup.service for details."
```

- [ ] **Step 4: `deploy/README.md`** (host-side install instructions)

```markdown
# Deploying Driftnote on the Raspberry Pi

## 0. Prerequisites
- Fedora-derived host with `podman` + systemd's container quadlet support.
- A user `driftnote` (`useradd -r -m -s /sbin/nologin driftnote`).
- `cloudflared` already configured to route a hostname → `127.0.0.1:8000`.
- A directory `/var/driftnote/` owned by user `driftnote`.

## 1. Install scripts and units
```bash
sudo install -d /usr/local/lib/driftnote/scripts
sudo install -m 0755 scripts/backup.sh scripts/alert-email.py /usr/local/lib/driftnote/scripts/

sudo install -m 0644 deploy/driftnote.container /etc/containers/systemd/
sudo install -m 0644 deploy/driftnote-backup.service /etc/systemd/system/
sudo install -m 0644 deploy/driftnote-backup-failure.service /etc/systemd/system/
sudo install -m 0644 deploy/driftnote-backup.timer /etc/systemd/system/
```

## 2. Drop in config + secrets
```bash
sudo install -d -m 0700 -o root /etc/driftnote
sudo install -m 0600 -o root config/config.example.toml /var/driftnote/config.toml
sudo $EDITOR /etc/driftnote/driftnote.env   # see template below
```

Template for `/etc/driftnote/driftnote.env`:
```
DRIFTNOTE_GMAIL_USER=you@gmail.com
DRIFTNOTE_GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
DRIFTNOTE_CF_ACCESS_AUD=<application-AUD-tag>
DRIFTNOTE_CF_TEAM_DOMAIN=<your-team>.cloudflareaccess.com
DRIFTNOTE_WEB_BASE_URL=https://driftnote.<your-domain>
DRIFTNOTE_ENVIRONMENT=prod
```

## 3. Enable
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now driftnote.container
sudo systemctl enable --now driftnote-backup.timer
```

## 4. Verify
```bash
curl -s http://127.0.0.1:8000/healthz  # {"status":"ok",...}
sudo journalctl -u driftnote.container -f
```

## 5. Update
```bash
sudo podman pull ghcr.io/maciej-makowski/driftnote:latest
sudo systemctl restart driftnote.container
```
```

- [ ] **Step 5: Commit**

```bash
git add deploy/
git commit -m "ops: systemd quadlet + backup timer + deploy README"
```

---

### Task 11.3: GHCR build workflow

**Files:**
- Create: `.github/workflows/build-image.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: Build & Push Container Image
on:
  push:
    branches: [master]
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build & push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: Containerfile
          push: true
          platforms: linux/arm64,linux/amd64
          tags: |
            ghcr.io/${{ github.repository_owner }}/driftnote:latest
            ghcr.io/${{ github.repository_owner }}/driftnote:${{ github.sha }}
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/build-image.yml
git commit -m "ci: build + push driftnote image to GHCR on master"
```

---

### Task 11.4: Final docs (README, Implementation.md, runbook)

**Files:**
- Replace: `README.md`
- Create: `Implementation.md`
- Create: `docs/runbook.md`

- [ ] **Step 1: Replace `README.md`**

```markdown
# Driftnote

Personal email-driven journaling app. Daily prompt → reply with mood emoji + markdown body + optional photos/videos → calendar/tag/search-browsable web UI behind Cloudflare Access. Weekly/monthly/yearly digest emails.

## Architecture (one-paragraph)

A single Python 3.14 process: FastAPI + Jinja2 + HTMX for the web UI, APScheduler for daily prompt + IMAP poll + digest jobs in-process, SQLite (WAL + FTS5) as a derived index over a markdown-on-disk source of truth. Cloudflare Access fronts the web UI via a Cloudflare Tunnel. See [docs/superpowers/specs/2026-05-06-driftnote-design.md](docs/superpowers/specs/2026-05-06-driftnote-design.md) for the design spec.

## Quickstart (development)

```bash
uv sync
uv run pre-commit install
podman-compose --podman-path ./scripts/podman-remote.sh -f podman-compose.dev.yml up -d
uv run uvicorn --factory driftnote.app:create_app --reload
```

Open http://localhost:8000/ — empty calendar; smoke-test by sending an email through the GreenMail container.

## CLI

```bash
driftnote serve                 # start the web app
driftnote reindex               # rebuild SQLite from filesystem
driftnote reindex --from-raw    # also re-derive entry.md from raw/*.eml
driftnote restore-imap --since=2026-05-01
driftnote send-prompt           # manually send today's prompt
```

## Setting up Gmail (one-time)

1. Enable 2-Step Verification on your Google account.
2. Google Account → Security → App passwords → "Mail / Other (Driftnote)" → save the 16-character credential.
3. Settings → Filters and Blocked Addresses → "Create filter" with `subject:"[Driftnote]"` `from:me`. Apply label "Driftnote/Inbox", "Skip Inbox". Make sure the labels `Driftnote/Inbox` and `Driftnote/Processed` exist.

## Setting up Cloudflare Access

1. Cloudflare Zero Trust → Access → Applications → Add application → Self-hosted.
2. Domain: `driftnote.<your-domain>`. Save and copy the **Application Audience (AUD) Tag**.
3. Add a policy "Owner" with rule `email is <you>`.

## Production deployment

See [deploy/README.md](deploy/README.md). TL;DR:

```bash
sudo install -d /usr/local/lib/driftnote/scripts
sudo install -m 0755 scripts/* /usr/local/lib/driftnote/scripts/
sudo install -m 0644 deploy/* /etc/systemd/system/  # quadlet + timer + service
sudo install -m 0644 deploy/driftnote.container /etc/containers/systemd/
sudo install -m 0600 -o root /dev/stdin /etc/driftnote/driftnote.env <<<'...secrets...'
sudo install -m 0644 config/config.example.toml /var/driftnote/config.toml
sudo systemctl daemon-reload
sudo systemctl enable --now driftnote.container driftnote-backup.timer
```

## Backup and restore

A monthly tarball lands in `/var/driftnote/backups/`; copy newer ones to OneDrive (or any cold storage) at your convenience. Local retention defaults to 12 months.

To restore on a fresh host:

```bash
zstd -d -c /path/to/driftnote-2026-04.tar.zst | tar -x -C /var/driftnote/
sudo systemctl start driftnote.container
sudo podman exec systemd-driftnote driftnote reindex   # rebuild SQLite from disk
```

If recent days are missing from your latest backup, fetch them from Gmail directly:

```bash
sudo podman exec systemd-driftnote driftnote restore-imap --since=2026-05-01
```

## Testing

```bash
uv run pytest -m "not live"             # full suite minus tests requiring real Gmail
uv run pytest -v                         # everything (live tests opt-in)
```

Integration tests use **GreenMail** (in-memory SMTP+IMAP) via `testcontainers-python`. No real network or Gmail required for CI.

## Implementation notes

See [Implementation.md](Implementation.md) for design decisions, data model, and module boundaries. See [docs/runbook.md](docs/runbook.md) for operational procedures.

## License

MIT.
```

- [ ] **Step 2: Create `Implementation.md`**

```markdown
# Driftnote Implementation Notes

This document captures the *why* behind structural decisions. Most of the *what* lives in the spec ([`docs/superpowers/specs/2026-05-06-driftnote-design.md`](docs/superpowers/specs/2026-05-06-driftnote-design.md)) and the implementation plan ([`docs/superpowers/plans/2026-05-06-driftnote-implementation.md`](docs/superpowers/plans/2026-05-06-driftnote-implementation.md)).

## Module boundaries

- **`config`** loads TOML + env. Secrets are validated from env only and never sourced from TOML.
- **`logging`** is structlog → JSON; secret keys are redacted before any renderer sees them.
- **`models`** — SQLAlchemy ORM. The `Entry` table uses an explicit `id INTEGER PRIMARY KEY` so that FTS5 can use `content_rowid='id'`. Foreign keys reference `entries.date` (the natural key).
- **`db`** — engine factory + WAL/busy-timeout pragmas + FTS5 triggers. `session_scope` commits on success, rolls back on error.
- **`filesystem`** — single source of truth for path layout, atomic markdown_io, per-date `fcntl.flock`. Uses `newline=""` everywhere so bodies round-trip byte-for-byte.
- **`repository`** — typed CRUD over SQLAlchemy. ORM types do not leak above this layer; every public function returns a Pydantic record.
- **`mail`** — pluggable transport. Same code path against Gmail (App Password) and GreenMail (in-process tests).
- **`ingest`** — `parse.py` extracts mood/tags/body/attachments from a raw `.eml`; `attachments.py` derives photo web/thumb (Pillow + pillow-heif) and video poster (ffmpeg shell-out); `pipeline.py` orchestrates with per-date locks, idempotency on `Message-ID`, and whole-message rollback on pre-IMAP-move failure.
- **`scheduler`** — APScheduler runner with a `job_run` context manager that records every invocation in the `job_runs` table. Concrete jobs: `prompt_job`, `poll_job` (handles `imap_moved=0` retries), `digest_jobs`, `disk_job`.
- **`alerts`** — self-emailing wrapper with 24h dedup keyed on `error_kind`.
- **`web`** — auth middleware (Cloudflare Access JWT), browse/edit/media/admin routes, banners, Jinja2 + HTMX templates.

## Spec deviations / refinements

- **`entries.id`** — added to enable FTS5 `content_rowid`. Spec §2 prose treated `date` as the PK; this is a refinement, not a change to natural keys.
- **`ingested_messages.imap_moved`** — added so a poll-step-g failure can be retried by the next poll without re-running ingestion (spec §3.B IMAP retry path).
- **Locks at `data/locks/<date>.lock`** instead of locking the entry directory directly. Equivalent semantics; doesn't require the entry directory to exist for a first-time ingestion.

## Test pyramid

- **Unit** — pure functions, fixtures, no I/O beyond tmp dirs (≥40 tests).
- **Integration** — uses GreenMail container fixture for IMAP+SMTP, FastAPI `TestClient` for routes, real SQLite (in tmp). No real Gmail.
- **Live** — opt-in via `pytest -m live`; requires real Gmail credentials. Used when working on auth/IMAP edge cases.

## Configuration model

- Cron expressions, regexes, file size limits, digest enable flags live in `config.toml` (mounted into the container).
- Secrets (`DRIFTNOTE_GMAIL_USER`, etc.) come from env only.
- `DRIFTNOTE_IMAP_*` and `DRIFTNOTE_SMTP_*` env vars override the matching `[email]` config keys, used by `podman-compose.dev.yml` to point at GreenMail.

## Operational notes

- All datetimes stored as ISO 8601 UTC strings (`...Z`).
- WAL + 5s busy-timeout makes concurrent writes from the host-side backup script and the in-container app safe.
- The backup script runs OUTSIDE the container (host-side systemd timer); it writes a `job_runs` row directly to the same SQLite file.
- Digest cron expressions are evaluated in the configured timezone (`Europe/London` by default), which means DST transitions don't shift digest send times.
```

- [ ] **Step 3: Create `docs/runbook.md`**

```markdown
# Driftnote Runbook

## Daily

- App self-health: `curl -s http://localhost:8000/healthz | jq` (proxy through Cloudflare-Access if remote).
- New entry doesn't appear: check IMAP poll job in admin (`/admin/runs/imap_poll`). If failures: `journalctl -u driftnote.container | tail -100` and look for `event="ingest_one"`.

## After deployment

1. Send a test email to yourself with the daily prompt subject. Check it lands in `Driftnote/Inbox` per your filter.
2. Reply with `Mood: 💪\n\nshort entry. #smoke` and a small photo.
3. Watch the next 5-minute poll cycle (or `driftnote send-prompt --date=YYYY-MM-DD` then a quick reply).
4. Browse `https://driftnote.<your-domain>/` and click into the entry.

## Restore from backup

```bash
# 1. Pick the archive (latest).
ls -lh /var/driftnote/backups/

# 2. Stop the app to avoid SQLite contention.
sudo systemctl stop driftnote.container

# 3. Restore.
zstd -d -c /var/driftnote/backups/driftnote-YYYY-MM.tar.zst | sudo tar -x -C /var/driftnote/

# 4. Restart and reindex.
sudo systemctl start driftnote.container
sudo podman exec systemd-driftnote driftnote reindex

# 5. Recent days missing? Pull from IMAP.
sudo podman exec systemd-driftnote driftnote restore-imap --since=YYYY-MM-DD
```

## Common diagnostics

| Symptom | First check |
|---|---|
| `/healthz` returns `db: error` | SQLite file permission, disk full, WAL contention |
| Daily prompt never arrives | `journalctl -u driftnote.container | grep daily_prompt` — look for SMTP errors |
| Reply email never appears | Check IMAP filter is set correctly (label = `Driftnote/Inbox`, `Skip Inbox`). Then admin → imap_poll. |
| Disk banner stuck | `/admin` → disk_check history. Confirm `disk_state` row matches reality; if you've cleaned up, `sqlite3 .../index.sqlite "DELETE FROM disk_state"` |
| Backup script alert | `systemctl status driftnote-backup.service` and `journalctl -u driftnote-backup.service` |
| Cloudflare Access 403s | Confirm AUD tag and team domain in env file match the dashboard. JWKS rotates ~yearly. |
```

- [ ] **Step 4: Verify all tests still pass and lint is clean**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy
uv run pytest -m "not live" -v
```

- [ ] **Step 5: Commit**

```bash
git add README.md Implementation.md docs/runbook.md
git commit -m "docs: README, Implementation.md, runbook"
```

---

### Chunk 11 closeout

**Acceptance criteria:**
- [ ] All Chunks 1–11 tests pass: `uv run pytest -m "not live" -v`.
- [ ] Lint, format, type checks all clean.
- [ ] `scripts/backup.sh` smoke test in Task 11.1 Step 3 succeeds.
- [ ] Container builds locally: `podman build -f Containerfile -t driftnote:smoke .`.
- [ ] 4 task commits in this chunk.

**Hand-off:** Driftnote is feature-complete. The first real prod deploy follows `deploy/README.md`. Subsequent improvements (CSS polish, tests, Gmail OAuth migration if App Passwords are deprecated, etc.) belong in follow-up tickets, not in this initial implementation plan.

---

## Plan summary

11 chunks, one logical project. Each chunk is reviewable independently, ends with a green test suite + clean lint, and produces a meaningful deliverable.

**Execution recommendation:** Use `superpowers:subagent-driven-development` so each task gets a fresh subagent with focused context. After Chunk 2 lands, Chunks 3, 4, 5 can run in parallel worktrees. After Chunk 6 lands, Chunks 7, 8, 9 can run in parallel. The remaining chunks have linear dependencies.

**Out of scope:** Polish CSS (the templates ship a minimal but functional layout — refinement belongs in follow-ups), real-Gmail live tests in CI (kept opt-in via `@pytest.mark.live`), inline-CID rendering tweaks if real Gmail proves picky (one-line follow-up to wrap multipart/related), Gmail OAuth migration (a localized swap inside `mail/transport.py` if Google removes App Password support).
