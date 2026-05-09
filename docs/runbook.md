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
