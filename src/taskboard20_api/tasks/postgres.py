"""Postgres-backed task store (psycopg 3, sync, own small connection pool)."""

from __future__ import annotations

import builtins
import contextlib
import datetime
import os
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import psycopg
import structlog

from .models import Task

log = structlog.get_logger()

_SCHEMA_LOCK_KEY = 2002001
_SEMAPHORE_WAIT = 2.0

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    seq      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       UUID NOT NULL UNIQUE,
    title    TEXT NOT NULL,
    due_date DATE NULL
)
"""


class StoreUnavailable(Exception):  # noqa: N818 - name fixed by the design contract
    """The database cannot be reached, timed out or the connection was lost."""


class PostgresTaskStore:
    """Task store on Postgres; never connects at construction."""

    def __init__(self, conninfo: str, *, max_idle: int = 5, max_open: int = 10) -> None:
        self._conninfo = conninfo
        self._max_idle = max_idle
        self._sem = threading.BoundedSemaphore(max_open)
        self._idle: builtins.list[psycopg.Connection] = []
        self._idle_lock = threading.Lock()
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pg-ping")

    @classmethod
    def from_env(cls) -> PostgresTaskStore:
        return cls(os.environ.get("DATABASE_URL", ""))

    # -- connections -------------------------------------------------------

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            self._conninfo,
            connect_timeout=2,
            options="-c statement_timeout=3000",
            keepalives=1,
            keepalives_idle=5,
            keepalives_interval=1,
            keepalives_count=2,
            tcp_user_timeout=3000,
        )

    def _drain_idle(self) -> None:
        with self._idle_lock:
            stale, self._idle = self._idle, []
        for conn in stale:
            _close_quietly(conn)

    def _acquire(self) -> psycopg.Connection:
        while True:
            with self._idle_lock:
                conn = self._idle.pop() if self._idle else None
            if conn is None:
                return self._connect()
            try:
                conn.execute("SELECT 1")
                conn.rollback()
                return conn
            except psycopg.Error:
                _close_quietly(conn)

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        if not self._sem.acquire(timeout=_SEMAPHORE_WAIT):
            log.warning("task_store_unavailable", error_type="PoolTimeout")
            raise StoreUnavailable("connection limit reached")
        conn: psycopg.Connection | None = None
        try:
            conn = self._acquire()
            yield conn
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            if conn is not None:
                _close_quietly(conn)
                conn = None
            self._drain_idle()
            log.warning("task_store_unavailable", error_type=type(exc).__name__)
            raise StoreUnavailable("task store unavailable") from exc
        except BaseException:
            if conn is not None:
                _close_quietly(conn)
                conn = None
            raise
        else:
            self._release(conn)
        finally:
            self._sem.release()

    def _release(self, conn: psycopg.Connection) -> None:
        try:
            conn.rollback()
        except psycopg.Error:
            _close_quietly(conn)
            return
        with self._idle_lock:
            if len(self._idle) < self._max_idle:
                self._idle.append(conn)
                return
        _close_quietly(conn)

    def _ensure_schema(self, conn: psycopg.Connection) -> None:
        with self._schema_lock:
            if self._schema_ready:
                return
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
            conn.execute(_CREATE_TABLE)
            conn.commit()
            self._schema_ready = True

    # -- operations --------------------------------------------------------

    def add(self, title: str, due_date: str | None) -> Task:
        task_id = uuid.uuid4()
        due = datetime.date.fromisoformat(due_date) if due_date is not None else None
        with self._connection() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)",
                (task_id, title, due),
            )
            conn.commit()
        return Task(id=str(task_id), title=title, due_date=due_date)

    def list(self) -> builtins.list[Task]:
        with self._connection() as conn:
            self._ensure_schema(conn)
            rows = conn.execute("SELECT id, title, due_date FROM tasks ORDER BY seq").fetchall()
            conn.rollback()
        return [
            Task(id=str(r[0]), title=r[1], due_date=r[2].isoformat() if r[2] else None)
            for r in rows
        ]

    def _select_one(self) -> None:
        with self._connection() as conn:
            conn.execute("SELECT 1")

    def ping(self, timeout: float = 1.0) -> bool:
        try:
            self._executor.submit(self._select_one).result(timeout)
        except Exception:
            return False
        return True

    def close(self) -> None:
        self._drain_idle()
        self._executor.shutdown(wait=False)


def _close_quietly(conn: psycopg.Connection) -> None:
    with contextlib.suppress(Exception):  # best effort on a broken connection
        conn.close()
