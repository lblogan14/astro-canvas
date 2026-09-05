"""Phase 13, scope item 4: every failure reaches the UI as something a user can act on.

Three surfaces: the hint table shared by node failures and REST failures, the unhandled-exception
handler that replaces FastAPI's bare "Internal Server Error", and the recovery of a stored
document that no longer validates.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from astro_canvas.engine.hints import hint_for
from astro_canvas.sdk import BlobError, DiscoveryResult
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


# --- hints ---------------------------------------------------------------------------------------


class _Model(BaseModel):
    n: int


def test_hints_cover_the_engine_and_the_common_failures() -> None:
    try:
        _Model(n="not a number")  # type: ignore[arg-type]
    except ValidationError as exc:
        assert hint_for(exc) == "Check the node's parameters against its schema."
    else:  # pragma: no cover - the model really does reject that
        pytest.fail("expected a ValidationError")

    assert hint_for(BlobError("nope")) is not None
    assert "workspace" in (hint_for(FileNotFoundError(2, "no such file")) or "")
    assert "memory" in (hint_for(MemoryError()) or "").lower()
    assert "installed" in (hint_for(ModuleNotFoundError("no module named 'rbvfit'")) or "")
    assert "time limit" in (hint_for(TimeoutError()) or "")


def test_a_subclass_inherits_its_base_hint() -> None:
    """A pack's own `OSError` subclass gets the filesystem advice without being listed."""

    class WeirdDiskError(OSError):
        pass

    assert hint_for(WeirdDiskError("disk on fire")) == hint_for(OSError("disk on fire"))


def test_an_exception_with_nothing_useful_to_say_gets_no_hint() -> None:
    assert hint_for(RuntimeError("boom")) is None


def test_pack_exceptions_are_matched_by_name_without_importing_them() -> None:
    """`astropy` and `httpx` errors are named, not imported: the engine may not depend on them."""

    class UnitConversionError(Exception):
        pass

    class ConnectError(Exception):
        pass

    assert "units" in (hint_for(UnitConversionError("Angstrom to Jy")) or "").lower()
    assert "archive" in (hint_for(ConnectError("connection refused")) or "")


# --- the unhandled-exception handler -------------------------------------------------------------


def add_route(app: Any, path: str, handler: Any) -> None:
    """Add one GET route *ahead* of the SPA catch-all `mount_static` registers.

    Routes match in registration order, and with a built SPA in `astro_canvas/static` the
    catch-all owns every path that `create_app` did not claim.
    """
    router = APIRouter()
    router.add_api_route(path, handler, methods=["GET"])
    app.include_router(router, prefix="/api")
    app.router.routes.insert(0, app.router.routes.pop())


def test_an_unhandled_exception_answers_with_a_message_hint_and_request_id(
    settings: Settings, test_discovery: DiscoveryResult
) -> None:
    app = create_app(settings, test_discovery)

    async def boom() -> None:
        raise FileNotFoundError(2, "no such file", "spectrum.fits")

    add_route(app, "/boom", boom)
    # `raise_server_exceptions=False` is how the client sees what a browser would see: Starlette
    # returns the handler's response *and* re-raises so the server logs the traceback.
    with authed_client(app, raise_server_exceptions=False) as client:
        response = client.get("/api/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"].startswith("FileNotFoundError:")
    assert "workspace" in body["hint"]
    assert len(body["request_id"]) == 12


def test_a_pydantic_error_answers_422_rather_than_500(
    settings: Settings, test_discovery: DiscoveryResult
) -> None:
    app = create_app(settings, test_discovery)

    async def bad_model() -> None:
        _Model(n="nope")  # type: ignore[arg-type]

    add_route(app, "/bad-model", bad_model)
    with authed_client(app) as client:
        response = client.get("/api/bad-model")
    assert response.status_code == 422
    assert response.json()["hint"] == "Check the node's parameters against its schema."


# --- recovering an unreadable document -----------------------------------------------------------


def corrupt(api: TestClient, workflow_id: str, doc_json: str) -> None:
    """Overwrite the stored document the way a bad migration or a hand edit would."""
    from sqlalchemy import select

    runtime = api.app.state.runtime
    from astro_canvas.store.models import Workflow

    with runtime.workspace.session() as session:
        row = session.scalars(select(Workflow).where(Workflow.id == workflow_id)).one()
        row.doc_json = doc_json
        session.commit()


def test_an_unreadable_document_comes_back_from_its_newest_version(api: TestClient) -> None:
    doc = load("math_chain")
    doc["id"] = "recover-me"
    assert api.post("/api/workflows", json=doc).status_code == 201
    # A second save, so there are two versions and the newest is the one that must come back.
    doc["nodes"]["c"]["params"]["value"] = 7.0
    assert api.put("/api/workflows/recover-me", json=doc).status_code == 200
    versions = api.get("/api/workflows/recover-me/versions").json()
    assert len(versions) == 2

    corrupt(api, "recover-me", json.dumps({"format": "astro-canvas/workflow", "nodes": "?"}))

    body = api.get("/api/workflows/recover-me").json()
    assert body["nodes"]["c"]["params"]["value"] == 7.0
    recovered = body["meta"]["recovered"]
    assert recovered["version"] == versions[0]["id"]
    assert "ValidationError" in recovered["reason"]

    # Saving is how the user accepts it: the notice is not written into the document.
    saved = api.put("/api/workflows/recover-me", json=body)
    assert saved.status_code == 200
    assert "recovered" not in saved.json()["doc"]["meta"]
    assert "recovered" not in api.get("/api/workflows/recover-me").json()["meta"]


def test_a_document_with_no_readable_version_answers_422(api: TestClient) -> None:
    doc = load("math_chain")
    doc["id"] = "hopeless"
    assert api.post("/api/workflows", json=doc).status_code == 201
    broken = json.dumps({"format": "astro-canvas/workflow", "nodes": "?"})
    corrupt(api, "hopeless", broken)
    from sqlalchemy import select

    from astro_canvas.store.models import WorkflowVersion

    runtime = api.app.state.runtime
    with runtime.workspace.session() as session:
        for row in session.scalars(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == "hopeless")
        ).all():
            row.doc_json = broken
        session.commit()

    response = api.get("/api/workflows/hopeless")
    assert response.status_code == 422
    body = response.json()
    assert body["detail"].startswith("ValidationError")
    assert body["hint"] == "Check the node's parameters against its schema."


def test_the_summary_list_survives_an_unreadable_document(api: TestClient) -> None:
    """A broken row must not take the Workflows panel down with it."""
    doc = load("math_chain")
    doc["id"] = "listed"
    assert api.post("/api/workflows", json=doc).status_code == 201
    corrupt(api, "listed", "{not json at all")
    listed = api.get("/api/workflows").json()
    assert [row["id"] for row in listed if row["id"] == "listed"] == ["listed"]


# --- a workspace that went away ------------------------------------------------------------------


def test_a_missing_workspace_is_reported_rather_than_empty(api: TestClient) -> None:
    import shutil

    assert api.get("/api/workspace").json()["available"] is True
    workspace = api.app.state.runtime.workspace
    root = Path(workspace.root)
    # Windows will not delete a folder holding an open SQLite file, which is also what a user
    # unplugging the drive does *not* care about: close the handles first, then take it away.
    workspace.close()
    shutil.rmtree(root)
    assert not root.exists()

    info = api.get("/api/workspace").json()
    assert info["available"] is False
    assert info["root"] == str(root)
    tree = api.get("/api/workspace/tree")
    assert tree.status_code == 410
    assert "workspace folder is gone" in tree.json()["detail"]
