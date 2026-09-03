"""``compute_preview``: run a node body with candidate params off the scheduler."""

from __future__ import annotations

import pytest

from astro_canvas.engine.preview import PreviewError, compute_preview
from astro_canvas.engine.scheduler import UpstreamMissingError
from tests.engine.conftest import Harness, make_doc

DOC = make_doc(
    {
        "src": {"type": "test.spec.make", "params": {"n": 201}},
        "crop": {"type": "core.spec.crop", "params": {"lo": 1200.0, "hi": 1300.0}},
        "c": {"type": "core.math.constant", "params": {"value": 1500.0}},
        "crop2": {
            "type": "core.spec.crop",
            "params": {"lo": 1000.0, "hi": 1100.0},
            "linked": ["hi"],
        },
    },
    {
        "e1": {"from": ["src", "out"], "to": ["crop", "spec"]},
        "e2": {"from": ["src", "out"], "to": ["crop2", "spec"]},
        "e3": {"from": ["c", "out"], "to": ["crop2", "hi"]},
    },
)


async def test_preview_layers_params_over_the_document_and_leaves_the_cache_alone(
    harness: Harness,
) -> None:
    scheduler = harness.scheduler(DOC)
    await scheduler.run()
    before = scheduler.output("crop", "out")
    assert before is not None and len(before) == 21
    type_id, outputs = compute_preview(
        scheduler, harness.registry, node_id="crop", params={"hi": 1250.0}
    )
    assert type_id == "core.spec.crop" and set(outputs) == {"out"}
    assert len(outputs["out"]) == 11
    # Nothing was committed: the cached output and the node state are untouched.
    after = scheduler.output("crop", "out")
    assert after is not None and len(after) == 21
    assert scheduler.records["crop"].state == "done"
    # Linked params take the upstream value unless overridden.
    _, linked = compute_preview(scheduler, harness.registry, node_id="crop2", params={})
    assert len(linked["out"]) == 101
    _, overridden = compute_preview(
        scheduler, harness.registry, node_id="crop2", params={"hi": 1050.0}
    )
    assert len(overridden["out"]) == 11


async def test_preview_by_type_and_error_cases(harness: Harness) -> None:
    scheduler = harness.scheduler(DOC)
    type_id, outputs = compute_preview(
        scheduler, harness.registry, node_type="core.math.constant", params={"value": 4.0}
    )
    assert type_id == "core.math.constant" and outputs["out"].model_dump()["value"] == 4.0
    with pytest.raises(UpstreamMissingError):
        compute_preview(scheduler, harness.registry, node_id="crop")
    with pytest.raises(PreviewError):
        compute_preview(scheduler, harness.registry, node_id="missing")
    with pytest.raises(PreviewError):
        compute_preview(scheduler, harness.registry, node_type="core.spec.crop")
    with pytest.raises(PreviewError):
        compute_preview(scheduler, harness.registry)
    with pytest.raises(PreviewError):
        compute_preview(scheduler, harness.registry, node_type="test.expand.sum3")
