"""Golden-file tests: ``NodeSpec`` JSON for documented nodes must stay stable.

Regenerate with ``ASTRO_CANVAS_UPDATE_GOLDEN=1 uv run pytest tests/sdk/test_schema_golden.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from astro_canvas_core.nodes import math as math_nodes
from astro_canvas_core.nodes import spec as spec_nodes

from astro_canvas.sdk import NodeDef
from tests.sdk import sample_nodes

FIXTURES = Path(__file__).parent / "fixtures"
CASES: dict[str, NodeDef] = {
    "sample_measure": sample_nodes.measure,
    "sample_split": sample_nodes.split,
    "sample_describe": sample_nodes.describe,
    "sample_swap": sample_nodes.swap,
    "core_to_velocity": spec_nodes.to_velocity,
    "core_expr": math_nodes.expr,
}


def _dump(node: NodeDef) -> dict[str, Any]:
    return node.spec.model_dump(mode="json")


@pytest.mark.parametrize("name", sorted(CASES))
def test_node_spec_matches_golden(name: str) -> None:
    path = FIXTURES / f"{name}.json"
    actual = _dump(CASES[name])
    if os.environ.get("ASTRO_CANVAS_UPDATE_GOLDEN") == "1":
        path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert path.is_file(), f"missing golden file {path.name}; run with ASTRO_CANVAS_UPDATE_GOLDEN=1"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected


def test_measure_schema_has_every_widget_feature() -> None:
    """The checklist items in one place: defaults, units, min/max, enum, descriptions."""
    params = {p.name: p for p in sample_nodes.measure.spec.params}
    vmin = params["vmin"].json_schema
    assert vmin["default"] == -200.0
    assert vmin["x-unit"] == "km/s"
    assert vmin["minimum"] == -5000 and vmin["maximum"] == 0
    assert vmin["x-widget"] == "slider" and vmin["x-step"] == 10
    assert vmin["description"] == "Lower integration limit."
    assert params["vmax"].label == "Upper limit"
    assert params["method"].json_schema["enum"] == ["direct", "aod"]
    assert params["method"].link_type == "astro.Str"
    assert params["tag"].json_schema["enum"] == ["a", "b"]
    assert params["tag"].description == "Custom help wins."
    assert params["tag"].advanced is True and params["tag"].json_schema["x-advanced"] is True
    assert params["weights"].json_schema["anyOf"][0] == {
        "items": {"type": "number"},
        "type": "array",
    }
    assert params["weights"].link_type == "astro.Json"
    assert params["snr"].link_type == "astro.Bool"
    assert params["smoothing"].json_schema["$defs"]["Smoothing"]["properties"]["width"] == {
        "default": 3,
        "title": "Width",
        "type": "integer",
    }
    assert params["wrest"].json_schema == {
        "default": 1215.67,
        "description": "Rest wavelength of the line.",
        "title": "Wrest",
        "type": "number",
        "x-unit": "Angstrom",
    }
    assert params["wrest"].unit == "Angstrom"
