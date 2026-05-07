"""Integration-test fixtures: a session-scoped GreenMail container."""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Iterator

import pytest

# Configure testcontainers to use the podman socket (required in Fedora toolbox).
# Must be set before testcontainers is imported/initialised.
os.environ.setdefault("DOCKER_HOST", "unix:///run/user/1000/podman/podman.sock")
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from testcontainers.core.container import DockerContainer

from tests.conftest import MailServer


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"port {host}:{port} not reachable within {timeout}s")


@pytest.fixture(scope="session")
def mail_server() -> Iterator[MailServer]:
    user = "you"
    password = "apppwd"
    address = "you@example.com"
    container = (
        DockerContainer("greenmail/standalone:2.1.4")
        .with_env(
            "GREENMAIL_OPTS",
            (
                "-Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap "
                f"-Dgreenmail.users={user}:{password}:{address} "
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
        _wait_for_port(host, smtp_port)
        _wait_for_port(host, imap_port)
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
