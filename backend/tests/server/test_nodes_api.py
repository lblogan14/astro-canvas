"""Contract tests for ``/api/nodes``, ``/api/types`` and ``/api/packs``."""

from __future__ import annotations

from fastapi.testclient import TestClient

from astro_canvas.sdk import discover
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client, fixture_entry_point


def test_list_nodes(client: TestClient) -> None:
    body = client.get("/api/nodes").json()
    ids = [n["id"] for n in body]
    assert ids == sorted(ids)
    assert "core.spec.crop" in ids
    crop = next(n for n in body if n["id"] == "core.spec.crop")
    assert crop["pack"] == "core"
    assert crop["inputs"][0] == {
        "name": "spec",
        "type": "astro.Spectrum1D",
        "description": "Input spectrum.",
        "required": True,
        "lazy": False,
    }
    assert [p["name"] for p in crop["params"]] == ["lo", "hi"]
    assert crop["outputs"][0]["type"] == "astro.Spectrum1D"


def test_filter_nodes_by_category(client: TestClient) -> None:
    body = client.get("/api/nodes", params={"category": "Math"}).json()
    assert {n["id"] for n in body} == {"core.math.constant", "core.math.expr"}
    assert client.get("/api/nodes", params={"category": "Nope"}).json() == []


def test_get_node_and_404(client: TestClient) -> None:
    assert client.get("/api/nodes/core.math.expr").json()["params"][0]["widget"] == "code"
    missing = client.get("/api/nodes/core.nope")
    assert missing.status_code == 404
    assert "core.nope" in missing.json()["detail"]


def test_list_types(client: TestClient) -> None:
    body = client.get("/api/types").json()
    ids = [t["id"] for t in body]
    assert ids == sorted(ids) and len(ids) == 25  # 20 core + 5 rbcodes (zfind + multispec)
    spectrum = next(t for t in body if t["id"] == "astro.Spectrum1D")
    assert spectrum["compatible_with"] == ["astro.SpectrumCollection"]
    assert spectrum["color"] == "#5B8DEF"
    assert spectrum["json_schema"]["properties"]["wave"]["x-ndarray"] == {
        "dtype": "float64",
        "ndim": 1,
    }
    assert spectrum["pack"] == "core"


def test_packs_and_system_report_load_errors(settings: Settings) -> None:
    discovery = discover([fixture_entry_point("broken"), fixture_entry_point("good")])
    client = authed_client(create_app(settings, discovery))

    packs = client.get("/api/packs").json()
    assert [p["name"] for p in packs] == ["broken", "good"]
    assert packs[0]["error"]["error"].startswith("ImportError")
    assert packs[1]["error"] is None and packs[1]["node_count"] == 1
    assert client.get("/api/nodes").json()[0]["id"] == "good.text.token"

    system = client.get("/api/system").json()
    assert system["packs"] == [
        {
            "name": "broken",
            "version": "unknown",
            "enabled": True,
            "node_count": 0,
            "security": "standard",
            "error": packs[0]["error"]["error"],
        },
        {
            "name": "good",
            "version": "unknown",
            "enabled": True,
            "node_count": 1,
            "security": "standard",
            "error": None,
        },
    ]


def test_openapi_includes_node_schema(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    assert "/api/nodes/{node_id}" in schema["paths"]
    assert "NodeSpec" in schema["components"]["schemas"]
    assert "PortTypeSpec" in schema["components"]["schemas"]
    assert "PackRecord" in schema["components"]["schemas"]
