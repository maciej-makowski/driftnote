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
