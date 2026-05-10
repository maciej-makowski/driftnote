"""Tests for the DRIFTNOTE_HOME / .env bootstrap helper."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from driftnote.bootstrap import driftnote_home, load_env


def test_driftnote_home_defaults_to_user_home_dotfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DRIFTNOTE_HOME", raising=False)
    assert driftnote_home() == Path.home() / ".driftnote"


def test_driftnote_home_respects_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    assert driftnote_home() == tmp_path


def test_load_env_loads_dotenv_from_driftnote_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("DRIFTNOTE_TESTKEY=from_dotenv\n")
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_TESTKEY", raising=False)
    monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)
    monkeypatch.delenv("DRIFTNOTE_DATA_ROOT", raising=False)

    load_env()

    assert os.environ["DRIFTNOTE_TESTKEY"] == "from_dotenv"


def test_load_env_does_not_override_existing_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("DRIFTNOTE_TESTKEY=from_dotenv\n")
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTNOTE_TESTKEY", "from_shell")

    load_env()

    assert os.environ["DRIFTNOTE_TESTKEY"] == "from_shell"


def test_load_env_defaults_config_path_from_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)

    load_env()

    assert os.environ["DRIFTNOTE_CONFIG"] == str(tmp_path / "config.toml")


def test_load_env_defaults_data_root_from_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_DATA_ROOT", raising=False)

    load_env()

    assert os.environ["DRIFTNOTE_DATA_ROOT"] == str(tmp_path / "data")


def test_load_env_does_not_override_explicit_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.setenv("DRIFTNOTE_CONFIG", "/somewhere/else.toml")

    load_env()

    assert os.environ["DRIFTNOTE_CONFIG"] == "/somewhere/else.toml"


def test_load_env_no_dotenv_file_is_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """tmp_path has no .env — should not raise; defaults still applied."""
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)

    load_env()  # must not raise

    assert os.environ["DRIFTNOTE_CONFIG"] == str(tmp_path / "config.toml")


def test_load_env_unreadable_dotenv_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.env` file we cannot read is silently skipped; defaults still apply.

    `python-dotenv.load_dotenv()` returns False for missing/directory paths
    but raises `PermissionError` for a regular file with mode 0o000. Our
    contract is to swallow that. Test by writing a real .env, chmod'ing it
    to 0o000, and checking load_env() returns normally.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root bypasses POSIX file mode")
    env_file = tmp_path / ".env"
    env_file.write_text("DRIFTNOTE_TESTKEY_UNREADABLE=should_not_load\n")
    env_file.chmod(0o000)
    monkeypatch.setenv("DRIFTNOTE_HOME", str(tmp_path))
    monkeypatch.delenv("DRIFTNOTE_TESTKEY_UNREADABLE", raising=False)
    monkeypatch.delenv("DRIFTNOTE_CONFIG", raising=False)
    try:
        load_env()  # must not raise
    finally:
        env_file.chmod(0o644)  # restore so pytest can clean up tmp_path

    assert "DRIFTNOTE_TESTKEY_UNREADABLE" not in os.environ
    assert os.environ["DRIFTNOTE_CONFIG"] == str(tmp_path / "config.toml")
