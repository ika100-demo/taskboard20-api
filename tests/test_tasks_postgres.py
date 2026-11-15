"""Acceptance tests for spec 002: tasks persist in Postgres; 503 and readiness on an outage."""

from __future__ import annotations

import socket
import time
from collections.abc import Iterator
from typing import Any

import pytest
from conftest import PgServer, free_port
from fastapi.testclient import TestClient

from taskboard20_api.main import app

UNAVAILABLE = {"detail": "Task store unavailable"}


def _new_store(url: str) -> Any:
    from taskboard20_api.tasks.postgres import PostgresTaskStore

    return PostgresTaskStore(url)


def _use(store: Any) -> TestClient:
    from taskboard20_api.tasks.store import get_task_store

    app.dependency_overrides[get_task_store] = lambda: store
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_override() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _locs(response: Any) -> list[Any]:
    return [err["loc"][-1] for err in response.json()["detail"]]


def test_task_survives_restart(database_url: str) -> None:  # AC-002.1
    store = _new_store(database_url)
    created = _use(store).post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-01"})
    assert created.status_code == 201
    store.close()

    restarted = _new_store(database_url)
    try:
        response = _use(restarted).get("/tasks")
    finally:
        restarted.close()
    assert response.status_code == 200
    assert response.json() == [created.json()]
    assert response.json()[0]["title"] == "Buy milk"
    assert response.json()[0]["due_date"] == "2026-12-01"


def test_two_instances_list_in_creation_order(database_url: str) -> None:  # AC-002.2
    first, second = _new_store(database_url), _new_store(database_url)
    try:
        created = []
        for store, payload in (
            (first, {"title": "A", "due_date": "2026-03-01"}),
            (second, {"title": "B"}),
            (first, {"title": "C", "due_date": "2025-01-01"}),
        ):
            response = _use(store).post("/tasks", json=payload)
            assert response.status_code == 201
            created.append(response.json())
        for store in (first, second):
            listed = _use(store).get("/tasks")
            assert listed.status_code == 200
            assert [t["title"] for t in listed.json()] == ["A", "B", "C"]
            assert listed.json() == created
            for item in listed.json():
                assert set(item) == {"id", "title", "due_date"}
            assert listed.json()[1]["due_date"] is None
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "title"),
        ({"title": ""}, "title"),
        ({"title": "   "}, "title"),
        ({"title": "a" * 201}, "title"),
        ({"title": "ok", "due_date": "2026-02-30"}, "due_date"),
        ({"title": "ok", "due_date": "tomorrow"}, "due_date"),
    ],
)
def test_rejected_input_not_stored(  # AC-002.3
    database_url: str, payload: dict[str, Any], field: str
) -> None:
    store = _new_store(database_url)
    try:
        client = _use(store)
        response = client.post("/tasks", json=payload)
        assert response.status_code == 422
        assert _locs(response)[-1] == field
        assert all(loc == field for loc in _locs(response))
        assert client.get("/tasks").json() == []
    finally:
        store.close()
    restarted = _new_store(database_url)
    try:
        after = _use(restarted).get("/tasks")
    finally:
        restarted.close()
    assert after.status_code == 200
    assert after.json() == []


def test_unreachable_at_start_answers_503() -> None:  # AC-002.4
    store = _new_store(f"postgresql://u@127.0.0.1:{free_port()}/db")
    try:
        client = _use(store)
        for call in (
            lambda: client.post("/tasks", json={"title": "x"}),
            lambda: client.get("/tasks"),
        ):
            started = time.monotonic()
            response = call()
            assert time.monotonic() - started < 6
            assert response.status_code == 503
            assert response.json() == UNAVAILABLE
    finally:
        store.close()


def test_non_answering_database_answers_503_within_6s() -> None:  # AC-002.4
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        port = listener.getsockname()[1]
        store = _new_store(f"postgresql://u@127.0.0.1:{port}/db")
        try:
            client = _use(store)
            started = time.monotonic()
            post = client.post("/tasks", json={"title": "x"})
            get = client.get("/tasks")
            elapsed = time.monotonic() - started
        finally:
            store.close()
    assert post.status_code == 503
    assert post.json() == UNAVAILABLE
    assert get.status_code == 503
    assert get.json() == UNAVAILABLE
    assert elapsed < 12  # two requests, each answered within 6 s


def test_outage_answers_503_and_creates_nothing(  # AC-002.4
    pg_server: PgServer, database_url: str
) -> None:
    store = _new_store(database_url)
    try:
        client = _use(store)
        assert client.post("/tasks", json={"title": "before"}).status_code == 201
        pg_server.stop()
        try:
            started = time.monotonic()
            post = client.post("/tasks", json={"title": "during outage"})
            get = client.get("/tasks")
            assert time.monotonic() - started < 12
            assert post.status_code == 503
            assert post.json() == UNAVAILABLE
            assert get.status_code == 503
            assert get.json() == UNAVAILABLE
        finally:
            pg_server.start()
        listed = client.get("/tasks")
        assert listed.status_code == 200
        assert [t["title"] for t in listed.json()] == ["before"]
    finally:
        store.close()


def test_probes_during_outage(pg_server: PgServer, database_url: str) -> None:  # AC-002.5
    store = _new_store(database_url)
    try:
        client = _use(store)
        assert client.get("/ready").status_code == 200
        pg_server.stop()
        try:
            ready = client.get("/ready")
            health = client.get("/health")
        finally:
            pg_server.start()
        assert ready.status_code == 503
        assert ready.json() == {"status": "not ready"}
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
    finally:
        store.close()


def test_probes_when_unreachable_at_start() -> None:  # AC-002.5
    store = _new_store(f"postgresql://u@127.0.0.1:{free_port()}/db")
    try:
        client = _use(store)
        started = time.monotonic()
        ready = client.get("/ready")
        assert time.monotonic() - started < 3
        assert ready.status_code == 503
        assert ready.json() == {"status": "not ready"}
        assert client.get("/health").status_code == 200
    finally:
        store.close()


def test_recovers_without_restart(pg_server: PgServer, database_url: str) -> None:  # AC-002.6
    store = _new_store(database_url)
    try:
        client = _use(store)
        assert client.get("/tasks").status_code == 200
        pg_server.stop()
        try:
            assert client.get("/tasks").status_code == 503
            assert client.get("/ready").status_code == 503
        finally:
            pg_server.start()
        created = client.post("/tasks", json={"title": "after recovery", "due_date": "2026-05-06"})
        assert created.status_code == 201
        listed = client.get("/tasks")
        assert listed.status_code == 200
        assert listed.json() == [created.json()]
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}
    finally:
        store.close()


def test_recovers_when_unreachable_at_start(  # AC-002.6
    pg_server: PgServer, database_url: str
) -> None:
    # A store created while the database is down must serve once it is up, in the same process.
    pg_server.stop()
    try:
        store = _new_store(database_url)
        client = _use(store)
        assert client.get("/tasks").status_code == 503
    finally:
        pg_server.start()
    try:
        assert client.post("/tasks", json={"title": "late"}).status_code == 201
        assert [t["title"] for t in client.get("/tasks").json()] == ["late"]
        assert client.get("/ready").status_code == 200
    finally:
        store.close()
