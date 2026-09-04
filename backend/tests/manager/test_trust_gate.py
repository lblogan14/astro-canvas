"""The code-node trust gate: quarantine on import, trust to run, edit to re-quarantine."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.manager.trust import code_snippets, snippet_hash
from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client
from tests.server.test_workflows_api import wait_status

SOURCE = "out = 6 * 7"


def doc_with_code(source: str = SOURCE, workflow_id: str = "wf-code") -> dict[str, Any]:
    return {
        "id": workflow_id,
        "name": "Code demo",
        "nodes": {
            "py": {
                "type": "core.code.python",
                "params": {
                    "source": source,
                    "inputs": [],
                    "outputs": [{"name": "out", "type": "astro.Float"}],
                },
            }
        },
        "edges": {},
    }


def as_bundle(doc: dict[str, Any]) -> bytes:
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w") as zf:
        zf.writestr("workflow.json", json.dumps(doc))
    return sink.getvalue()


@pytest.fixture
def client(settings: Settings, discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, discovery)) as client:
        yield client


# --- hashing ------------------------------------------------------------------------------------


def test_a_snippet_hash_ignores_line_endings() -> None:
    assert snippet_hash("a = 1\nb = 2") == snippet_hash("a = 1\r\nb = 2")


def test_editing_a_snippet_changes_its_hash() -> None:
    assert snippet_hash(SOURCE) != snippet_hash(SOURCE + " + 1")


def test_code_nodes_are_found_inside_subgraph_bodies() -> None:
    doc = WorkflowDoc.model_validate(
        {
            "id": "wf",
            "nodes": {"i": {"type": "subgraph:sg1"}},
            "subgraphs": {
                "sg1": {
                    "name": "body",
                    "nodes": {"py": {"type": "core.code.python", "params": {"source": SOURCE}}},
                }
            },
        }
    )
    assert [s.node for s in code_snippets(doc)] == ["sg1/py"]


# --- local authoring ----------------------------------------------------------------------------


def test_locally_written_code_is_trusted_on_save(client: TestClient) -> None:
    """Design 11: a snippet the user typed here needs no dialog."""
    assert client.post("/api/workflows", json=doc_with_code()).status_code == 201
    review = client.get("/api/workflows/wf-code/trust").json()
    assert not review["quarantined"]
    assert review["snippets"][0]["decision"] == "trusted"
    assert client.get("/api/workflows/wf-code/status").json()["node_errors"] == {}


def test_a_locally_authored_code_node_runs(client: TestClient) -> None:
    client.post("/api/workflows", json=doc_with_code())
    client.post("/api/workflows/wf-code/run", json={"targets": None})
    wait_status(client, "wf-code")
    output = client.get("/api/outputs/py/out?workflow_id=wf-code&fmt=json")
    assert output.status_code == 200
    assert output.json()["data"] == {"value": 42.0}


# --- imported code ------------------------------------------------------------------------------


def test_an_imported_bundle_with_code_opens_quarantined(client: TestClient) -> None:
    result = client.post(
        "/api/bundles/import",
        files={"file": ("code.acw", as_bundle(doc_with_code()), "application/zip")},
    ).json()
    assert result["quarantined"]
    assert [s["decision"] for s in result["snippets"]] == [None]

    workflow_id = result["workflow_id"]
    status = client.get(f"/api/workflows/{workflow_id}/status").json()
    assert [i["code"] for i in status["node_errors"]["py"]] == ["quarantined"]
    assert "review and trust" in status["node_errors"]["py"][0]["message"]


def test_a_quarantined_code_node_does_not_run(client: TestClient) -> None:
    result = client.post(
        "/api/bundles/import",
        files={"file": ("code.acw", as_bundle(doc_with_code()), "application/zip")},
    ).json()
    workflow_id = result["workflow_id"]
    client.post(f"/api/workflows/{workflow_id}/run", json={"targets": None})
    wait_status(client, workflow_id)
    assert client.get(f"/api/outputs/py/out?workflow_id={workflow_id}&fmt=json").status_code == 404


def test_trusting_the_snippet_lets_it_run(client: TestClient) -> None:
    """Acceptance: a bundle with a code node opens quarantined; trusting enables execution."""
    result = client.post(
        "/api/bundles/import",
        files={"file": ("code.acw", as_bundle(doc_with_code()), "application/zip")},
    ).json()
    workflow_id = result["workflow_id"]

    decision = client.post(
        "/api/manager/trust", json={"hash": snippet_hash(SOURCE), "decision": "trusted"}
    )
    assert decision.status_code == 200

    review = client.get(f"/api/workflows/{workflow_id}/trust").json()
    assert not review["quarantined"] and review["blocked_nodes"] == []
    assert client.get(f"/api/workflows/{workflow_id}/status").json()["node_errors"] == {}

    client.post(f"/api/workflows/{workflow_id}/run", json={"targets": None})
    wait_status(client, workflow_id)
    assert client.get(f"/api/outputs/py/out?workflow_id={workflow_id}&fmt=json").status_code == 200


def test_blocking_a_snippet_keeps_it_quarantined(client: TestClient) -> None:
    result = client.post(
        "/api/bundles/import",
        files={"file": ("code.acw", as_bundle(doc_with_code()), "application/zip")},
    ).json()
    client.post("/api/manager/trust", json={"hash": snippet_hash(SOURCE), "decision": "blocked"})
    status = client.get(f"/api/workflows/{result['workflow_id']}/status").json()
    assert status["node_errors"]["py"][0]["message"] == "this code snippet was blocked"


def test_editing_a_trusted_snippet_re_quarantines_it(client: TestClient) -> None:
    """Acceptance: an edited snippet is a different snippet, so the gate closes again."""
    result = client.post(
        "/api/bundles/import",
        files={"file": ("code.acw", as_bundle(doc_with_code()), "application/zip")},
    ).json()
    workflow_id = result["workflow_id"]
    client.post("/api/manager/trust", json={"hash": snippet_hash(SOURCE), "decision": "trusted"})
    assert client.get(f"/api/workflows/{workflow_id}/status").json()["node_errors"] == {}

    edited = client.get(f"/api/workflows/{workflow_id}").json()
    edited["nodes"]["py"]["params"]["source"] = "out = 1 + 1"
    saved = client.put(f"/api/workflows/{workflow_id}", json=edited)
    assert saved.status_code == 200
    assert [i["code"] for i in saved.json()["node_errors"]["py"]] == ["quarantined"]


def test_trusting_every_snippet_lifts_the_quarantine_flag(client: TestClient) -> None:
    """Once the document has no untrusted code left, later local edits are trusted again."""
    result = client.post(
        "/api/bundles/import",
        files={"file": ("code.acw", as_bundle(doc_with_code()), "application/zip")},
    ).json()
    workflow_id = result["workflow_id"]
    client.post("/api/manager/trust", json={"hash": snippet_hash(SOURCE), "decision": "trusted"})

    doc = client.get(f"/api/workflows/{workflow_id}").json()
    assert doc["meta"]["quarantine"] is True
    client.put(f"/api/workflows/{workflow_id}", json=doc)  # a save with everything trusted
    assert "quarantine" not in client.get(f"/api/workflows/{workflow_id}").json()["meta"]

    edited = client.get(f"/api/workflows/{workflow_id}").json()
    edited["nodes"]["py"]["params"]["source"] = "out = 3 * 3"
    saved = client.put(f"/api/workflows/{workflow_id}", json=edited)
    assert saved.json()["node_errors"] == {}


def test_forgetting_a_decision_quarantines_the_snippet_again(client: TestClient) -> None:
    client.post("/api/workflows", json=doc_with_code())
    assert client.get("/api/workflows/wf-code/status").json()["node_errors"] == {}

    assert client.delete(f"/api/manager/trust/{snippet_hash(SOURCE)}").status_code == 204
    assert client.get("/api/workflows/wf-code/status").json()["node_errors"]["py"]
    assert client.delete(f"/api/manager/trust/{snippet_hash(SOURCE)}").status_code == 404


def test_decisions_are_listed(client: TestClient) -> None:
    client.post("/api/workflows", json=doc_with_code())
    records = client.get("/api/manager/trust").json()
    assert [r["hash"] for r in records] == [snippet_hash(SOURCE)]
    assert records[0]["decision"] == "trusted"


def test_a_bundle_without_code_is_not_quarantined(client: TestClient) -> None:
    doc = {"id": "plain", "name": "Plain", "nodes": {"c": {"type": "core.math.constant"}}}
    result = client.post(
        "/api/bundles/import", files={"file": ("plain.acw", as_bundle(doc), "application/zip")}
    ).json()
    assert not result["quarantined"] and result["snippets"] == []
