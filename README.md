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
3. Set both `recipient` and `reply_to` in `config.toml` to a plus-addressed alias of your Gmail, e.g. `you+driftnote@gmail.com`. Gmail delivers `you+anything@gmail.com` to `you@gmail.com`'s mailbox, and the `Reply-To` header makes replies route back to the alias too — so every Driftnote email (prompts, digests, your replies) is filterable by a single `deliveredto:` rule.
4. Create the labels `Driftnote/Inbox` and `Driftnote/Processed` (Settings → Labels → Create new label).
5. Create a filter (Settings → Filters and Blocked Addresses → Create filter):
   - **Has the words:** `deliveredto:you+driftnote@gmail.com`
   - **Apply label:** `Driftnote/Inbox`, **Skip Inbox**
   - **Do NOT** check "Mark as read". The IMAP poll uses `SEARCH UNSEEN` to find new replies; pre-marking them as read makes the poller skip them and your entries silently won't appear.
6. Send yourself a test prompt (`driftnote send-prompt`) and confirm it lands in `Driftnote/Inbox` with the filter applied — and is `Unread` in Gmail's UI.

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
