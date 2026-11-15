"""Smoke tests for specs 001 and 002: reach the service only through its URL."""

from __future__ import annotations

import json
import urllib.request
import uuid

import pytest


def _create_task(base_url: str, title: str) -> dict[str, object]:
    request = urllib.request.Request(
        base_url + "/tasks",
        data=json.dumps({"title": title, "due_date": "2026-12-01"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 201
        body: dict[str, object] = json.load(response)
    return body


def _list_tasks(base_url: str) -> list[dict[str, object]]:
    with urllib.request.urlopen(base_url + "/tasks", timeout=10) as response:
        assert response.status == 200
        body: list[dict[str, object]] = json.load(response)
    return body


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    body = _create_task(smoke_base_url, title)
    assert isinstance(body["id"], str)
    assert body["title"] == title
    assert body["due_date"] == "2026-12-01"


@pytest.mark.smoke
def test_smoke_ac_001_5_list_tasks(smoke_base_url: str) -> None:  # AC-001.5
    body = _list_tasks(smoke_base_url)
    assert isinstance(body, list)
    for item in body:
        assert set(item) == {"id", "title", "due_date"}


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_002_1_created_task_is_listed(smoke_base_url: str) -> None:  # AC-002.1
    title = f"smoke-{uuid.uuid4()}"
    created = _create_task(smoke_base_url, title)
    matches = [t for t in _list_tasks(smoke_base_url) if t["title"] == title]
    assert len(matches) == 1
    assert matches[0] == created


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_002_2_creation_order(smoke_base_url: str) -> None:  # AC-002.2
    prefix = f"smoke-{uuid.uuid4()}"
    titles = [f"{prefix}-{n}" for n in range(3)]
    for title in titles:
        _create_task(smoke_base_url, title)
    listed = [t["title"] for t in _list_tasks(smoke_base_url) if str(t["title"]).startswith(prefix)]
    assert listed == titles


@pytest.mark.smoke
def test_smoke_ac_002_5_ready(smoke_base_url: str) -> None:  # AC-002.5
    with urllib.request.urlopen(smoke_base_url + "/ready", timeout=10) as response:
        assert response.status == 200
