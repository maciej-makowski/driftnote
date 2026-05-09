"""Smoke test: /healthz returns 200."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _write_minimal_config(path: Path) -> None:
    path.write_text(
        "[schedule]\n"
        'daily_prompt   = "0 21 * * *"\n'
        'weekly_digest  = "0 8 * * 1"\n'
        'monthly_digest = "0 8 1 * *"\n'
        'yearly_digest  = "0 8 1 1 *"\n'
        'imap_poll      = "*/5 * * * *"\n'
        'timezone       = "Europe/London"\n'
        "[email]\n"
        'imap_folder            = "INBOX"\n'
        'imap_processed_folder  = "INBOX.Processed"\n'
        'recipient              = "you@example.com"\n'
        'sender_name            = "Driftnote"\n'
        'imap_host              = "x"\n'
        "imap_port              = 993\n"
        "imap_tls               = true\n"
        'smtp_host              = "x"\n'
        "smtp_port              = 587\n"
        "smtp_tls               = false\n"
        "smtp_starttls          = true\n"
        "[prompt]\n"
        'subject_template = "[Driftnote] How was {date}?"\n'
        'body_template    = "templates/emails/prompt.txt.j2"\n'
        "[parsing]\n"
        "mood_regex = '^\\\\s*Mood:\\\\s*(\\\\S+)'\n"
        "tag_regex  = '#(\\\\w+)'\n"
        "max_photos = 4\n"
        "max_videos = 2\n"
        "[digests]\n"
        "weekly_enabled  = true\n"
        "monthly_enabled = true\n"
        "yearly_enabled  = true\n"
        "[backup]\n"
        "retain_months = 12\n"
        "encrypt       = false\n"
        'age_key_path  = ""\n'
        "[disk]\n"
        "warn_percent  = 80\n"
        "alert_percent = 95\n"
        'check_cron    = "0 */6 * * *"\n'
        'data_path     = "/tmp"\n'
    )


def test_healthz_returns_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test: the create_app() boots and /healthz returns 200."""
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
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
