"""Every shipped template opens into a working GUI: layouts resolve and name a default."""

from __future__ import annotations

from pathlib import Path

import pytest

from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.engine.layouts import (
    layout_issues,
    parse_item,
    parse_layout,
)
from astro_canvas.server.templates import default_layout

TEMPLATES = Path(__file__).resolve().parents[4] / "packs" / "rbcodes" / "templates"

EXPECTED_DEFAULT = {
    "absorption-line-measurement": "wizard",
    "redshift-finder": "dashboard",
    "multi-spectrum-viewer": "dashboard",
    "ifu-cube-explorer": "dashboard",
}


def load(name: str) -> WorkflowDoc:
    return WorkflowDoc.model_validate_json((TEMPLATES / f"{name}.acw").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(EXPECTED_DEFAULT))
def test_template_layouts_resolve(name: str) -> None:
    doc = load(name)
    assert layout_issues(doc) == []
    assert doc.promoted, "a template without promoted params has nothing to show in App mode"
    assert doc.views, "a template without views has nothing to show on a dashboard"


@pytest.mark.parametrize("name", sorted(EXPECTED_DEFAULT))
def test_template_opens_in_its_documented_layout(name: str) -> None:
    doc = load(name)
    expected = EXPECTED_DEFAULT[name]
    assert doc.meta["default_layout"] == expected
    assert default_layout(doc) == expected
    assert expected in doc.layouts


def test_absorption_wizard_follows_the_specgui_tabs() -> None:
    """The steps of design 8.5: Load, Redshift, Transition, Continuum, Measure, Save."""
    doc = load("absorption-line-measurement")
    wizard, issue = parse_layout("wizard", doc.layouts["wizard"])
    assert issue is None and wizard is not None
    steps = wizard.steps  # type: ignore[attr-defined]
    assert [step.title for step in steps] == [
        "Load",
        "Redshift",
        "Transition",
        "Continuum",
        "Measure",
        "Save",
    ]
    # Every step gates on the nodes it edits, so Next means "this step has run".
    assert [step.nodes for step in steps] == [
        ["load"],
        ["redshift"],
        ["transition", "slice"],
        ["continuum"],
        ["ew"],
        ["save"],
    ]
    measure = steps[4]
    assert parse_item(measure.items[0]) is not None
    assert any(str(item).startswith("view:") for item in measure.items)


def test_dashboard_tiles_stay_inside_the_grid() -> None:
    for name in ("redshift-finder", "multi-spectrum-viewer", "ifu-cube-explorer"):
        doc = load(name)
        dashboard, issue = parse_layout("dashboard", doc.layouts["dashboard"])
        assert issue is None and dashboard is not None
        cols = dashboard.cols  # type: ignore[attr-defined]
        for tile in dashboard.items:  # type: ignore[attr-defined]
            assert tile.x >= 0 and tile.y >= 0, f"{name}: {tile.ref} is off the grid"
            assert tile.x + tile.w <= cols, f"{name}: {tile.ref} overflows {cols} columns"


def test_absorption_batch_columns_still_match_the_promoted_params() -> None:
    """Phase 09's batch layout must survive the phase 10 regrouping of `promoted`."""
    doc = load("absorption-line-measurement")
    refs = {p.ref for p in doc.promoted}
    columns = doc.layouts["batch"]["columns"]
    assert {entry["promoted"] for entry in columns} <= refs
    assert doc.layouts["batch"]["rows"] == "samples/rbcodes/absorption_batch.csv"
