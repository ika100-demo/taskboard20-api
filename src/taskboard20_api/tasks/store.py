"""Task stores: the repository protocol, the in-memory store and the default Postgres store."""

from __future__ import annotations

import builtins
import threading
import uuid
from typing import Protocol

from .models import Task
from .postgres import PostgresTaskStore, StoreUnavailable

__all__ = [
    "StoreUnavailable",
    "TaskRepository",
    "TaskStore",
    "close_default_store",
    "get_task_store",
]


class TaskRepository(Protocol):
    """What the routes and the readiness probe need from a task store."""

    def add(self, title: str, due_date: str | None) -> Task: ...

    def list(self) -> builtins.list[Task]: ...

    def ping(self, timeout: float = 1.0) -> bool: ...


class TaskStore:
    """Insertion-ordered, thread-safe task store."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def add(self, title: str, due_date: str | None) -> Task:
        task = Task(id=str(uuid.uuid4()), title=title, due_date=due_date)
        with self._lock:
            self._tasks[task.id] = task
        return task

    def list(self) -> builtins.list[Task]:
        with self._lock:
            return builtins.list(self._tasks.values())

    def ping(self, timeout: float = 1.0) -> bool:
        return True


_store: PostgresTaskStore | None = None
_store_lock = threading.Lock()


def get_task_store() -> TaskRepository:
    """Dependency returning the process-wide Postgres store, created on first use."""
    global _store  # noqa: PLW0603 - lazily created process-wide singleton
    store = _store
    if store is None:
        with _store_lock:
            store = _store
            if store is None:
                store = _store = PostgresTaskStore.from_env()
    return store


def close_default_store() -> None:
    """Close and forget the process-wide store."""
    global _store  # noqa: PLW0603 - lazily created process-wide singleton
    with _store_lock:
        store, _store = _store, None
    if store is not None:
        store.close()
