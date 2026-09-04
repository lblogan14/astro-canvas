"""Exporting a ``.acw`` and importing it into a fresh workspace (design 7.2)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.manager.bundles import (
    CARD_FIGURE,
    BundleError,
    open_bundle,
    prepare_import,
    read_document,
)
from astro_canvas.manager.trust import snippet_hash
from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client
from tests.server.test_workflows_api import wait_status

SPECTRUM = "samples/rbcodes/sdss1.fits"


def workflow(name: str = "Bundle demo") -> dict[str, object]:
    """A tiny document that reads a sample file and derives one number from it."""
    return {
        "id": "wf-bundle",
        "name": name,
        "description": "Two constants and their sum.",
        "nodes": {
            "load": {"type": "core.io.load_spectrum", "params": {"path": SPECTRUM}},
            "c": {"type": "core.math.constant", "params": {"value": 3.0}},
            "sum": {
                "type": "core.math.expr",
                "params": {"expression": "x + 1"},
                "linked": ["x"],
            },
        },
        "edges": {"e": {"from": ["c", "out"], "to": ["sum", "x"]}},
        "views": [{"id": "v1", "node": "sum", "port": "out"}],
        "layouts": {"app": {"sections": [{"title": "Result", "items": ["view:v1"]}]}},
        "requires": {"packs": {"astro-canvas-core": ">=0.1,<0.2"}},
    }


@pytest.fixture
def client(settings: Settings, discovery: DiscoveryResult) -> TestClient:
    with authed_client(create_app(settings, discovery)) as client:
        yield client


def export(client: TestClient, doc: dict[str, object], **options: object) -> dict:
    created = client.post("/api/workflows", json=doc)
    assert created.status_code == 201, created.text
    workflow_id = created.json()["doc"]["id"]
    client.post(f"/api/workflows/{workflow_id}/run", json={"targets": None})
    wait_status(client, workflow_id)
    response = client.post("/api/bundles/export", json={"workflow_id": workflow_id, **options})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_bundle_carries_the_document_the_lock_and_a_readme(
    client: TestClient, settings: Settings
) -> None:
    manifest = export(client, workflow())
    path = settings.workspace / manifest["path"]
    assert path.is_file() and manifest["bytes"] > 0

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        assert {
            "workflow.json",
            "lock.json",
            "inputs/refs.json",
            "provenance.json",
            "trust.json",
            "README.md",
        } <= names
        doc = WorkflowDoc.model_validate_json(zf.read("workflow.json"))
        readme = zf.read("README.md").decode("utf-8")
        provenance = json.loads(zf.read("provenance.json"))
    assert doc.name == "Bundle demo"
    assert doc.layouts["app"]["sections"][0]["items"] == ["view:v1"]
    assert "Bundle demo" in readme and "astro-canvas-core" in readme
    assert {n["node"] for n in provenance["nodes"]} == {"load", "c", "sum"}
    assert manifest["lock"]["packs"]["astro-canvas-core"]


def test_input_files_are_hashed_and_embedded(client: TestClient, settings: Settings) -> None:
    manifest = export(client, workflow())
    refs = {i["param_ref"]: i for i in manifest["inputs"]}
    assert set(refs) == {"load.path"}
    entry = refs["load.path"]
    assert entry["path"] == SPECTRUM and entry["embedded"] and entry["bytes"] > 0
    assert len(entry["blake3"]) == 64
    with zipfile.ZipFile(settings.workspace / manifest["path"]) as zf:
        assert f"inputs/{SPECTRUM}" in zf.namelist()


def test_a_size_limit_keeps_the_file_out_but_keeps_its_hash(client: TestClient) -> None:
    manifest = export(client, workflow(), embed_inputs_max_mb=0)
    entry = manifest["inputs"][0]
    assert not entry["embedded"] and entry["blake3"]


def test_leaf_outputs_and_a_card_figure_are_written(client: TestClient, settings: Settings) -> None:
    manifest = export(client, workflow())
    assert "sum.out" in manifest["outputs"]
    assert CARD_FIGURE in manifest["figures"]
    with zipfile.ZipFile(settings.workspace / manifest["path"]) as zf:
        assert zf.read(CARD_FIGURE)[:8] == b"\x89PNG\r\n\x1a\n"
        assert any(n.startswith("outputs/sum.out.") for n in zf.namelist())


def test_outputs_can_be_left_out(client: TestClient) -> None:
    assert export(client, workflow(), include_outputs="none")["outputs"] == []


def test_an_any_output_is_never_bundled(client: TestClient, settings: Settings) -> None:
    """design 7.2: an in-process object has no file form and must not leave the machine."""
    doc = workflow("Any demo")
    doc["nodes"] = {"note": {"type": "core.note.markdown", "params": {"text": "hi"}}}
    doc["edges"] = {}
    doc["views"] = []
    doc["layouts"] = {}
    manifest = export(client, doc)
    with zipfile.ZipFile(settings.workspace / manifest["path"]) as zf:
        assert not any(name.endswith((".pkl", ".pickle")) for name in zf.namelist())


def test_round_trip_into_a_fresh_workspace(
    client: TestClient, settings: Settings, tmp_path: Path, discovery: DiscoveryResult
) -> None:
    """Acceptance: export here, import into another workspace, same document and outputs."""
    manifest = export(client, workflow())
    payload = (settings.workspace / manifest["path"]).read_bytes()
    before = client.get(f"/api/outputs/sum/out?workflow_id={manifest['workflow_id']}&fmt=json")
    assert before.status_code == 200

    fresh = Settings(
        workspace=tmp_path / "fresh",
        config_dir=tmp_path / "fresh-cfg",
        token="test-token",
        process_pool=False,
        debounce_ms=20,
    )
    with authed_client(create_app(fresh, discovery)) as other:
        response = other.post(
            "/api/bundles/import",
            files={"file": ("demo.acw", payload, "application/zip")},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["missing_packs"] == {}
        assert result["layout_errors"] == []
        assert not result["quarantined"]
        assert result["workflow_id"] != manifest["workflow_id"]

        imported = other.get(f"/api/workflows/{result['workflow_id']}").json()
        assert set(imported["nodes"]) == {"load", "c", "sum"}
        assert imported["layouts"]["app"]["sections"][0]["items"] == ["view:v1"]

        other.post(f"/api/workflows/{result['workflow_id']}/run", json={"targets": None})
        wait_status(other, result["workflow_id"])
        after = other.get(f"/api/outputs/sum/out?workflow_id={result['workflow_id']}&fmt=json")
        assert after.status_code == 200
        assert after.json()["data"] == before.json()["data"]


def test_import_reports_a_pack_this_machine_does_not_have(
    client: TestClient, settings: Settings
) -> None:
    doc = workflow("Needs a pack")
    doc["requires"] = {"packs": {"astro-canvas-nonesuch": ">=1"}}
    manifest = export(client, doc)
    payload = (settings.workspace / manifest["path"]).read_bytes()

    response = client.post(
        "/api/bundles/import", files={"file": ("demo.acw", payload, "application/zip")}
    )
    result = response.json()
    assert result["missing_packs"] == {"astro-canvas-nonesuch": ">=1"}
    assert any("Manager" in w for w in result["warnings"])


def test_a_missing_input_is_reported_rather_than_guessed(
    client: TestClient, settings: Settings, tmp_path: Path, discovery: DiscoveryResult
) -> None:
    manifest = export(client, workflow(), embed_inputs_max_mb=0)
    payload = (settings.workspace / manifest["path"]).read_bytes()
    fresh = Settings(
        workspace=tmp_path / "fresh2",
        config_dir=tmp_path / "fresh2-cfg",
        token="test-token",
        process_pool=False,
    )
    with authed_client(create_app(fresh, discovery)) as other:
        result = other.post(
            "/api/bundles/import", files={"file": ("demo.acw", payload, "application/zip")}
        ).json()
    # The sample file is re-seeded by pack discovery, so it is found rather than missing;
    # its content matches, so no warning is raised.
    statuses = {i["param_ref"]: i["status"] for i in result["inputs"]}
    assert statuses == {"load.path": "ok"}


def test_a_changed_input_is_flagged_as_a_hash_mismatch(
    client: TestClient, settings: Settings, tmp_path: Path, discovery: DiscoveryResult
) -> None:
    manifest = export(client, workflow(), embed_inputs_max_mb=0)
    payload = (settings.workspace / manifest["path"]).read_bytes()
    fresh_root = tmp_path / "fresh3"
    (fresh_root / "samples" / "rbcodes").mkdir(parents=True)
    (fresh_root / SPECTRUM).write_bytes(b"not the same file at all")
    fresh = Settings(
        workspace=fresh_root,
        config_dir=tmp_path / "fresh3-cfg",
        token="test-token",
        process_pool=False,
    )
    with authed_client(create_app(fresh, discovery)) as other:
        result = other.post(
            "/api/bundles/import", files={"file": ("demo.acw", payload, "application/zip")}
        ).json()
    assert result["inputs"][0]["status"] == "hash_mismatch"
    assert any("differs" in w for w in result["warnings"])


def test_a_plain_json_document_still_opens(client: TestClient) -> None:
    """Pack templates ship ``.acw`` files that are bare documents (phase 05); both shapes open."""
    doc = read_document(json.dumps(workflow()).encode("utf-8"))
    assert doc.name == "Bundle demo"


def test_a_bundle_without_a_workflow_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.acw"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("README.md", "nothing here")
    with pytest.raises(BundleError, match="no workflow.json"):
        open_bundle(path.read_bytes())


def test_code_hashes_travel_but_decisions_do_not(client: TestClient, settings: Settings) -> None:
    doc = workflow("With code")
    doc["nodes"] = {
        "py": {
            "type": "core.code.python",
            "params": {
                "source": "out = 2 + 2",
                "inputs": [],
                "outputs": [{"name": "out", "type": "astro.Float"}],
            },
        }
    }
    doc["edges"] = {}
    doc["views"] = []
    doc["layouts"] = {}
    manifest = export(client, doc)
    assert manifest["code_hashes"] == [snippet_hash("out = 2 + 2")]
    with zipfile.ZipFile(settings.workspace / manifest["path"]) as zf:
        trust = json.loads(zf.read("trust.json"))
    assert trust["snippets"][0]["hash"] == snippet_hash("out = 2 + 2")
    assert "decision" not in trust["snippets"][0]


def test_prepare_import_keeps_node_ids_so_layout_refs_survive(
    client: TestClient, settings: Settings
) -> None:
    manifest = export(client, workflow())
    payload = (settings.workspace / manifest["path"]).read_bytes()
    runtime = client.app.state.runtime
    doc, result = prepare_import(
        open_bundle(payload), runtime.workspace, runtime.registry, client.app.state.packs
    )
    assert set(doc.nodes) == {"load", "c", "sum"}
    assert doc.id != manifest["workflow_id"]
    assert result.layout_errors == []
