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
| 3 | Filesystem + Repository | 2 | entry on disk + indexed in SQLite |
| 4 | Mail transport (IMAP + SMTP via GreenMail) | 2 | can send/receive via GreenMail |
| 5 | Ingestion pipeline | 3, 4 | end-to-end: `.eml` in → entry on disk + DB |
| 6 | Scheduler, jobs, alerts | 5 | scheduled prompts/polls/disk-checks/alerts run |
| 7 | Digest rendering | 3 | digest HTML rendered for fixed inputs |
| 8 | Web layer | 3, 7 | browse/edit/admin UI works locally |
| 9 | CLI + app composition | 5, 6, 7, 8 | full app boots, CLI commands work |
| 10 | Deployment, CI image build, docs | 9 | container in GHCR, README, runbook, quadlet |

**Parallelism opportunities for executors using `subagent-driven-development`:**
- After Chunk 2 lands on `master`: Chunks 3 and 4 can run in parallel worktrees.
- After Chunk 5 lands: Chunks 6, 7, and 8 can run in parallel worktrees.
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

CMD ["uvicorn", "driftnote.app:app", "--host", "0.0.0.0", "--port", "8000"]
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

The `entries` table uses an explicit INTEGER PRIMARY KEY `id` so that FTS5 can
reference it via `content_rowid='id'`. Foreign keys throughout reference
`entries.date` (the natural key), not `entries.id`.
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


def test_healthz_returns_ok(monkeypatch) -> None:
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", "u@example.com")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", "p")
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    monkeypatch.setenv("DRIFTNOTE_ENVIRONMENT", "dev")

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
"""FastAPI app factory. Full wiring lands in Chunk 8; this minimum gives us /healthz."""

from __future__ import annotations

from fastapi import FastAPI


def create_app(*, skip_startup_jobs: bool = False) -> FastAPI:
    """Create and configure the Driftnote FastAPI app.

    `skip_startup_jobs` is True in tests / when the harness only wants the HTTP
    surface. Full lifespan wiring (DB init, scheduler start) lands in Chunk 8.
    """
    app = FastAPI(title="Driftnote", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
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
podman --remote run --rm -d --name driftnote-smoke \
    -e DRIFTNOTE_GMAIL_USER=u@example.com \
    -e DRIFTNOTE_GMAIL_APP_PASSWORD=p \
    -e DRIFTNOTE_CF_ACCESS_AUD=aud \
    -e DRIFTNOTE_CF_TEAM_DOMAIN=team.example.com \
    -e DRIFTNOTE_ENVIRONMENT=dev \
    -p 8000:8000 driftnote:smoke
sleep 3
curl -sf http://localhost:8000/healthz
podman --remote stop driftnote-smoke
podman --remote rmi driftnote:smoke
```

Expected: `{"status":"ok"}` printed; exit code 0.

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
* @<your-github-handle>
```

(The implementer should replace `<your-github-handle>` with the actual GitHub username at first deploy; it's left as a placeholder so the plan is portable.)

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
