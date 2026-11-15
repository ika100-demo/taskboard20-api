"""Shared pytest fixtures, including the throwaway Postgres harness (spec 002).

The harness drives the server only through ``initdb`` / ``pg_ctl`` / ``psql`` (all shipped by the
devbox package ``postgresql@16``), so collecting or running tests that do not need a database never
needs psycopg. Set ``TEST_DATABASE_URL`` to use an existing server instead of a throwaway one.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess  # nosec B404 - test harness runs the Postgres binaries
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from taskboard20_api.main import app


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)


def free_port() -> int:
    """A TCP port on 127.0.0.1 that has no listener right now."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


class PgServer:
    """A Postgres server for the tests: throwaway (own data dir) or external (TEST_DATABASE_URL)."""

    def __init__(self, admin_url: str, datadir: Path | None, port: int | None) -> None:
        self.admin_url = admin_url
        self.datadir = datadir
        self.port = port
        self.controllable = datadir is not None
        self._tmp: Path | None = None

    def url_for(self, dbname: str) -> str:
        parts = urlsplit(self.admin_url)
        return urlunsplit(parts._replace(path="/" + dbname))

    def sql(self, statement: str) -> None:
        command = ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", self.admin_url, "-c", statement]
        result = _run(command)
        if result.returncode != 0:
            raise RuntimeError(f"psql failed: {statement!r}: {result.stderr.strip()}")

    def _pg_ctl(self, *args: str) -> None:
        assert self.datadir is not None
        result = _run(["pg_ctl", "-D", str(self.datadir), "-w", "-t", "60", *args])
        if result.returncode != 0:
            raise RuntimeError(f"pg_ctl {args} failed: {result.stdout} {result.stderr}")

    def start(self) -> None:
        assert self.datadir is not None
        sockdir = self.datadir.parent / "sock"
        sockdir.mkdir(exist_ok=True)
        options = f"-p {self.port} -k {sockdir} -c listen_addresses=127.0.0.1"
        self._pg_ctl("-l", str(self.datadir.parent / "pg.log"), "-o", options, "start")

    def stop(self) -> None:
        """Stop the server (fast shutdown); only for a throwaway server."""
        if not self.controllable:
            pytest.skip("outage tests need the throwaway server (unset TEST_DATABASE_URL)")
        self._pg_ctl("-m", "fast", "stop")

    def is_running(self) -> bool:
        assert self.datadir is not None
        return _run(["pg_ctl", "-D", str(self.datadir), "status"]).returncode == 0


@pytest.fixture(scope="session")
def pg_server() -> Iterator[PgServer]:
    """A session-wide Postgres; also sets DATABASE_URL so the default store is ready."""
    external = os.environ.get("TEST_DATABASE_URL")
    if shutil.which("psql") is None:
        pytest.fail("psql not on PATH: run the tests through `devbox run test` (postgresql@16)")
    if external:
        server = PgServer(external, None, None)
        os.environ["DATABASE_URL"] = external
        yield server
        return
    for tool in ("initdb", "pg_ctl"):
        if shutil.which(tool) is None:
            pytest.fail(
                f"{tool} not on PATH and TEST_DATABASE_URL is unset: add devbox package "
                "postgresql@16 and run the tests through `devbox run test`"
            )
    tmp = Path(tempfile.mkdtemp(prefix="taskboard-pg-"))
    datadir = tmp / "data"
    init = _run(["initdb", "-D", str(datadir), "-A", "trust", "-U", "postgres", "-E", "UTF8"])
    if init.returncode != 0:
        pytest.fail(f"initdb failed: {init.stderr}")
    port = free_port()
    server = PgServer(f"postgresql://postgres@127.0.0.1:{port}/postgres", datadir, port)
    server.start()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = server.admin_url
    try:
        yield server
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        if server.is_running():
            server._pg_ctl("-m", "immediate", "stop")
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def database_url(pg_server: PgServer) -> Iterator[str]:
    """URL of a fresh, empty database, dropped after the test."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    pg_server.sql(f'CREATE DATABASE "{name}"')
    try:
        yield pg_server.url_for(name)
    finally:
        if pg_server.controllable and not pg_server.is_running():
            pg_server.start()
        pg_server.sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
