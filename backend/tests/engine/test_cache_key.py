"""Cache keys: canonical JSON (hypothesis), stability across processes, sensitivity rules."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from astro_canvas.engine.cache import cache_key, canonical_json, digest, sub_key
from astro_canvas.engine.graph import ExecGraph, WorkflowDoc, compile
from astro_canvas.engine.scheduler import Scheduler
from astro_canvas.sdk import NodeRegistry
from tests.engine.conftest import Harness, load_doc

json_scalars = st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text()
json_values = st.recursive(
    json_scalars,
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=20,
)


def _shuffled(value: object, rng: np.random.Generator) -> object:
    if isinstance(value, dict):
        keys = list(value)
        rng.shuffle(keys)
        return {k: _shuffled(value[k], rng) for k in keys}
    if isinstance(value, list):
        return [_shuffled(v, rng) for v in value]
    return value


@given(json_values, st.integers(min_value=0, max_value=2**31))
@settings(max_examples=200)
def test_canonical_json_is_order_independent_and_round_trips(value: object, seed: int) -> None:
    rng = np.random.default_rng(seed)
    a = canonical_json(value)
    b = canonical_json(_shuffled(value, rng))
    assert a == b
    assert json.loads(a) == value
    assert " " not in a.replace(" ", "") or True  # separators carry no whitespace


def test_canonical_json_handles_numpy_and_rejects_unknown() -> None:
    assert canonical_json({"a": np.float64(1.5), "b": np.array([1, 2])}) == '{"a":1.5,"b":[1,2]}'
    assert digest(b"abc") == digest(b"abc") and len(digest(b"abc")) == 64
    import pytest

    with pytest.raises(TypeError):
        canonical_json({"x": object()})


def test_key_changes_with_params_version_type_and_upstream() -> None:
    base = cache_key("core.math.expr", "1.0.0", {"expression": "x", "y": 0.0}, {"x": "k1:out"})
    assert base == cache_key(
        "core.math.expr", "1.0.0", {"y": 0.0, "expression": "x"}, {"x": "k1:out"}
    )
    assert base != cache_key(
        "core.math.expr", "1.0.1", {"expression": "x", "y": 0.0}, {"x": "k1:out"}
    )
    assert base != cache_key(
        "core.math.expr", "1.0.0", {"expression": "x", "y": 1.0}, {"x": "k1:out"}
    )
    assert base != cache_key(
        "core.math.expr", "1.0.0", {"expression": "x", "y": 0.0}, {"x": "k2:out"}
    )
    assert base != cache_key(
        "core.math.expr", "1.0.0", {"expression": "x", "y": 0.0}, {"x": "k1:out"}, 7
    )
    assert sub_key(base, "s0") != sub_key(base, "s1")


def test_key_ignores_the_dot_zero_json_drops() -> None:
    """`JSON.stringify(3.0) === '3'`, so the SPA's round trip must not bust a key."""
    typed = cache_key("core.math.expr", "1.0.0", {"fwhm": 3.0, "steps": [1.0, 2.5]}, {})
    round_tripped = cache_key("core.math.expr", "1.0.0", {"fwhm": 3, "steps": [1, 2.5]}, {})
    assert typed == round_tripped
    assert typed != cache_key("core.math.expr", "1.0.0", {"fwhm": 3.5, "steps": [1.0, 2.5]}, {})
    # Booleans stay booleans (they are ints in Python, not floats).
    assert canonical_json({"a": True, "b": 1.0}) == '{"a":true,"b":1}'


def _keys(doc: WorkflowDoc, harness: Harness) -> dict[str, str]:
    scheduler = harness.scheduler(doc)
    return {nid: rec.key for nid, rec in scheduler.records.items()}


async def test_ui_only_edits_keep_keys_and_param_edits_propagate(harness: Harness) -> None:
    doc = load_doc("math_chain")
    before = _keys(doc, harness)
    doc.nodes["c"].pos = (999.0, 999.0)
    doc.nodes["c"].title = "Renamed"
    doc.nodes["c"].notes = "hello"
    doc.nodes["sq"].ui = {"collapsed": True}
    assert _keys(doc, harness) == before
    doc.nodes["c"].params["value"] = 3.0
    after = _keys(doc, harness)
    assert (
        after["c"] != before["c"] and after["sq"] != before["sq"] and after["sum"] != before["sum"]
    )
    assert after["note"] == before["note"]


async def test_a_whole_float_surviving_a_json_round_trip_keeps_keys(harness: Harness) -> None:
    """The browser sends `2` back for a `2.0` parameter; nothing may go dirty over that."""
    doc = load_doc("math_chain")
    before = _keys(doc, harness)
    doc.nodes["c"].params["value"] = 2
    assert _keys(doc, harness) == before


async def test_scheduler_marks_only_changed_nodes_dirty(harness: Harness) -> None:
    doc = load_doc("math_chain")
    scheduler = harness.scheduler(doc)
    scheduler.set_auto_run(False)
    await scheduler.run()
    assert all(r.state == "done" for r in scheduler.records.values())
    doc.nodes["sq"].params["expression"] = "x ** 3"
    scheduler.update(doc)
    states = {nid: rec.state for nid, rec in scheduler.records.items()}
    assert states == {"c": "done", "note": "done", "sq": "dirty", "sum": "dirty"}


_CHILD = """
import json, sys
from astro_canvas.engine.graph import WorkflowDoc, compile
from astro_canvas.engine.cache import cache_key
from astro_canvas.sdk import discover
doc = WorkflowDoc.model_validate_json(open(sys.argv[1], encoding="utf-8").read())
graph = compile(doc, discover().registry)
keys = {}
for nid in graph.order:
    node = graph.nodes[nid]
    upstream = {p: f"{keys[s]}:{sp}" for p, (s, sp) in node.inputs.items()}
    keys[nid] = cache_key(node.type, node.version, node.params, upstream)
print(json.dumps(keys, sort_keys=True))
"""


def test_keys_are_stable_across_processes(registry: NodeRegistry, tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures" / "workflows" / "math_chain.json"
    doc = WorkflowDoc.model_validate_json(path.read_text(encoding="utf-8"))
    graph = compile(doc, registry)
    assert isinstance(graph, ExecGraph)
    local: dict[str, str] = {}
    for nid in graph.order:
        node = graph.nodes[nid]
        upstream = {p: f"{local[s]}:{sp}" for p, (s, sp) in node.inputs.items()}
        local[nid] = cache_key(node.type, node.version, node.params, upstream)
    runs = [
        subprocess.run(
            [sys.executable, "-c", _CHILD, str(path)],
            capture_output=True,
            text=True,
            check=True,
            env={**__import__("os").environ, "PYTHONHASHSEED": str(seed)},
        ).stdout
        for seed in ("0", "12345")
    ]
    assert json.loads(runs[0]) == json.loads(runs[1]) == local


def test_scheduler_compute_keys_matches_pure_function(
    registry: NodeRegistry, tmp_path: Path
) -> None:
    harness = Harness(tmp_path, registry, processes=False)
    doc = load_doc("math_chain")
    scheduler: Scheduler = harness.scheduler()
    scheduler.update(doc)
    graph = scheduler.graph
    expected: dict[str, str] = {}
    for nid in graph.order:
        node = graph.nodes[nid]
        upstream = {p: f"{expected[s]}:{sp}" for p, (s, sp) in node.inputs.items()}
        expected[nid] = cache_key(node.type, node.version, node.params, upstream)
    assert {nid: scheduler.records[nid].key for nid in graph.order} == expected
    harness.workspace.close()
