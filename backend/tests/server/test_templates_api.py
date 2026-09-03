"""``/api/templates``: listing, reading and instantiating pack-shipped workflow templates."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astro_canvas.sdk import DiscoveryResult, NodeRegistry
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client
from tests.server.test_workflows_api import wait_status

TEMPLATE = {
    "format": "astro-canvas/workflow",
    "version": 1,
    "id": "template-math",
    "name": "Math template",
    "description": "Two constants added.",
    "nodes": {
        "a": {"type": "core.math.constant", "params": {"value": 2.0}},
        "b": {"type": "core.math.expr", "params": {"expression": "x + 1"}, "linked": ["x"]},
    },
    "edges": {"e": {"from": ["a", "out"], "to": ["b", "x"]}},
    "meta": {"created": "2020-01-01T00:00:00", "tags": ["sample"]},
}


@pytest.fixture
def templates_dir(tmp_path: Path, registry: NodeRegistry) -> Iterator[Path]:
    folder = tmp_path / "templates"
    folder.mkdir()
    (folder / "math.acw").write_text(json.dumps(TEMPLATE), encoding="utf-8")
    (folder / "math.md").write_text("# Math\nAdds one.", encoding="utf-8")
    (folder / "broken.acw").write_text("{not json", encoding="utf-8")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")
    registry.add_templates(folder, pack="testpack")
    try:
        yield folder
    finally:
        registry.template_dirs.pop("testpack", None)


@pytest.fixture
def api(
    settings: Settings, test_discovery: DiscoveryResult, templates_dir: Path
) -> Iterator[TestClient]:
    with authed_client(create_app(settings, test_discovery)) as client:
        yield client


def test_lists_templates_with_readme_and_skips_broken_files(api: TestClient) -> None:
    body = api.get("/api/templates").json()
    ours = [t for t in body if t["pack"] == "testpack"]
    assert [t["id"] for t in ours] == ["testpack.math"]
    info = ours[0]
    assert info["name"] == "Math template" and info["description"] == "Two constants added."
    assert info["node_count"] == 2 and info["file"] == "math.acw"
    assert info["readme"] == "# Math\nAdds one."


def test_reads_the_template_document(api: TestClient) -> None:
    doc = api.get("/api/templates/testpack.math").json()
    assert doc["id"] == "template-math" and set(doc["nodes"]) == {"a", "b"}
    assert api.get("/api/templates/nope.missing").status_code == 404


def test_instantiate_creates_a_fresh_workflow_that_runs(api: TestClient) -> None:
    response = api.post("/api/templates/testpack.math/instantiate", json={"name": "My measurement"})
    assert response.status_code == 201, response.text
    saved = response.json()
    doc = saved["doc"]
    assert doc["id"] != "template-math" and doc["name"] == "My measurement"
    assert doc["meta"]["template"] == "testpack.math" and doc["meta"]["tags"] == ["sample"]
    assert doc["meta"].get("created") != "2020-01-01T00:00:00"
    assert saved["node_errors"] == {}
    status = wait_status(api, doc["id"])
    assert status["nodes"]["b"]["state"] == "done"
    listed = api.get("/api/workflows").json()
    assert any(w["id"] == doc["id"] for w in listed)
    second = api.post("/api/templates/testpack.math/instantiate").json()["doc"]
    assert second["id"] != doc["id"] and second["name"] == "Math template"
    assert api.post("/api/templates/nope/instantiate").status_code == 404
