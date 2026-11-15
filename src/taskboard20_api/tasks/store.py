"""Process-local in-memory task store."""

from __future__ import annotations

import builtins
import threading
import uuid

from .models import Task


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


_store = TaskStore()


def get_task_store() -> TaskStore:
    """Dependency returning the process-wide store."""
    return _store
