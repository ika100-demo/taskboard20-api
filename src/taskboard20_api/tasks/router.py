"""HTTP routes for tasks."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from .models import Task, TaskCreate
from .store import StoreUnavailable, TaskRepository, get_task_store

router = APIRouter()
logger = structlog.get_logger()

StoreDep = Annotated[TaskRepository, Depends(get_task_store)]


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Task store unavailable")


@router.post("/tasks", status_code=201, response_model=Task)
def create_task(body: TaskCreate, store: StoreDep) -> Task:
    """Create a task."""
    try:
        task = store.add(body.title, body.due_date)
    except StoreUnavailable as exc:
        raise _unavailable() from exc
    logger.info("task_created", task_id=task.id)
    return task


@router.get("/tasks", response_model=list[Task])
def list_tasks(store: StoreDep) -> list[Task]:
    """List tasks in creation order."""
    try:
        return store.list()
    except StoreUnavailable as exc:
        raise _unavailable() from exc
