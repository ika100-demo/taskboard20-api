"""Smoke tests for spec 001 (AC-001.1, AC-001.5): reach the service only through its URL."""

from __future__ import annotations

import json
import urllib.request
import uuid

import pytest


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    request = urllib.request.Request(
        smoke_base_url + "/tasks",
        data=json.dumps({"title": title, "due_date": "2026-12-01"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 201
        body = json.load(response)
    assert isinstance(body["id"], str)
    assert body["title"] == title
    assert body["due_date"] == "2026-12-01"


@pytest.mark.smoke
def test_smoke_ac_001_5_list_tasks(smoke_base_url: str) -> None:  # AC-001.5
    with urllib.request.urlopen(smoke_base_url + "/tasks", timeout=10) as response:
        assert response.status == 200
        body = json.load(response)
    assert isinstance(body, list)
    for item in body:
        assert set(item) == {"id", "title", "due_date"}
