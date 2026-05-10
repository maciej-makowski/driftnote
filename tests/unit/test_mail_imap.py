"""Unit tests for driftnote.mail.imap connect / login error handling."""

from __future__ import annotations

import asyncio

import aioimaplib
import pytest

from driftnote.mail import imap as imap_mod
from driftnote.mail.transport import ImapTransport


class _FakeClient:
    """Minimal stand-in for aioimaplib.IMAP4 / IMAP4_SSL.

    Returns a configurable Response from `login()` so tests can exercise the
    NO / OK branches without a real IMAP server.
    """

    def __init__(self, *, login_result: str, login_lines: list[bytes]) -> None:
        self._login_result = login_result
        self._login_lines = login_lines
        self.login_called_with: tuple[str, str] | None = None

    async def wait_hello_from_server(self) -> None:
        return None

    async def login(self, user: str, password: str) -> aioimaplib.Response:
        self.login_called_with = (user, password)
        return aioimaplib.Response(self._login_result, self._login_lines)


def _transport() -> ImapTransport:
    return ImapTransport(
        host="imap.example.com",
        port=143,
        tls=False,
        username="user@example.com",
        password="hunter2",
        inbox_folder="INBOX",
        processed_folder="INBOX.Processed",
    )


def test_connect_raises_on_login_no_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A NO response from LOGIN must surface as RuntimeError, not as a downstream
    'illegal in state NONAUTH' error on the next command."""
    fake = _FakeClient(
        login_result="NO",
        login_lines=[b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)"],
    )

    def _factory(*_args: object, **_kwargs: object) -> _FakeClient:
        return fake

    monkeypatch.setattr(aioimaplib, "IMAP4", _factory)
    monkeypatch.setattr(aioimaplib, "IMAP4_SSL", _factory)

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(imap_mod._connect(_transport()))

    msg = str(excinfo.value)
    assert "user@example.com" in msg
    assert "AUTHENTICATIONFAILED" in msg
    assert "Invalid credentials" in msg


def test_connect_returns_client_on_login_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity: a successful LOGIN returns the connected client (no raise)."""
    fake = _FakeClient(login_result="OK", login_lines=[b"LOGIN completed"])

    def _factory(*_args: object, **_kwargs: object) -> _FakeClient:
        return fake

    monkeypatch.setattr(aioimaplib, "IMAP4", _factory)
    monkeypatch.setattr(aioimaplib, "IMAP4_SSL", _factory)

    client = asyncio.run(imap_mod._connect(_transport()))
    assert client is fake
    assert fake.login_called_with == ("user@example.com", "hunter2")
