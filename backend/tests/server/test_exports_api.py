"""``POST /api/workflows/{id}/exports``: outputs become workspace files, one per ref."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.server.exports import slug
from astro_canvas.settings import Settings
from tests.conftest import authed_client
from tests.server.test_workflows_api import load, wait_status


@pytest.fixture
def api(settings: Settings, test_discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, test_discovery)) as client:
        yield client


def test_slug_keeps_a_readable_folder_name() -> None:
    assert slug("Absorption Line Measurement", "wf") == "Absorption-Line-Measurement"
    assert slug("Redshift Finder / QSO", "wf") == "Redshift-Finder-QSO"
    assert slug("../../etc", "wf") == "etc"
    assert slug("***", "wf-1") == "wf-1"


def ran(api: TestClient) -> dict[str, Any]:
    doc = load("math_chain")
    assert api.post("/api/workflows", json=doc).status_code == 201
    wait_status(api, doc["id"])
    return doc


def test_exports_write_json_files_under_the_workflow_folder(
    api: TestClient, settings: Settings
) -> None:
    doc = ran(api)
    body = api.post(
        f"/api/workflows/{doc['id']}/exports", json={"refs": ["sum.out", "c.out"]}
    ).json()
    assert body["dir"] == "exports/Math-chain"
    assert [f["ref"] for f in body["files"]] == ["sum.out", "c.out"]
    assert {f["format"] for f in body["files"]} == {"json"}
    assert body["skipped"] == []

    written = Path(settings.workspace) / body["files"][0]["path"]
    assert written.name == "sum.out.json"
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload == {"type_id": "astro.Float", "data": {"value": 7.0}}
    assert written.stat().st_size == body["files"][0]["bytes"]


def test_a_chosen_folder_is_used_and_reruns_overwrite(api: TestClient, settings: Settings) -> None:
    doc = ran(api)
    first = api.post(
        f"/api/workflows/{doc['id']}/exports", json={"refs": ["sum.out"], "dir": "results/run1"}
    ).json()
    assert first["files"][0]["path"] == "results/run1/sum.out.json"
    again = api.post(
        f"/api/workflows/{doc['id']}/exports", json={"refs": ["sum.out"], "dir": "results/run1"}
    ).json()
    assert again["files"][0]["path"] == first["files"][0]["path"]
    kept = api.post(
        f"/api/workflows/{doc['id']}/exports",
        json={"refs": ["sum.out"], "dir": "results/run1", "overwrite": False},
    ).json()
    assert kept["files"][0]["path"] == "results/run1/sum.out-1.json"
    assert sorted(p.name for p in (Path(settings.workspace) / "results/run1").iterdir()) == [
        "sum.out-1.json",
        "sum.out.json",
    ]


def test_missing_outputs_and_bad_refs_are_skipped_not_fatal(api: TestClient) -> None:
    doc = ran(api)
    body = api.post(
        f"/api/workflows/{doc['id']}/exports", json={"refs": ["sum", "ghost.out", "sum.out"]}
    ).json()
    assert [(s["ref"], s["reason"]) for s in body["skipped"]] == [
        ("sum", "bad_ref"),
        ("ghost.out", "no_output"),
    ]
    assert body["skipped"][1]["message"] == "no node 'ghost' in the graph"
    assert [f["ref"] for f in body["files"]] == ["sum.out"]


def test_a_failed_node_is_skipped_with_its_own_message(api: TestClient) -> None:
    """A missing value says which of the three reasons it is; "no cached output" said none."""
    doc = {
        "format": "astro-canvas/workflow",
        "version": 1,
        "id": "failed-export",
        "name": "Failed",
        "nodes": {"boom": {"type": "test.fail", "params": {}, "pos": [0, 0]}},
        "edges": {},
    }
    assert api.post("/api/workflows", json=doc).status_code == 201
    status = wait_status(api, doc["id"])
    assert status["nodes"]["boom"]["state"] == "error"

    body = api.post(
        f"/api/workflows/{doc['id']}/exports", json={"refs": ["boom.out"], "run": True}
    ).json()
    assert body["files"] == []
    assert body["skipped"][0]["reason"] == "failed"
    assert body["skipped"][0]["message"].startswith("boom failed:")


def test_an_export_on_the_heels_of_an_edit_waits_for_the_new_value(
    api: TestClient, settings: Settings
) -> None:
    """The nightly's macOS failure: exporting into the middle of a recompute.

    The edit arms the auto-run debounce, so for the next fraction of a second the node's cached
    output is the *old* key's and the new one does not exist yet. Without a wait the export
    answers `no_output` for a value that is milliseconds away, which is what a wizard's Save step
    does to it -- and a client cannot wait for this itself, because its own node states arrive
    after the server has already changed them.
    """
    doc = ran(api)
    doc["nodes"]["c"]["params"]["value"] = 5.0
    assert api.put(f"/api/workflows/{doc['id']}", json=doc).status_code == 200

    body = api.post(f"/api/workflows/{doc['id']}/exports", json={"refs": ["sum.out"]}).json()
    assert body["skipped"] == []
    written = Path(settings.workspace) / body["files"][0]["path"]
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload == {"type_id": "astro.Float", "data": {"value": 31.0}}  # 5**2 + 5 + 1


def test_run_computes_a_cost_gated_node_instead_of_reporting_it_missing(
    api: TestClient, settings: Settings
) -> None:
    """The other half of the nightly's macOS failure.

    An expensive node -- or an `auto` one whose average runtime crossed the threshold, which is
    what a slow machine does to a real analysis chain -- is `stale` after an edit: auto-run leaves
    it alone on purpose and it waits for someone to ask. A wizard's Save step is someone asking,
    and it has no canvas to press Run on, so the export asks for it.
    """
    doc = {
        "format": "astro-canvas/workflow",
        "version": 1,
        "id": "gated-export",
        "name": "Gated",
        "nodes": {
            "c": {"type": "core.math.constant", "params": {"value": 2.0}, "pos": [0, 0]},
            "slow": {
                "type": "test.sleep",
                "params": {"seconds": 0.01},
                "linked": ["x"],
                "pos": [200, 0],
            },
        },
        "edges": {"e1": {"from": ["c", "out"], "to": ["slow", "x"]}},
    }
    assert api.post("/api/workflows", json=doc).status_code == 201
    status = wait_status(api, doc["id"])
    # Auto-run computed the cheap node and left the expensive one alone, which is the point.
    assert status["nodes"]["c"]["state"] == "done"
    assert status["nodes"]["slow"]["state"] != "done"

    without = api.post(f"/api/workflows/{doc['id']}/exports", json={"refs": ["slow.out"]}).json()
    assert [(s["ref"], s["reason"]) for s in without["skipped"]] == [("slow.out", "no_output")]

    body = api.post(
        f"/api/workflows/{doc['id']}/exports", json={"refs": ["slow.out"], "run": True}
    ).json()
    assert body["skipped"] == []
    written = Path(settings.workspace) / body["files"][0]["path"]
    assert json.loads(written.read_text(encoding="utf-8"))["data"] == {"value": 2.0}


def test_paths_outside_the_workspace_are_refused(api: TestClient) -> None:
    doc = ran(api)
    denied = api.post(f"/api/workflows/{doc['id']}/exports", json={"refs": [], "dir": "../escape"})
    assert denied.status_code == 400
    assert api.post("/api/workflows/nope/exports", json={"refs": []}).status_code == 404
