"""``/api/workflows/{id}/batch``: start, poll, cancel, and the ``batch.*`` events on ``/ws``."""

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
from tests.server.test_workflows_api import wait_status

DOC: dict[str, Any] = {
    "id": "batch-doc",
    "name": "Batch",
    "nodes": {
        "src": {"type": "core.math.constant", "params": {"value": 1.0}},
        "add": {
            "type": "core.math.expr",
            "params": {"expression": "x + y", "y": 0.0},
            "linked": ["x"],
        },
    },
    "edges": {"e1": {"from": ["src", "out"], "to": ["add", "x"]}},
    "promoted": [{"node": "src", "param": "value"}, {"node": "add", "param": "y"}],
    "layouts": {
        "batch": {
            "columns": [{"promoted": "src.value", "column": "x0"}, "add.y"],
            "collect": ["add.out"],
        }
    },
}


@pytest.fixture
def api(settings: Settings, test_discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, test_discovery)) as client:
        yield client


def wait_batch(client: TestClient, batch_id: str, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        body: dict[str, Any] = client.get(f"/api/workflows/batch-doc/batch/{batch_id}").json()
        if body["status"] != "running":
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"batch still running: {body['counts']}")
        time.sleep(0.02)


def test_batch_runs_every_row_and_reports_results(api: TestClient) -> None:
    assert api.post("/api/workflows", json=DOC).status_code == 201
    wait_status(api, "batch-doc")

    rows = [{"x0": float(i), "add.y": 10.0} for i in range(20)]
    rows[7]["add.y"] = "nonsense"
    accepted = api.post("/api/workflows/batch-doc/batch", json={"rows": rows})
    assert accepted.status_code == 202
    batch_id = accepted.json()["batch_id"]
    assert accepted.json()["n_rows"] == 20

    body = wait_batch(api, batch_id)
    assert body["status"] == "error"
    assert body["counts"] == {"done": 19, "error": 1}
    results = body["results"]
    assert results["columns"][:3] == ["x0", "add.y", "value"]
    assert results["rows"][0]["value"] == 10.0
    assert results["rows"][7]["status"] == "error" and results["rows"][7]["error_message"]
    assert results["rows"][19]["value"] == 29.0
    assert body["rows"][7]["error"] is not None


def test_batch_needs_rows_a_collect_and_a_known_workflow(api: TestClient) -> None:
    api.post("/api/workflows", json=DOC)
    wait_status(api, "batch-doc")
    assert api.post("/api/workflows/nope/batch", json={"rows": [{}]}).status_code == 404
    assert api.post("/api/workflows/batch-doc/batch", json={"rows": []}).status_code == 400
    empty = api.post(
        "/api/workflows/batch-doc/batch",
        json={"rows": [{"x0": 1.0}], "spec": {"bindings": [], "collect": []}},
    )
    assert empty.status_code == 400
    assert api.get("/api/workflows/batch-doc/batch/ghost").status_code == 404


def test_cancelling_a_batch_stops_the_remaining_rows(
    settings: Settings, test_discovery: DiscoveryResult
) -> None:
    doc = {
        "id": "batch-doc",
        "nodes": {"slow": {"type": "test.sleep", "params": {"seconds": 30.0, "x": 0.0}}},
        "edges": {},
        "layouts": {"batch": {"columns": ["slow.x"], "collect": ["slow.out"]}},
    }
    with authed_client(create_app(settings, test_discovery)) as api:
        api.post("/api/workflows", json=doc)
        wait_status(api, "batch-doc")
        started = api.post(
            "/api/workflows/batch-doc/batch",
            json={
                "rows": [{"slow.x": float(i)} for i in range(6)],
                "spec": {
                    "bindings": [{"node": "slow", "param": "x", "column": "slow.x"}],
                    "collect": [{"node": "slow", "port": "out"}],
                    "max_workers": 2,
                },
            },
        )
        batch_id = started.json()["batch_id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            body = api.get(f"/api/workflows/batch-doc/batch/{batch_id}").json()
            if sum(r["state"] == "running" for r in body["rows"]) >= 2:
                break
            time.sleep(0.02)
        assert api.post(f"/api/workflows/batch-doc/batch/{batch_id}/cancel").status_code == 200
        body = wait_batch(api, batch_id)
        assert body["status"] == "cancelled"
        assert body["counts"].get("done", 0) == 0


def test_ws_batch_commands_stream_row_events(
    settings: Settings, test_discovery: DiscoveryResult
) -> None:
    with authed_client(create_app(settings, test_discovery)) as api:
        api.post("/api/workflows", json=DOC)
        wait_status(api, "batch-doc")
        with api.websocket_connect("/ws?client_id=batch") as ws:
            assert ws.receive_json()["type"] == "hello"
            ws.send_json({"type": "subscribe", "workflow_id": "batch-doc"})
            seen: list[dict[str, Any]] = []
            ws.send_json({"type": "batch.run", "rows": [{"x0": 2.0, "add.y": 3.0}]})
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                message = ws.receive_json()
                seen.append(message)
                if message["type"] == "batch.finished":
                    break
            kinds = [m["type"] for m in seen]
            assert "batch.accepted" in kinds and "batch.started" in kinds
            rows = [m for m in seen if m["type"] == "batch.row"]
            assert [r["state"] for r in rows] == ["running", "done"]
            assert rows[-1]["outputs"]["value"] == 5.0
            assert seen[-1]["status"] == "done" and seen[-1]["done"] == 1


def test_ws_batch_rejects_an_empty_batch_and_cancels_by_id(
    settings: Settings, test_discovery: DiscoveryResult
) -> None:
    with authed_client(create_app(settings, test_discovery)) as api:
        api.post("/api/workflows", json=DOC)
        wait_status(api, "batch-doc")
        with api.websocket_connect("/ws?client_id=batch2") as ws:
            ws.receive_json()
            ws.send_json({"type": "batch.run", "rows": [{"x0": 1.0}]})
            assert "subscribe first" in ws.receive_json()["message"]
            ws.send_json({"type": "subscribe", "workflow_id": "batch-doc"})
            ws.send_json({"type": "batch.run", "rows": []})
            while True:
                message = ws.receive_json()
                if message["type"] == "error":
                    assert "needs rows" in message["message"]
                    break
            ws.send_json({"type": "batch.cancel", "batch_id": "ghost"})
            while True:
                message = ws.receive_json()
                if message["type"] == "batch.cancelled":
                    assert message["cancelled"] is False
                    break
