"""``/api/workflows`` CRUD, versions, status snapshot and bearer-token auth."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client

WORKFLOWS = Path(__file__).resolve().parents[1] / "fixtures" / "workflows"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((WORKFLOWS / f"{name}.json").read_text(encoding="utf-8"))
    return data


@pytest.fixture
def api(settings: Settings, test_discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, test_discovery)) as client:
        yield client


def wait_status(client: TestClient, workflow_id: str, timeout: float = 10.0) -> dict[str, Any]:
    """Poll ``/status`` until no node is dirty/queued/running and no run is active."""
    deadline = time.monotonic() + timeout
    while True:
        body: dict[str, Any] = client.get(f"/api/workflows/{workflow_id}/status").json()
        busy = any(
            n["state"] in ("queued", "running") or (n["state"] == "dirty" and not n["stale"])
            for n in body["nodes"].values()
        )
        if not busy and body["current_run"] is None:
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"workflow still busy: {body}")
        time.sleep(0.02)


def test_requires_bearer_token(settings: Settings, test_discovery: DiscoveryResult) -> None:
    app = create_app(settings, test_discovery)
    anonymous = TestClient(app)
    assert anonymous.get("/api/health").status_code == 200
    assert anonymous.get("/api/openapi.json").status_code == 200
    denied = anonymous.get("/api/workflows")
    assert denied.status_code == 401 and denied.headers["www-authenticate"] == "Bearer"
    assert anonymous.get("/api/workflows", params={"token": "test-token"}).status_code == 200
    assert (
        anonymous.get("/api/workflows", headers={"Authorization": "Bearer nope"}).status_code == 401
    )
    assert (settings.config_dir / "token").read_text(encoding="utf-8") == "test-token"


def test_auth_can_be_disabled(tmp_path: Path, test_discovery: DiscoveryResult) -> None:
    settings = Settings(workspace=tmp_path / "ws", auth=False, config_dir=tmp_path / "cfg")
    app = create_app(settings, test_discovery)
    assert app.state.token is None
    assert TestClient(app).get("/api/workflows").json() == []


def test_crud_versions_and_status(api: TestClient) -> None:
    doc = load("math_chain")
    created = api.post("/api/workflows", json=doc)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["doc"]["id"] == doc["id"] and body["node_errors"] == {}
    assert body["doc"]["edges"]["e1"] == {"from": ["c", "out"], "to": ["sq", "x"]}
    assert "modified" in body["doc"]["meta"]

    assert api.post("/api/workflows", json=doc).status_code == 409

    listed = api.get("/api/workflows").json()
    assert [w["id"] for w in listed] == [doc["id"]]
    assert listed[0]["node_count"] == 4 and listed[0]["name"] == "Math chain"

    fetched = api.get(f"/api/workflows/{doc['id']}").json()
    assert fetched["nodes"]["sum"]["params"] == {"expression": "x + y + z", "z": 1.0}

    status = wait_status(api, doc["id"])  # cheap nodes auto-ran after the debounce
    assert {n["state"] for n in status["nodes"].values()} == {"done"}
    assert status["node_errors"] == {}

    versions = api.get(f"/api/workflows/{doc['id']}/versions").json()
    assert len(versions) == 1

    doc["nodes"]["c"]["params"]["value"] = 3.0
    doc["nodes"]["c"]["pos"] = [1, 2]
    updated = api.put(f"/api/workflows/{doc['id']}", json=doc)
    assert updated.status_code == 200
    assert api.put(f"/api/workflows/{doc['id']}", json=doc).status_code == 200  # unchanged
    versions = api.get(f"/api/workflows/{doc['id']}/versions").json()
    assert len(versions) == 2  # only the changed save created a snapshot
    old = api.get(f"/api/workflows/{doc['id']}/versions/{versions[-1]['id']}").json()
    assert old["nodes"]["c"]["params"]["value"] == 2.0
    assert api.get(f"/api/workflows/{doc['id']}/versions/999999").status_code == 404

    status = wait_status(api, doc["id"])
    out = api.get("/api/outputs/sum/out", params={"workflow_id": doc["id"]}).json()
    assert out == {"type_id": "astro.Float", "data": {"value": 13.0}}

    assert api.put("/api/workflows/other-id", json=doc).status_code == 400
    assert api.delete(f"/api/workflows/{doc['id']}").status_code == 204
    assert api.get(f"/api/workflows/{doc['id']}").status_code == 404
    assert api.delete(f"/api/workflows/{doc['id']}").status_code == 404
    assert api.get(f"/api/workflows/{doc['id']}/versions").status_code == 404
    assert api.get(f"/api/workflows/{doc['id']}/status").status_code == 404


def test_layout_errors_report_stale_promoted_and_view_refs(api: TestClient) -> None:
    doc = load("math_chain")
    doc["promoted"] = [{"node": "c", "param": "value", "label": "Value", "group": "Setup"}]
    doc["views"] = [{"id": "total", "node": "sum", "port": "out", "kind": "value-chip"}]
    doc["layouts"] = {
        "app": {"sections": [{"title": "Setup", "items": ["promoted:c.value", "view:total"]}]}
    }
    assert api.post("/api/workflows", json=doc).json()["layout_errors"] == []

    doc["layouts"]["app"]["sections"][0]["items"] = ["promoted:c.gone", "view:missing"]
    errors = api.put(f"/api/workflows/{doc['id']}", json=doc).json()["layout_errors"]
    assert [(e["code"], e["ref"]) for e in errors] == [
        ("unknown_promoted", "c.gone"),
        ("unknown_view", "missing"),
    ]
    # The layout itself round-trips untouched, unknown keys included.
    stored = api.get(f"/api/workflows/{doc['id']}").json()
    assert stored["layouts"]["app"]["sections"][0]["items"] == ["promoted:c.gone", "view:missing"]


def test_invalid_document_reports_node_errors(api: TestClient) -> None:
    doc = load("invalid/missing_input")
    body = api.post("/api/workflows", json=doc).json()
    assert body["node_errors"]["crop"][0]["code"] == "missing_input"
    status = api.get(f"/api/workflows/{doc['id']}/status").json()
    assert status["node_errors"]["crop"][0]["port"] == "spec"
    assert status["nodes"]["crop"]["state"] == "idle" and status["nodes"]["vel"]["state"] == "idle"
    assert api.post("/api/workflows", json={"nodes": "nope"}).status_code == 422


def test_workflows_persist_across_restarts(
    settings: Settings, test_discovery: DiscoveryResult
) -> None:
    doc = load("math_chain")
    with authed_client(create_app(settings, test_discovery)) as first:
        assert first.post("/api/workflows", json=doc).status_code == 201
        wait_status(first, doc["id"])
    with authed_client(create_app(settings, test_discovery)) as second:
        assert [w["id"] for w in second.get("/api/workflows").json()] == [doc["id"]]
        status = wait_status(second, doc["id"])
        # Outputs were cached on disk: the fresh process reports cache hits, not re-execution.
        assert all(n["cache_hit"] for n in status["nodes"].values() if n["state"] == "done")


def test_auto_run_setting_gates_the_debounced_run(api: TestClient) -> None:
    doc = load("math_chain")
    doc["id"] = "wf-settings"
    assert api.post("/api/workflows", json=doc).status_code == 201
    wait_status(api, "wf-settings")
    assert api.get("/api/workflows/wf-settings/settings").json() == {"auto_run": True}
    assert api.get("/api/workflows/wf-settings/status").json()["auto_run"] is True

    off = api.post("/api/workflows/wf-settings/settings", json={"auto_run": False})
    assert off.status_code == 200 and off.json() == {"auto_run": False}
    doc["nodes"]["c"]["params"]["value"] = 5.0
    assert api.put("/api/workflows/wf-settings", json=doc).status_code == 200
    time.sleep(0.15)
    body = api.get("/api/workflows/wf-settings/status").json()
    assert body["auto_run"] is False
    assert body["nodes"]["c"]["state"] == "dirty"

    on = api.post("/api/workflows/wf-settings/settings", json={"auto_run": True})
    assert on.json() == {"auto_run": True}
    body = wait_status(api, "wf-settings")
    assert body["nodes"]["sum"]["state"] == "done"
    assert api.get("/api/workflows/missing/settings").status_code == 404
    assert api.post("/api/workflows/missing/settings", json={"auto_run": True}).status_code == 404
