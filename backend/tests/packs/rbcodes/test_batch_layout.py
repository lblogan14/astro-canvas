"""The absorption template's ``layouts.batch``: valid spec, bound nodes, and a runnable row."""

from __future__ import annotations

import asyncio
import csv
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from astro_canvas.engine.batch import BatchRunner, spec_from_layout
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.engine.scheduler import SchedulerConfig
from astro_canvas.sdk import NodeRegistry
from tests.engine.conftest import Harness

PACK = Path(__file__).resolve().parents[4] / "packs" / "rbcodes"
TEMPLATE = PACK / "templates" / "absorption-line-measurement.acw"
ROWS = PACK / "sample_data" / "absorption_batch.csv"

SPECGUI_INPUT_COLUMNS = [
    "filename",
    "redshift",
    "transition",
    "slice_vmin",
    "slice_vmax",
    "ew_vmin",
    "ew_vmax",
    "linelist",
    "method",
]


@pytest.fixture(scope="module")
def template() -> WorkflowDoc:
    return WorkflowDoc.model_validate_json(TEMPLATE.read_text(encoding="utf-8"))


@pytest.fixture
async def batch_harness(tmp_path: Path, registry: NodeRegistry) -> AsyncIterator[Harness]:
    """The engine harness (its own fixture lives in ``tests/engine``)."""
    harness = Harness(tmp_path, registry, processes=False)
    harness.bus.bind(asyncio.get_running_loop())
    yield harness
    await harness.close()


def test_the_batch_layout_binds_every_specgui_input_column(template: WorkflowDoc) -> None:
    spec = spec_from_layout(template.layouts["batch"])
    assert [b.column for b in spec.bindings] == SPECGUI_INPUT_COLUMNS
    # The two velocity windows stay separate, as in launch_specgui -b.
    by_column = {b.column: b.ref for b in spec.bindings}
    assert by_column["slice_vmin"] == "slice.vmin" and by_column["ew_vmin"] == "ew.vmin"
    assert by_column["slice_vmax"] == "slice.vmax" and by_column["ew_vmax"] == "ew.vmax"
    assert [c.ref for c in spec.collect] == ["ew.out"]


def test_every_bound_ref_exists_as_a_node_param(
    template: WorkflowDoc, registry: NodeRegistry
) -> None:
    spec = spec_from_layout(template.layouts["batch"])
    for binding in [*spec.bindings]:
        node = template.nodes[binding.node]
        params = {p.name for p in registry.get(node.type).spec.params}
        assert binding.param in params, f"{binding.ref} is not a param of {node.type}"
    for collect in spec.collect:
        outputs = {p.name for p in registry.get(template.nodes[collect.node].type).spec.outputs}
        assert collect.port in outputs
    promoted = {f"{p.node}.{p.param}" for p in template.promoted}
    assert {b.ref for b in spec.bindings} <= promoted


def test_the_bundled_rows_match_the_layout_columns(template: WorkflowDoc) -> None:
    spec = spec_from_layout(template.layouts["batch"])
    assert template.layouts["batch"]["rows"].endswith("absorption_batch.csv")
    with ROWS.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 20
    columns = set(rows[0])
    assert {b.column for b in spec.bindings} <= columns
    # The paths point at the seeded sample folder.
    assert all(row["filename"].startswith("samples/rbcodes/") for row in rows)


async def test_a_row_runs_end_to_end_and_collects_the_measurement(
    batch_harness: Harness, template: WorkflowDoc
) -> None:
    """One real row through the batch runner: the MgII 2796 measurement lands in the results."""
    harness = batch_harness
    samples = harness.workspace.root / "samples" / "rbcodes"
    samples.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PACK / "sample_data" / "sdss1.fits", samples / "sdss1.fits")

    spec = spec_from_layout(template.layouts["batch"]).model_copy(update={"max_workers": 2})
    with ROWS.open(newline="", encoding="utf-8") as handle:
        all_rows = [dict(row) for row in csv.DictReader(handle)]
    # The +-100 and +-200 km/s windows of MgII 2796, plus a row whose file does not exist.
    rows = [row for row in all_rows if row["ew_vmax"] in ("100", "200")][:2]
    rows.append({**rows[0], "filename": "samples/rbcodes/missing.fits"})

    runner = BatchRunner(
        registry=harness.registry,
        cache=harness.cache,
        bus=harness.bus,
        workspace_root=harness.workspace.root,
        scratch_root=harness.workspace.scratch_dir,
        threads=harness.threads,
        processes=None,
        config=lambda: SchedulerConfig(debounce_s=0.01, use_processes=False),
    )
    run = await runner.execute(template, rows, spec)

    assert run.counts() == {"done": 2, "error": 1}
    results = run.results()
    assert {"W", "W_e", "logN", "SNR", "status", "error_message"} <= set(results.columns)
    # The +-200 km/s window is the template's documented measurement (rbcodes 2.4.0).
    assert results.rows[1]["W"] == pytest.approx(2.07, abs=0.1)
    assert results.rows[0]["W"] < results.rows[1]["W"]  # the narrower window integrates less
    assert results.rows[1]["ew_vmax"] == "200" and results.rows[0]["ew_vmax"] == "100"
    assert results.rows[2]["status"] == "error" and results.rows[2]["error_message"]
