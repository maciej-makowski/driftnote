"""Integration-test fixtures: a session-scoped GreenMail container."""

from __future__ import annotations

import os
import select
import socket
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

# Auto-detect the podman rootless socket so this works inside a Fedora toolbox
# WITHOUT clobbering DOCKER_HOST on machines that have a real Docker daemon
# (e.g. GitHub Actions ubuntu-latest, where /var/run/docker.sock is the right
# default). Must run before testcontainers is imported.
_xdg = os.environ.get("XDG_RUNTIME_DIR")
if "DOCKER_HOST" not in os.environ and _xdg:
    _podman_sock = Path(_xdg) / "podman" / "podman.sock"
    if _podman_sock.exists():
        os.environ["DOCKER_HOST"] = f"unix://{_podman_sock}"
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from testcontainers.core.container import DockerContainer  # noqa: E402

from tests.conftest import MailServer  # noqa: E402


def _wait_for_smtp_banner(host: str, port: int, timeout: float = 30.0) -> None:
    """Wait until the SMTP server sends a banner (not just accepts TCP connections)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((host, port))
            ready, _, _ = select.select([s], [], [], 2.0)
            if ready:
                data = s.recv(256)
                if data and data.startswith(b"220"):
                    s.close()
                    return
            s.close()
        except OSError:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"SMTP banner not received from {host}:{port} within {timeout}s")


def _wait_for_imap_banner(host: str, port: int, timeout: float = 30.0) -> None:
    """Wait until the IMAP server sends a greeting (not just accepts TCP connections)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((host, port))
            ready, _, _ = select.select([s], [], [], 2.0)
            if ready:
                data = s.recv(256)
                if data and b"IMAP" in data:
                    s.close()
                    return
            s.close()
        except OSError:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"IMAP greeting not received from {host}:{port} within {timeout}s")


@pytest.fixture(scope="session")
def mail_server() -> Iterator[MailServer]:
    user = "you"
    password = "apppwd"
    domain = "example.com"
    address = f"{user}@{domain}"
    # GreenMail 2.1.4 users format: login:password@domain
    container = (
        DockerContainer("greenmail/standalone:2.1.4")
        .with_env(
            "GREENMAIL_OPTS",
            (
                "-Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap "
                f"-Dgreenmail.users={user}:{password}@{domain} "
                "-Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled"
            ),
        )
        .with_exposed_ports(3025, 3143, 8080)
    )
    container.start()
    try:
        host = container.get_container_host_ip()
        smtp_port = int(container.get_exposed_port(3025))
        imap_port = int(container.get_exposed_port(3143))
        _wait_for_smtp_banner(host, smtp_port)
        _wait_for_imap_banner(host, imap_port)
        yield MailServer(
            host=host,
            smtp_port=smtp_port,
            imap_port=imap_port,
            user=user,
            password=password,
            address=address,
        )
    finally:
        container.stop()
