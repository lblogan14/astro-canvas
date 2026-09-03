"""``/ws``: auth, subscribe snapshot, run/cancel commands, previews and binary output frames."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from astro_canvas.engine.events import FRAME_OUTPUT, decode_frame
from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client
from tests.server.test_workflows_api import load, wait_status

SPECTRUM = {
    "id": "ws-spectrum",
    "nodes": {
        "src": {"type": "test.spec.make", "params": {"n": 20000}},
        "slow": {"type": "test.sleep", "params": {"seconds": 0.05, "x": 1.0}},
    },
}


@pytest.fixture
def api(settings: Settings, test_discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, test_discovery)) as client:
        yield client


def collect_until(ws: WebSocketTestSession, kind: str, limit: int = 200) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event["type"] == kind:
            return events
    raise AssertionError(f"no {kind} event within {limit} messages: {events[-5:]}")


def test_websocket_requires_token_and_same_origin(api: TestClient) -> None:
    anonymous = TestClient(api.app)  # ``api`` sends the bearer header on every handshake
    with pytest.raises(WebSocketDisconnect) as denied, anonymous.websocket_connect("/ws"):
        pass
    assert denied.value.code == 4401
    with (
        pytest.raises(WebSocketDisconnect) as cross,
        anonymous.websocket_connect(
            "/ws?token=test-token",
            headers={"origin": "http://evil.example", "host": "127.0.0.1:8765"},
        ),
    ):
        pass
    assert cross.value.code == 4403
    with api.websocket_connect(
        "/ws?token=test-token&client_id=abc",
        headers={"origin": "http://localhost:5173", "host": "127.0.0.1:8765"},
    ) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["client_id"] == "abc"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        ws.send_json({"type": "nope"})
        assert "unknown message type" in ws.receive_json()["message"]
        ws.send_json(["not", "an", "object"])
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "run"})
        assert "subscribe first" in ws.receive_json()["message"]
        ws.send_json({"type": "subscribe"})
        assert "invalid subscribe" in ws.receive_json()["message"]
        ws.send_json({"type": "subscribe", "workflow_id": "missing"})
        assert "unknown workflow" in ws.receive_json()["message"]


def test_subscribe_run_and_events(api: TestClient) -> None:
    api.post("/api/workflows", json=SPECTRUM)
    wait_status(api, "ws-spectrum")
    with api.websocket_connect("/ws?token=test-token") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "subscribe", "workflow_id": "ws-spectrum"})
        subscribed = ws.receive_json()
        assert subscribed["type"] == "subscribed" and subscribed["current_run"] is None
        validation = ws.receive_json()
        assert validation["type"] == "graph.validation" and validation["node_errors"] == {}
        snapshot = {}
        for _ in range(2):
            event = ws.receive_json()
            assert event["type"] == "node.status"
            snapshot[event["node_id"]] = event
        assert snapshot["src"]["state"] == "done" and snapshot["slow"]["state"] == "dirty"
        assert snapshot["slow"]["stale"] is True and snapshot["slow"]["cost_class"] == "expensive"

        ws.send_json({"type": "run", "targets": ["slow"]})
        accepted = ws.receive_json()
        assert accepted["type"] == "run.accepted"
        events = collect_until(ws, "run.finished")
        types = [e["type"] for e in events]
        assert types[0] == "run.started" and types[-1] == "run.finished"
        assert events[0]["run_id"] == accepted["run_id"] and events[0]["targets"] == ["slow"]
        states = [
            e["state"] for e in events if e["type"] == "node.status" and e["node_id"] == "slow"
        ]
        assert states == ["queued", "running", "done"]
        summary = next(e for e in events if e["type"] == "node.output.summary")
        assert summary["node_id"] == "slow" and summary["summary"] == {
            "type": "astro.Float",
            "data": {"value": 1.0},
        }
        assert events[-1]["status"] == "done" and all(
            e["workflow_id"] == "ws-spectrum" for e in events
        )

        ws.send_json({"type": "run", "targets": ["ghost"]})
        assert "unknown or invalid target" in ws.receive_json()["message"]

        ws.send_json({"type": "cancel"})
        result = ws.receive_json()
        assert result["type"] == "cancel.result" and result["cancelled"] is False


def test_preview_request_redecimates_for_viewport(api: TestClient) -> None:
    api.post("/api/workflows", json=SPECTRUM)
    wait_status(api, "ws-spectrum")
    with api.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "workflow_id": "ws-spectrum"})
        collect_until(ws, "node.status")
        ws.receive_json()  # second status
        ws.send_json(
            {
                "type": "preview.request",
                "node_id": "src",
                "port": "out",
                "viewport": {"lo": 1200, "hi": 1210, "n_out": 64},
            }
        )
        event = ws.receive_json()
        assert event["type"] == "node.output.summary" and event["port"] == "out"
        wave = event["summary"]["wave"]
        assert len(wave) <= 64 and min(wave) >= 1200 and max(wave) <= 1210
        assert event["summary"]["n"] == 20000 and event["tag"] is None
        ws.send_json(
            {
                "type": "preview.request",
                "node_id": "src",
                "port": "out",
                "viewport": {"n_out": 32, "tag": "viewer"},
            }
        )
        tagged = ws.receive_json()
        assert tagged["tag"] == "viewer" and len(tagged["summary"]["wave"]) <= 32
        ws.send_json({"type": "preview.request", "node_id": "src", "port": "nope"})
        assert "no output" in ws.receive_json()["message"]
        ws.send_json(
            {
                "type": "preview.request",
                "node_id": "src",
                "port": "out",
                "viewport": {"lo": "not-a-number", "hi": 5},
            }
        )
        assert "preview failed" in ws.receive_json()["message"]


def test_output_request_streams_binary_frame(api: TestClient) -> None:
    api.post("/api/workflows", json={**SPECTRUM, "id": "ws-binary"})
    wait_status(api, "ws-binary")
    with api.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "workflow_id": "ws-binary"})
        collect_until(ws, "node.status")
        ws.receive_json()
        ws.send_json({"type": "output.request", "node_id": "src", "port": "out"})
        frame = ws.receive_bytes()
        msg_type, header, payload = decode_frame(frame)
        assert msg_type == FRAME_OUTPUT and header["type_id"] == "astro.Spectrum1D"
        arrays = {a["name"]: a for a in header["arrays"]}
        wave = np.frombuffer(payload, dtype="<f8", count=20000, offset=arrays["wave"]["offset"])
        assert wave[0] == 1000.0 and wave[-1] == 2000.0
        ws.send_json({"type": "output.request", "node_id": "src", "port": "zzz"})
        assert "no output" in ws.receive_json()["message"]


def test_events_follow_document_edits(api: TestClient) -> None:
    doc = load("math_chain")
    api.post("/api/workflows", json=doc)
    wait_status(api, doc["id"])
    with api.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "workflow_id": doc["id"]})
        collect_until(ws, "graph.validation")
        for _ in range(4):
            ws.receive_json()
        doc["nodes"]["c"]["params"]["value"] = 10.0
        api.put(f"/api/workflows/{doc['id']}", json=doc)
        events = collect_until(ws, "run.finished")
        dirty = [e for e in events if e["type"] == "node.status" and e["state"] == "dirty"]
        assert {e["node_id"] for e in dirty} == {"c", "sq", "sum"}
        summaries = {
            e["node_id"]: e["summary"]["data"]["value"]
            for e in events
            if e["type"] == "node.output.summary"
        }
        assert summaries["sum"] == 111.0
