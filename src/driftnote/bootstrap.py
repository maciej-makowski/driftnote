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
