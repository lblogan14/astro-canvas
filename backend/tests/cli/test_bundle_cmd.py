"""``astro-canvas bundle export|import``: the round trip without a server."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astro_canvas import cli
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.settings import Settings
from astro_canvas.store.workspace import Workspace

runner = CliRunner()

DOC: dict[str, object] = {
    "id": "wf-cli-bundle",
    "name": "CLI bundle",
    "nodes": {
        "c": {"type": "core.math.constant", "params": {"value": 3.0}},
        "sum": {"type": "core.math.expr", "params": {"expression": "x + 1"}, "linked": ["x"]},
    },
    "edges": {"e": {"from": ["c", "out"], "to": ["sum", "x"]}},
}


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A workspace with ``wf-cli-bundle`` already stored, and no uv on the path."""
    root = tmp_path / "ws"
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ASTRO_CANVAS_WORKSPACE", str(root))
    from astro_canvas.sdk import discover
    from astro_canvas.server.runtime import EngineRuntime

    settings = Settings(
        workspace=root, config_dir=tmp_path / "cfg", auth="none", process_pool=False
    )
    runtime = EngineRuntime(settings, discover().registry)
    runtime.save(WorkflowDoc.model_validate(DOC))
    runtime.workspace.close()
    return root


def test_export_writes_a_bundle_next_to_the_data(workspace: Path) -> None:
    result = runner.invoke(cli.app, ["bundle", "export", "wf-cli-bundle"])
    assert result.exit_code == 0, result.output
    written = sorted((workspace / "bundles").glob("*.acw"))
    assert len(written) == 1
    with zipfile.ZipFile(written[0]) as zf:
        assert "workflow.json" in zf.namelist()
        assert json.loads(zf.read("workflow.json"))["name"] == "CLI bundle"


def test_export_honours_an_explicit_output_path(workspace: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / "share.acw"
    result = runner.invoke(
        cli.app, ["bundle", "export", "wf-cli-bundle", "--out", str(target), "--no-figures"]
    )
    assert result.exit_code == 0, result.output
    assert target.is_file() and str(target) in result.output


def test_export_refuses_an_unknown_workflow(workspace: Path) -> None:
    result = runner.invoke(cli.app, ["bundle", "export", "nope"])
    assert result.exit_code == 1 and "unknown workflow 'nope'" in result.output


def test_import_into_another_workspace_restores_the_document(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance: export here, import there, same document -- the cross-machine path."""
    target = tmp_path / "share.acw"
    assert (
        runner.invoke(
            cli.app, ["bundle", "export", "wf-cli-bundle", "--out", str(target)]
        ).exit_code
        == 0
    )

    fresh = tmp_path / "fresh"
    monkeypatch.setenv("ASTRO_CANVAS_WORKSPACE", str(fresh))
    result = runner.invoke(cli.app, ["bundle", "import", str(target)])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("imported CLI bundle as ")
    # The import gives the document a fresh id so it cannot collide with a local one.
    imported_id = result.output.split(" as ", 1)[1].strip()
    assert imported_id != DOC["id"]

    reopened = Workspace(fresh)
    try:
        with reopened.session() as session:
            from astro_canvas.store.models import Workflow

            row = session.get(Workflow, imported_id)
            assert row is not None
            restored = WorkflowDoc.model_validate_json(row.doc_json)
            assert restored.name == "CLI bundle"
            assert set(restored.nodes) == {"c", "sum"}
    finally:
        reopened.close()


def test_import_refuses_a_file_that_is_not_a_bundle(workspace: Path, tmp_path: Path) -> None:
    junk = tmp_path / "junk.acw"
    junk.write_bytes(b"not a zip at all")
    result = runner.invoke(cli.app, ["bundle", "import", str(junk)])
    assert result.exit_code == 1


def test_import_reports_a_missing_file(workspace: Path, tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["bundle", "import", str(tmp_path / "absent.acw")])
    assert result.exit_code == 1
