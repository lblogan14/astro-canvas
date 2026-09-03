"""``POST /api/workflows/{id}/run``, ``GET /api/runs/{id}``, cancel, and history persistence."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client
from tests.server.test_workflows_api import load, wait_status

EXPENSIVE = {
    "id": "runs-expensive",
    "nodes": {
        "c": {"type": "core.math.constant", "params": {"value": 5.0}},
        "slow": {"type": "test.sleep", "params": {"seconds": 0.05}, "linked": ["x"]},
    },
    "edges": {"e1": {"from": ["c", "out"], "to": ["slow", "x"]}},
}


@pytest.fixture
def api(settings: Settings, test_discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, test_discovery)) as client:
        yield client


def wait_run(client: TestClient, run_id: str, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        body: dict[str, Any] = client.get(f"/api/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"run still running: {body}")
        time.sleep(0.02)


def test_run_expensive_node_and_inspect(api: TestClient) -> None:
    assert api.post("/api/workflows", json=EXPENSIVE).status_code == 201
    status = wait_status(api, "runs-expensive")
    assert status["nodes"]["slow"]["state"] == "dirty" and status["nodes"]["slow"]["stale"]

    accepted = api.post("/api/workflows/runs-expensive/run", json={"targets": ["slow"]})
    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]
    detail = wait_run(api, run_id)
    assert detail["status"] == "done" and detail["targets"] == ["slow"]
    assert detail["finished"] is not None
    nodes = {n["node_id"]: n for n in detail["nodes"]}
    assert nodes["slow"]["status"] == "done" and nodes["slow"]["cache_hit"] is False
    assert "c" not in nodes or nodes["c"]["status"] == "done"
    out = api.get("/api/outputs/slow/out", params={"workflow_id": "runs-expensive"}).json()
    assert out["data"]["value"] == 5.0

    listed = api.get("/api/runs", params={"workflow_id": "runs-expensive"}).json()
    assert [r["id"] for r in listed][0] == run_id and len(listed) >= 2  # auto-run + explicit
    assert api.get("/api/runs/nope").status_code == 404
    assert api.post("/api/runs/nope/cancel").status_code == 404
    assert api.post(f"/api/runs/{run_id}/cancel").json() == {"cancelled": False}
    assert api.post("/api/workflows/nope/run").status_code == 404
    bad = api.post("/api/workflows/runs-expensive/run", json={"targets": ["ghost"]})
    assert bad.status_code == 400


def test_cancel_running_run(api: TestClient) -> None:
    doc = {**EXPENSIVE, "id": "runs-cancel"}
    doc["nodes"] = {
        **EXPENSIVE["nodes"],
        "slow": {**EXPENSIVE["nodes"]["slow"], "params": {"seconds": 30}},
    }  # type: ignore[dict-item]
    api.post("/api/workflows", json=doc)
    wait_status(api, "runs-cancel")
    run_id = api.post("/api/workflows/runs-cancel/run").json()["run_id"]
    deadline = time.monotonic() + 5
    while (
        api.get("/api/workflows/runs-cancel/status").json()["nodes"]["slow"]["state"] != "running"
    ):
        assert time.monotonic() < deadline
        time.sleep(0.02)
    started = time.perf_counter()
    assert api.post(f"/api/runs/{run_id}/cancel").json() == {"cancelled": True}
    detail = wait_run(api, run_id)
    assert time.perf_counter() - started < 2.0
    assert detail["status"] == "cancelled"
    assert {n["node_id"]: n["status"] for n in detail["nodes"]}["slow"] == "cancelled"


def test_run_history_survives_restart(settings: Settings, test_discovery: DiscoveryResult) -> None:
    doc = load("math_chain")
    with authed_client(create_app(settings, test_discovery)) as first:
        first.post("/api/workflows", json=doc)
        run_id = first.post(f"/api/workflows/{doc['id']}/run").json()["run_id"]
        wait_run(first, run_id)
    with authed_client(create_app(settings, test_discovery)) as second:
        detail = second.get(f"/api/runs/{run_id}").json()
        assert detail["status"] == "done" and detail["workflow_id"] == doc["id"]
        assert second.get("/api/runs").json()[0]["id"] in {
            r["id"] for r in second.get("/api/runs", params={"workflow_id": doc["id"]}).json()
        }
