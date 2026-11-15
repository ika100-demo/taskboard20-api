"""Acceptance tests for spec 001: create and list in-memory tasks."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskboard20_api.main import app


@pytest.fixture()
def tasks_client() -> Iterator[TestClient]:
    """A client against a fresh, empty task store (simulates a freshly started service)."""
    from taskboard20_api.tasks.store import TaskStore, get_task_store

    store = TaskStore()
    app.dependency_overrides[get_task_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_task_store, None)


def _locs(response: Any) -> list[Any]:
    return [err["loc"][-1] for err in response.json()["detail"]]


def test_create_task_returns_201_with_fields() -> None:  # AC-001.1
    from taskboard20_api.tasks.store import TaskStore, get_task_store

    store = TaskStore()
    app.dependency_overrides[get_task_store] = lambda: store
    try:
        client = TestClient(app)
        response = client.post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-01"})
    finally:
        app.dependency_overrides.pop(get_task_store, None)
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], str)
    assert body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] == "2026-12-01"
    assert set(body) == {"id", "title", "due_date"}


def test_create_task_ignores_client_id() -> None:  # AC-001.1
    from taskboard20_api.tasks.store import TaskStore, get_task_store

    store = TaskStore()
    app.dependency_overrides[get_task_store] = lambda: store
    try:
        response = TestClient(app).post("/tasks", json={"title": "x", "id": "mine", "extra": 1})
    finally:
        app.dependency_overrides.pop(get_task_store, None)
    assert response.status_code == 201
    assert response.json()["id"] != "mine"
    assert set(response.json()) == {"id", "title", "due_date"}


def test_create_task_without_due_date(tasks_client: TestClient) -> None:  # AC-001.2
    response = tasks_client.post("/tasks", json={"title": "Call Bob"})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_create_task_with_null_due_date(tasks_client: TestClient) -> None:  # AC-001.2
    response = tasks_client.post("/tasks", json={"title": "Call Bob", "due_date": None})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None},
        {"title": 123},
        {"title": ["a"]},
        {"title": ""},
        {"title": "   "},
        {"title": "a" * 201},
    ],
)
def test_invalid_title_rejected(  # AC-001.3
    tasks_client: TestClient, payload: dict[str, Any]
) -> None:
    response = tasks_client.post("/tasks", json=payload)
    assert response.status_code == 422
    assert "title" in _locs(response)
    assert all(err["loc"][-1] == "title" for err in response.json()["detail"])
    listing = tasks_client.get("/tasks")
    assert listing.status_code == 200
    assert listing.json() == []


def test_title_of_200_chars_accepted(tasks_client: TestClient) -> None:  # AC-001.3
    response = tasks_client.post("/tasks", json={"title": "a" * 200})
    assert response.status_code == 201
    assert response.json()["title"] == "a" * 200


@pytest.mark.parametrize(
    "due", ["tomorrow", "2026-02-30", "2026-12-01T10:00:00Z", "", 20261201, "2026-1-1"]
)
def test_invalid_due_date_rejected(tasks_client: TestClient, due: Any) -> None:  # AC-001.4
    response = tasks_client.post("/tasks", json={"title": "ok", "due_date": due})
    assert response.status_code == 422
    assert _locs(response) == ["due_date"]
    assert tasks_client.get("/tasks").json() == []


def test_list_tasks_shape(tasks_client: TestClient) -> None:  # AC-001.5
    tasks_client.post("/tasks", json={"title": "one", "due_date": "2026-01-02"})
    tasks_client.post("/tasks", json={"title": "two"})
    response = tasks_client.get("/tasks")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    for item in body:
        assert set(item) == {"id", "title", "due_date"}


def test_list_tasks_in_creation_order(tasks_client: TestClient) -> None:  # AC-001.6
    created = [
        tasks_client.post("/tasks", json=payload).json()
        for payload in (
            {"title": "A", "due_date": "2026-03-01"},
            {"title": "B"},
            {"title": "C", "due_date": "2025-01-01"},
        )
    ]
    listed = tasks_client.get("/tasks").json()
    assert listed == created
    assert [t["title"] for t in listed] == ["A", "B", "C"]
    assert len({t["id"] for t in listed}) == 3


def test_fresh_service_lists_empty(tasks_client: TestClient) -> None:  # AC-001.7
    response = tasks_client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_tasks_do_not_survive_restart() -> None:  # AC-001.7
    from taskboard20_api.tasks.store import TaskStore, get_task_store

    first = TaskStore()
    app.dependency_overrides[get_task_store] = lambda: first
    try:
        TestClient(app).post("/tasks", json={"title": "before restart"})
        second = TaskStore()
        app.dependency_overrides[get_task_store] = lambda: second
        response = TestClient(app).get("/tasks")
    finally:
        app.dependency_overrides.pop(get_task_store, None)
    assert response.status_code == 200
    assert response.json() == []
