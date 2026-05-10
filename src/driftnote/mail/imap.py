"""Async IMAP poll + move helpers built on aioimaplib.

`poll_unseen` is an async generator yielding `RawMessage` for each UNSEEN
message in `transport.inbox_folder`. After the consumer has persisted the
message it should call `move_to_processed(transport, message_id=...)` to
copy the message to the Processed folder, mark it deleted in Inbox, and
expunge.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as default_policy

import aioimaplib

from driftnote.mail.transport import ImapTransport


@dataclass(frozen=True)
class RawMessage:
    """A fetched UNSEEN message: original bytes + parsed Message-ID."""

    message_id: str
    raw_bytes: bytes


async def _connect(transport: ImapTransport) -> aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL:
    if transport.tls:
        client: aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL = aioimaplib.IMAP4_SSL(
            host=transport.host, port=transport.port
        )
    else:
        client = aioimaplib.IMAP4(host=transport.host, port=transport.port)
    await client.wait_hello_from_server()
    rc = await client.login(transport.username, transport.password)
    # aioimaplib's login() returns Response(result='NO'|'OK', lines=...) rather than
    # raising on auth failure. Without this check the next command (e.g. SELECT) would
    # fail with the misleading "illegal in state NONAUTH" — surface the real error.
    if rc.result != "OK":
        detail = b" ".join(rc.lines).decode("ascii", "replace")
        raise RuntimeError(f"IMAP LOGIN failed for {transport.username}: {detail}")
    return client


async def poll_unseen(transport: ImapTransport) -> AsyncIterator[RawMessage]:
    """Yield each UNSEEN message in transport.inbox_folder. Marks them \\Seen."""
    client = await _connect(transport)
    try:
        await client.select(transport.inbox_folder)
        result, data = await client.search("UNSEEN")
        if result != "OK" or not data or not data[0]:
            return
        ids = data[0].split()
        for ident in ids:
            ident_str = ident.decode("ascii")
            fetch_result, fetch_data = await client.fetch(ident_str, "(RFC822)")
            if fetch_result != "OK":
                continue
            raw = _extract_rfc822(fetch_data)
            if raw is None:
                continue
            parsed = BytesParser(policy=default_policy).parsebytes(raw)
            message_id = (parsed["Message-ID"] or "").strip()
            if not message_id:
                continue
            yield RawMessage(message_id=message_id, raw_bytes=raw)
    finally:
        await client.logout()


async def move_to_processed(transport: ImapTransport, *, message_id: str) -> None:
    """Copy the message to Processed, mark deleted in Inbox, expunge.

    Raises if the message cannot be located by Message-ID.
    """
    client = await _connect(transport)
    try:
        # Ensure the destination folder exists. GreenMail and Gmail both accept
        # CREATE on an existing folder as a no-op (Gmail returns NO; we ignore it).
        with contextlib.suppress(Exception):
            await client.create(transport.processed_folder)
        await client.select(transport.inbox_folder)
        # IMAP requires HEADER values containing brackets/@/spaces to be
        # IMAP-quoted. Wrap the Message-ID in double quotes.
        quoted = f'"{message_id}"'
        result, data = await client.search("HEADER", "Message-ID", quoted)
        if result != "OK" or not data or not data[0]:
            raise RuntimeError(f"message {message_id} not found in {transport.inbox_folder}")
        ident = data[0].split()[0].decode("ascii")
        copy_result, _ = await client.copy(ident, transport.processed_folder)
        if copy_result != "OK":
            raise RuntimeError(f"COPY failed: {copy_result}")
        await client.store(ident, "+FLAGS", r"(\Deleted)")
        await client.expunge()
    finally:
        with contextlib.suppress(Exception):
            await client.logout()


def _extract_rfc822(fetch_data: list[bytes | bytearray]) -> bytes | None:
    """Pull the RFC822 body bytes out of an aioimaplib FETCH response.

    aioimaplib's FETCH returns a list shaped roughly:
        [b'<seqnum> (RFC822 {<size>}', bytearray(<rfc822-bytes>), b')', b'FETCH completed.']

    Anchor on the literal-size prelude (`...{N}`): the body is the immediately
    following bytes chunk. Robust against trailing status lines or multiple
    FETCH responses appearing in the same `data` list.
    """
    for i, chunk in enumerate(fetch_data):
        if not isinstance(chunk, (bytes, bytearray)):
            continue
        stripped = chunk.rstrip()
        if (
            stripped.endswith(b"}")
            and b"{" in stripped
            and i + 1 < len(fetch_data)
            and isinstance(fetch_data[i + 1], (bytes, bytearray))
        ):
            return bytes(fetch_data[i + 1])
    return None
