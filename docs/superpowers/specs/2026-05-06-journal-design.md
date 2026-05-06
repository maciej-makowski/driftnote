# Journal — Design Spec

**Status:** approved-pending-implementation
**Date:** 2026-05-06
**Owner:** Maciej Makowski

## Purpose

A personal "between-micro-and-regular" journaling app that prompts the user for a daily entry by email, ingests the reply into a markdown-on-disk store, exposes a web UI for browsing/editing, and emails periodic digests. Self-hosted on a Raspberry Pi.

## Goals

- One short daily entry per day, prompted and submitted by email.
- Mood emoji + free-form markdown body + hashtags + photo and video attachments per entry.
- Web UI to browse by calendar, tag-cloud, and full-text search; edit entries.
- Weekly / monthly / yearly digest emails with an emoji moodboard, stats, and selected media.
- Runs on a Raspberry Pi as a Podman container behind Cloudflare Tunnel + Cloudflare Access.
- Filesystem-first storage so entries remain human-readable and survive any tool change.
- Simple, restorable backups suitable for manual upload to OneDrive / cold storage.

## Non-goals (v1)

- Multi-user support, roles, sharing.
- Mobile-native client (responsive web UI only).
- LLM-generated summaries / sentiment analysis.
- Encryption of the live data directory at rest (backups can be encrypted).
- Browser push notifications.
- Public-internet exposure outside Cloudflare Access.

---

## §1. Architecture overview

A single Python process on the RPi (Podman container) handles HTTP, scheduling, IMAP poll, SMTP send, ingestion, and image/video processing. SQLite is a derived index; the filesystem under `data/entries/` is the source of truth.

```
                   ┌────────────────────────────────────────────┐
   Cloudflare      │  Raspberry Pi (Podman + systemd quadlet)   │
   Tunnel +        │                                            │
   Access ───HTTP──┤  FastAPI app (Jinja2 + HTMX)               │
                   │    ├── HTTP routes (browse / edit / media) │
                   │    ├── APScheduler                         │
                   │    │     ├── daily prompt sender           │
                   │    │     ├── IMAP poller                   │
                   │    │     ├── digest jobs (week/month/year) │
                   │    │     └── disk check                    │
                   │    └── ingestion pipeline                  │
                   │                                            │
                   │  Bind-mounted volume:                      │
                   │    /var/journal/data/entries/YYYY/MM/DD/   │
                   │    /var/journal/data/index.sqlite          │
                   │    /var/journal/config.toml                │
                   │                                            │
                   │  Host systemd timer:                       │
                   │    monthly tar.zst → /var/journal/backups/ │
                   └──────────────┬─────────────────────────────┘
                                  │ SMTP (587) / IMAPS (993)
                                  ▼
                              Gmail (App Password)
```

### Module boundaries

- **HTTP layer** depends on `repository/`, `filesystem/`, and `digest/` (for inline previews). It does **not** import `mail/` or `ingest/`.
- **Ingestion** depends on `filesystem/`, `repository/`, and `mail/transport.py` (for size limits). It does **not** import `web/` or `scheduler/`.
- **Scheduler** is the only module that imports from `ingest/`, `digest/`, `mail/`, and disk-check — it's the orchestrator.
- **Repository** depends only on `db.py` and `models.py`.
- **Mail** is a transport layer that does not know about entries — bytes in / bytes out.
- **Cloudflare Access JWT verification** is FastAPI middleware; bypassed when `ENVIRONMENT=dev`.

---

## §2. Data model

### Filesystem (source of truth)

```
/var/journal/
├── config.toml
├── data/
│   ├── entries/
│   │   └── 2026/05/06/
│   │       ├── entry.md              ← parsed, displayed, editable
│   │       ├── raw/
│   │       │   ├── 2026-05-06T21-30-15Z.eml
│   │       │   └── 2026-05-07T02-15-22Z.eml
│   │       ├── originals/
│   │       │   ├── IMG_4521.heic
│   │       │   └── VID_4522.mov
│   │       ├── web/
│   │       │   └── IMG_4521.jpg      ← 1600px, EXIF stripped
│   │       └── thumbs/
│   │           ├── IMG_4521.jpg      ← 320px
│   │           └── VID_4522.jpg      ← ffmpeg poster frame at ~1s
│   └── index.sqlite                  ← derived, rebuildable
├── backups/journal-2026-04.tar.zst
└── logs/                             ← rotated journald output
```

### `entry.md` format

YAML frontmatter + markdown body. When multiple replies arrive for the same date, body sections are concatenated, separated by `---`. The frontmatter `sources` array preserves the chronological order of `raw/*.eml` files used to derive the body.

```markdown
---
date: 2026-05-06
mood: 💪
tags: [work, cooking]
photos:
  - filename: IMG_4521.heic
    caption: ""
videos:
  - filename: VID_4522.mov
created_at: 2026-05-06T21:30:15Z
updated_at: 2026-05-07T02:15:22Z
sources:
  - raw/2026-05-06T21-30-15Z.eml
  - raw/2026-05-07T02-15-22Z.eml
---

Long day at work, finally cracked the migration bug. #work

---

Forgot to mention — made a decent risotto. #cooking
```

### SQLite schema (derived index)

```sql
CREATE TABLE entries (
  date          TEXT PRIMARY KEY,         -- 'YYYY-MM-DD'
  mood          TEXT,                      -- single emoji or NULL
  body_text     TEXT NOT NULL,             -- plain text from markdown body, for FTS
  body_md       TEXT NOT NULL,             -- raw markdown body (no frontmatter)
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE tags (
  date  TEXT NOT NULL REFERENCES entries(date) ON DELETE CASCADE,
  tag   TEXT NOT NULL,                     -- lowercase
  PRIMARY KEY (date, tag)
);
CREATE INDEX idx_tags_tag ON tags(tag);

CREATE TABLE media (
  id        INTEGER PRIMARY KEY,
  date      TEXT NOT NULL REFERENCES entries(date) ON DELETE CASCADE,
  kind      TEXT NOT NULL CHECK (kind IN ('photo','video')),
  filename  TEXT NOT NULL,
  ord       INTEGER NOT NULL,
  caption   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_media_date ON media(date);

CREATE TABLE ingested_messages (
  message_id  TEXT PRIMARY KEY,            -- email Message-ID header
  date        TEXT NOT NULL REFERENCES entries(date),
  eml_path    TEXT NOT NULL,               -- relative to entry dir
  ingested_at TEXT NOT NULL
);

CREATE TABLE pending_prompts (
  date         TEXT PRIMARY KEY,
  message_id   TEXT NOT NULL UNIQUE,       -- outgoing prompt's Message-ID
  sent_at      TEXT NOT NULL
);

CREATE TABLE job_runs (
  id            INTEGER PRIMARY KEY,
  job           TEXT NOT NULL,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  status        TEXT NOT NULL,             -- 'running'|'ok'|'warn'|'error'
  detail        TEXT,
  error_kind    TEXT,
  error_message TEXT,
  acknowledged_at TEXT
);
CREATE INDEX idx_job_runs_job_started ON job_runs(job, started_at DESC);

CREATE TABLE disk_state (
  threshold_percent INTEGER PRIMARY KEY,
  crossed_at        TEXT NOT NULL
);

CREATE VIRTUAL TABLE entries_fts USING fts5(
  body_text, content='entries', content_rowid='rowid'
);
-- triggers keep entries_fts in sync with entries (standard FTS5 pattern)
```

SQLite runs in **WAL mode** with a 5s busy-handler so the host-side backup script and the in-container app can both write safely.

---

## §3. Request flows

### A. Daily prompt out (default 21:00 local)

1. APScheduler fires `send_daily_prompt`.
2. Render `prompt.md.j2` with `{date, recipient_name}`; subject from `subject_template`.
3. SMTP-send to `recipient`. The outgoing `Message-ID` is recorded in `pending_prompts`.
4. Log success/failure; record a `job_runs` row.

### B. IMAP poll → ingest (default every 5 min)

1. Connect IMAPS to `Journal/Inbox`, search `UNSEEN`.
2. For each message:
   a. Read `Message-ID`. Skip if already in `ingested_messages` (idempotency).
   b. Read `In-Reply-To`. If it matches a row in `pending_prompts`, the entry's date is that prompt's date. Otherwise use the message's `Date` header (in configured timezone) and log a warning.
   c. Strip quoted text (heuristic: lines after `On … wrote:` plus `>`-prefixed lines).
   d. Extract: mood (configured regex), tags (configured regex), body, attachments.
   e. Create `data/entries/YYYY/MM/DD/` if absent. Write `raw/<received-utc>.eml` (full original bytes). Save attachments to `originals/`. Generate `web/` and `thumbs/` derivatives. Append-or-create `entry.md` (regenerate frontmatter; append body section with `---` separator if entry already exists).
   f. Upsert SQLite: `entries`, `tags`, `media`, `ingested_messages`.
   g. IMAP: copy message to `Journal/Processed`, mark deleted in `Journal/Inbox`, EXPUNGE.
3. On any per-message failure: roll back filesystem writes for that message (no `entry.md` mutation, no `raw.eml` written, no SQLite row), leave the message UNSEEN in `Journal/Inbox`, log error with `Message-ID`, continue with next message.

### C. Web UI

All routes (in non-dev) require valid `Cf-Access-Jwt-Assertion` header verified against Cloudflare's public keys.

- `GET /` — current month calendar; cell content = mood emoji + first photo's thumbnail. Empty cells dimmed.
- `GET /entry/{date}` — markdown rendered to HTML; photos in a gallery (thumbs lazy-load, click → web-size lightbox, click → original); videos via `<video>` from original.
- `GET /entry/{date}/edit` — HTMX form: emoji picker, tag chips with autocomplete, plain `<textarea>` markdown editor with HTMX-driven live preview, photo/video reorder + caption + delete.
- `POST /entry/{date}` — applies edits: rewrites `entry.md`, updates SQLite. Never modifies `raw/*.eml`.
- `GET /tags` — tag cloud sized by frequency; click → `/?tag=work`.
- `GET /search?q=...` — FTS5 results.
- `GET /media/{date}/{kind}/{filename}` — serves bytes; `kind ∈ {original, web, thumb}`.
- `GET /admin` — job/backup/disk dashboard (see §6).
- `GET /healthz`, `GET /readyz` — health endpoints (see §6).

### D. Digest send (configured cron)

Each digest type independently enabled in config. Cron defaults: weekly Mon 08:00, monthly 1st 08:00, yearly Jan 1 08:00.

- **Weekly:** subject `[Journal] Week of Mon DD MMM → Sun DD MMM`. 7-emoji moodboard row. Per-day section with date heading, emoji, body HTML, inline thumbnails (CID-attached, link to web UI for full-size). Tag chips footer.
- **Monthly:** subject `[Journal] Month YYYY`. Calendar-grid moodboard (rows = weeks). Stats line (entries / total days, top emoji, top tags). 4–6 highlight days picked by heuristic: days with photos *and* at least one rare tag (used <3 times that month). Each highlight: date, emoji, first ~2 sentences, one inline thumbnail. Link to web UI for full month.
- **Yearly:** subject `[Journal] YYYY in review`. GitHub-style 52-week × 7-day emoji grid. Stats: total entries, longest streak, top 10 emojis, top 10 tags. One photo per month (most-tagged day's first photo, fallback to any photo). Link to web UI.

Each digest run records a `job_runs` row.

### E. Backup (host-side systemd timer, monthly)

1. `systemd-tmpfiles` ensures `/var/journal/backups/` exists with correct mode.
2. Timer fires `journal-backup.service` on the 1st at 03:00:
   - `tar --zstd -cf .../journal-YYYY-MM.tar.zst -C /var/journal config.toml data/entries`
   - If `backup.encrypt=true`, pipe through `age -p` using the configured key path.
   - Prune local `backups/journal-*.tar.zst` files older than `backup.retain_months` (default **12**).
   - Write a `job_runs` row directly into `data/index.sqlite` (WAL-safe).
3. Service `OnFailure=` invokes `scripts/alert-email.py` to self-email via SMTP.

---

## §4. Deployment, configuration, secrets

### Dev (laptop)

- `podman-compose.dev.yml` brings up the app container plus a **GreenMail** mail container.
  - `greenmail/standalone:2.1.4`, ports `3025` (SMTP), `3143` (IMAP), `8080` (REST API for fixture seeding). User `you:apppwd:you@example.com` pre-seeded.
- App env overrides point IMAP/SMTP at `mail:3143`/`mail:3025` with TLS off; same code path as prod.
- `ENVIRONMENT=dev` skips JWT verification; runs on `http://localhost:8000` with `uvicorn --reload`.

### Prod (RPi)

- Image built from `Containerfile` and pushed to `ghcr.io/<you>/journal:latest` by GitHub Actions on `master`.
- RPi pulls and runs as a systemd quadlet:

```ini
# /etc/containers/systemd/journal.container
[Unit]
Description=Journal app
After=network-online.target
Wants=network-online.target

[Container]
Image=ghcr.io/<you>/journal:latest
Volume=/var/journal:/var/journal:Z
Environment=JOURNAL_CONFIG=/var/journal/config.toml
EnvironmentFile=/etc/journal/journal.env
PublishPort=127.0.0.1:8000:8000
Exec=uvicorn journal.app:app --host 0.0.0.0 --port 8000

[Service]
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- `cloudflared` runs as a separate systemd service routing `journal.<your-domain>` → `http://127.0.0.1:8000` (existing pattern from another app).
- Cloudflare Access policy: `email is <you>`.
- Backup timer + service installed under `/etc/systemd/system/`.

### Configuration file (`/var/journal/config.toml`)

```toml
[schedule]                              # cron syntax, evaluated in [timezone]
daily_prompt   = "0 21 * * *"
weekly_digest  = "0 8 * * 1"
monthly_digest = "0 8 1 * *"
yearly_digest  = "0 8 1 1 *"
imap_poll      = "*/5 * * * *"
timezone       = "Europe/London"

[email]
imap_folder            = "Journal/Inbox"
imap_processed_folder  = "Journal/Processed"
recipient              = "you@gmail.com"
sender_name            = "Your Journal"
imap_host              = "imap.gmail.com"
imap_port              = 993
imap_tls               = true
smtp_host              = "smtp.gmail.com"
smtp_port              = 587
smtp_starttls          = true

[prompt]
subject_template = "[Journal] How was {date}?"
body_template    = "templates/prompt.md.j2"

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
```

### Secrets (`/etc/journal/journal.env`, mode 0600, root-owned)

```
JOURNAL_GMAIL_USER=you@gmail.com
JOURNAL_GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
JOURNAL_CF_ACCESS_AUD=<application-AUD-tag>
JOURNAL_CF_TEAM_DOMAIN=<your-team>.cloudflareaccess.com
JOURNAL_AGE_KEY_PATH=/etc/journal/backup.age.key   # only if encrypted
```

App startup validates secrets and fails fast on missing/malformed values.

### Setup walkthrough (will be in README)

1. **Gmail App Password.** Google Account → Security → 2-Step Verification (must be on) → App passwords → "Mail / Other (Journal)" → save the 16-char password.
2. **Gmail filter + labels.** Create labels `Journal/Inbox` and `Journal/Processed`. Settings → Filters and Blocked Addresses → Create filter: `subject:"[Journal]"` `from:me` → action: Apply label "Journal/Inbox", Skip Inbox.
3. **Cloudflare Access.** Zero Trust dashboard → Access → Applications → Add → Self-hosted → domain `journal.<yours>` → Policy "Owner" with `email is <you>` → save. Copy Application AUD tag.
4. **RPi prep.** `sudo mkdir -p /var/journal/{data,backups,logs}`; `sudo chown <user> /var/journal/{data,backups,logs}`. Drop in `config.toml` and `journal.env`.
5. **Systemd.** Install quadlet + backup unit files, then `systemctl daemon-reload && systemctl enable --now journal.container journal-backup.timer`.

---

## §5. Testing strategy

### Unit (pytest, fast, no I/O beyond tmp dirs)

- `test_parse.py` — fixtures of `.eml` files: plain reply, multipart HTML+plain, quoted thread, mood marker present/absent, no tags / multiple tags, photos only / videos only / mixed, oversized attachment, non-image attachment, threaded afterthought reply.
- `test_markdown_io.py` — round-trip property test (`hypothesis`): `entry → md → entry` is identity for emoji/tag fuzz.
- `test_repository.py` — CRUD + queries for entries, tags, media, jobs, ingested.
- `test_attachments.py` — Pillow + pillow-heif + ffmpeg shell-out happy path and failure modes.
- `test_digest_render.py` — snapshot tests of rendered HTML for fixed inputs (week/month/year).
- `test_jwt_middleware.py` — valid / expired / wrong-aud / malformed JWT.
- `test_alerts.py` — 24h dedup logic.
- `test_disk_job.py` — threshold crossing, dedup, alert formatting.

### Integration (still no real network)

- `test_ingest_pipeline.py` — drop `.eml` into a fake mailbox → assert filesystem layout, SQLite contents, idempotency on second run.
- `test_imap_roundtrip.py` — via GreenMail (`testcontainers-python`), end-to-end: app sends prompt, GreenMail receives, harness "user" replies, app polls, ingestion verified.
- `test_smtp_send.py` — via GreenMail.
- `test_scheduler_cron.py` — APScheduler with `MemoryJobStore` + `freezegun`; verify each job fires on the right cron in `Europe/London`, including DST transitions.
- `test_routes_*.py` — FastAPI `TestClient` with stubbed JWT middleware.
- `test_reindex_cli.py` — populated `entries/` tree → drop `index.sqlite` → reindex → identical row set.

### Live (opt-in, `@pytest.mark.live`)

- Real Gmail account dedicated to testing. Run on demand for auth/IMAP edge-case work. Not in CI.

### CI (GitHub Actions, every PR + push to master)

- Jobs: `ruff check`, `ruff format --check`, `mypy`, `pytest -m 'not live'` (uses GreenMail via testcontainers), `podman build` smoke.
- `astral-sh/setup-uv` with cache.
- Lint auto-fix on a separate job that commits back if mechanical fixes exist (note: the `GITHUB_TOKEN`-pushed commit will not retrigger workflows — acceptable).

### Pre-commit hooks (`.pre-commit-config.yaml`)

- `ruff` (lint + format + import sort) on staged files.
- `pytest -m 'not live and not slow'` — fast unit slice.
- README documents `uv run pre-commit install` post-clone.

### Manual smoke checks (in `docs/runbook.md`)

After every prod deploy: send a test email with mood + photo, watch logs, verify in web UI; send afterthought reply and verify append; edit via UI and verify markdown updated; run `journal reindex` and verify idempotency.

---

## §6. Failure modes & observability

### Logging

Structured JSON to stdout (`structlog`); journald captures via systemd. Each line carries `event`, `date`, `message_id` (where relevant), `error_kind`, `request_id` for HTTP.

### Failure matrix

| Failure | Detection | Response |
|---|---|---|
| Gmail SMTP refused | exception in send job | log ERROR, retry 3× exponential backoff (1m / 5m / 15m), then give up; next scheduled run tries fresh. |
| Gmail IMAP auth fails | exception in poll job | log ERROR; next scheduled poll retries. After 5 consecutive failures, self-email an alert (best-effort). |
| Reply has no matching `In-Reply-To` | parse step | WARNING; entry date taken from message `Date` header; ingestion proceeds. |
| No mood marker and no emoji | parse step | WARNING; `mood=NULL`; digest moodboard renders neutral placeholder. |
| Attachment count exceeds limits | parse step | WARNING; first N kept; dropped filenames logged and noted in `entry.md` as `<!-- dropped: ... -->`. |
| Attachment fails to write (disk full / perms) | filesystem step | ERROR; whole-message rollback (no `entry.md` mutation, no `raw.eml`, no SQLite row); message left UNSEEN; next poll retries. |
| Corrupt image / unreadable HEIC | derivative generation | WARNING; original kept; web/thumb skipped; UI placeholder. |
| Video has no decodable first frame | ffmpeg poster step | WARNING; thumb falls back to generic icon; original still playable. |
| Two replies for same date concurrently | ingestion | per-date `fcntl.flock` on entry directory serializes; both `raw.eml` files saved. |
| User edits `entry.md` on disk | next page load reads stale SQLite | documented: edit via UI; CLI `journal reindex` is the recovery for hand-edits. |
| SQLite locked | OperationalError | retry with 5s busy-handler; reindex CLI documented to run with app stopped. |
| Cloudflare Access JWT invalid | middleware | 403; INFO log unless threshold exceeded. |
| Backup script fails | timer service exit non-zero | systemd notifies; standalone backup script also self-emails. |
| Disk full (writes fail) | any write | reads still served; writes ERROR; admin banner + email already triggered at 80% / 95% before reaching full. |

### Health endpoints

- `GET /healthz` — `200 {"status":"ok","db":"ok","data_dir":"ok","last_imap_poll":"...","last_imap_poll_status":"ok"}`.
- `GET /readyz` — `200` only after first DB open + config validation.

### Admin panel (`GET /admin`)

- One card per job: Daily prompt, IMAP poll, Weekly/Monthly/Yearly digest, Backup, Disk check.
- Each card: last status, last run timestamp, last success timestamp, failure count in last 30 days.
- Drill-down: paginated last 100 runs with timestamps, status, detail, expandable error message.
- **Banners** on every page when unhealthy:
  - Any unacknowledged `error` row in last 7 days → red banner with link to admin.
  - Last successful backup older than 35 days → amber.
  - Disk usage ≥ 80% → amber; ≥ 95% → red.
- **Acknowledge:** clicking a failure row sets `acknowledged_at`; banners ignore acknowledged failures. History preserved.

### Disk monitoring

- Job `disk_check` runs per `disk.check_cron` (default every 6h). `shutil.disk_usage("/var/journal/data")`.
- On crossing 80% (transition from below), self-email **once** with current usage and projected days-remaining (linear extrapolation from last 30 days of growth). State tracked via `disk_state` table; re-alert only after dropping back below the threshold.
- On 95% crossing, second email with stronger subject.
- Both thresholds also surface in admin panel.

### Email alert dedup

All self-emails (IMAP failure, disk threshold, backup failure) check `job_runs` for an alert of the same `error_kind` in the last 24h; if found, alert is logged-only, not re-sent.

### CLI tools

- `journal reindex [--from-raw] [--force]`
  - Default: walk `data/entries/`, parse every `entry.md`, rebuild `index.sqlite` from scratch.
  - `--from-raw`: also re-derive `entry.md` content from `raw/*.eml` (overwrites manual UI edits — requires `--force` if any entry has `updated_at > created_at`).
- `journal restore-imap --since=YYYY-MM-DD [--until=YYYY-MM-DD]`
  - Fetch matching emails from configured IMAP folders (Inbox + Processed); run them through normal ingestion. Idempotent via `ingested_messages`.
- `journal send-prompt [--date=YYYY-MM-DD]`
  - Manual trigger of a prompt for a given date (default: today). Useful if the scheduled job missed.

---

## §7. Project structure

```
journal/
├── pyproject.toml                  # uv-managed
├── uv.lock
├── README.md
├── Implementation.md
├── .pre-commit-config.yaml
├── .github/
│   ├── workflows/ci.yml
│   ├── workflows/build-image.yml
│   └── CODEOWNERS
├── Containerfile
├── podman-compose.dev.yml
├── scripts/
│   ├── podman-remote.sh
│   ├── backup.sh
│   └── alert-email.py
├── deploy/
│   ├── journal.container
│   ├── journal-backup.service
│   ├── journal-backup.timer
│   └── README.md
├── config/
│   ├── config.example.toml
│   └── prompt.example.md.j2
├── src/journal/
│   ├── __init__.py
│   ├── app.py                      # FastAPI factory, middleware, lifespan
│   ├── cli.py                      # typer: serve, reindex, restore-imap, send-prompt
│   ├── config.py                   # pydantic-settings (TOML + env)
│   ├── logging.py
│   │
│   ├── models.py                   # SQLAlchemy ORM + pydantic DTOs
│   ├── db.py                       # engine, session, migrations, FTS triggers
│   ├── repository/
│   │   ├── entries.py
│   │   ├── media.py
│   │   ├── jobs.py
│   │   └── ingested.py
│   │
│   ├── filesystem/
│   │   ├── layout.py
│   │   ├── markdown_io.py
│   │   └── locks.py
│   │
│   ├── ingest/
│   │   ├── pipeline.py
│   │   ├── parse.py
│   │   └── attachments.py
│   │
│   ├── mail/
│   │   ├── imap.py
│   │   ├── smtp.py
│   │   └── transport.py
│   │
│   ├── scheduler/
│   │   ├── runner.py               # APScheduler + job_run wrapping context manager
│   │   ├── prompt_job.py
│   │   ├── poll_job.py
│   │   ├── digest_jobs.py
│   │   └── disk_job.py
│   │
│   ├── digest/
│   │   ├── weekly.py
│   │   ├── monthly.py
│   │   ├── yearly.py
│   │   └── moodboard.py
│   │
│   ├── web/
│   │   ├── routes_browse.py
│   │   ├── routes_edit.py
│   │   ├── routes_media.py
│   │   ├── routes_admin.py
│   │   ├── routes_health.py
│   │   ├── auth.py
│   │   ├── banners.py
│   │   ├── templates/
│   │   │   ├── base.html.j2
│   │   │   ├── calendar.html.j2
│   │   │   ├── entry.html.j2
│   │   │   ├── entry_edit.html.j2
│   │   │   ├── tags.html.j2
│   │   │   ├── search.html.j2
│   │   │   ├── admin.html.j2
│   │   │   ├── digests/{weekly,monthly,yearly}.html.j2
│   │   │   └── emails/prompt.txt.j2
│   │   └── static/{style.css, htmx.min.js}
│   │
│   └── alerts.py
│
└── tests/
    ├── conftest.py                 # tmp data dir, GreenMail fixture, freezegun
    ├── fixtures/{emails,entries,images}/
    ├── unit/...
    └── integration/...
```

### Key dependencies

- **Runtime:** `fastapi`, `uvicorn`, `sqlalchemy`, `apscheduler`, `jinja2`, `pillow`, `pillow-heif`, `aioimaplib`, `aiosmtplib`, `structlog`, `pydantic-settings`, `pyjwt[crypto]`, `typer`, `markdown-it-py`, `mistletoe`.
- **Dev/test:** `pytest`, `pytest-asyncio`, `freezegun`, `hypothesis`, `testcontainers`, `ruff`, `mypy`, `pre-commit`.
- **Container base:** `python:3.14-slim` + apt: `libheif1`, `ffmpeg`, `tzdata`.

---

## §8. Risks, deferred items, open assumptions

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| Gmail App Passwords removed for personal accounts | `mail/transport.py` abstraction localizes a swap to OAuth (with the 7-day-or-verify trade-off). |
| HEIC decoding requires `libheif` on aarch64 | Container image installs `libheif1`; CI runs HEIC fixture. |
| `ffmpeg` required for video poster | Container installs `ffmpeg`; CI runs `.mov` fixture. |
| User edits `entry.md` on disk while app runs | UI is the supported edit path; `journal reindex` is the documented recovery. |
| `reindex --from-raw` overwrites UI edits | Prints warning; requires `--force` if any entry has `updated_at > created_at`. |
| Cloudflare Tunnel down → web UI unreachable | App still ingests email and sends digests; tunnel restart is independent. |
| Backup script + app concurrent SQLite writes | WAL mode + 5s busy-handler; backup writes one row per run. |
| DST transitions in cron timing | All cron via APScheduler `ZoneInfo` (`Europe/London`); tests verify across DST boundaries. |
| Email account change | `config.toml` + secrets edit only; no code change; entries unaffected. |

### Deferred (out of scope for v1)

- FTS ranking / snippet highlighting beyond SQLite FTS5 defaults.
- Multi-user, roles, sharing.
- Rich-text editing in web UI (markdown textarea + preview is enough).
- Auto photo selection beyond "first photo of the day" for calendar cells.
- Incremental digest retry (full regeneration on retry; one recipient → duplicate is benign).
- Mobile-native app.
- Browser push notifications.
- LLM-generated summaries / sentiment analysis (deliberately out — journal is for the user's own reflection).
- Encrypted-at-rest live data dir; only backup-time encryption is supported.
- Restore-from-IMAP across folders other than `Journal/Inbox` and `Journal/Processed`.

### Confirmed assumptions

- **Single user.** Auth boundary is Cloudflare Access; no in-app users/roles.
- **Timezone:** `Europe/London` (configurable).
- **Backup local retention:** 12 monthly archives (configurable).
- **Markdown editor:** plain `<textarea>` with HTMX-driven live preview (no CodeMirror/Monaco).
