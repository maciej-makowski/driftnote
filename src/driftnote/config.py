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
        secrets = Secrets()
    except ValidationError as exc:
        raise ConfigError(f"missing/invalid secrets in env: {exc}") from exc

    overrides = _EmailEnvOverrides()
    email_raw = dict(raw.get("email", {}))
    for field in (
        "imap_host",
        "imap_port",
        "imap_tls",
        "smtp_host",
        "smtp_port",
        "smtp_tls",
        "smtp_starttls",
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
