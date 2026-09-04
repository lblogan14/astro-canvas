"""``engine.layouts``: item refs parse, sections validate, stale refs are reported."""

from __future__ import annotations

from typing import Any

from astro_canvas.engine.layouts import (
    AppLayout,
    DashboardLayout,
    WizardLayout,
    layout_issues,
    parse_item,
    parse_layout,
)
from tests.engine.conftest import load_doc, make_doc


def doc_with(**layouts: Any) -> Any:
    """A two-node document promoting ``c.value`` and pinning ``view:out``."""
    return make_doc(
        {"c": {"type": "test.const"}, "sq": {"type": "test.square"}},
        {"e": {"from": ["c", "out"], "to": ["sq", "x"]}},
        promoted=[{"node": "c", "param": "value", "label": "Value", "group": "Setup", "order": 1}],
        views=[{"id": "out", "node": "sq", "port": "out", "kind": "value-chip"}],
        layouts=layouts,
    )


# --- refs --------------------------------------------------------------------------------------


def test_item_refs_parse_in_string_and_object_form() -> None:
    promoted = parse_item("promoted:n2.z")
    assert promoted is not None
    assert (promoted.kind, promoted.ref, promoted.node_param) == ("promoted", "n2.z", ("n2", "z"))
    assert promoted.text == "promoted:n2.z"
    view = parse_item("view:v1")
    assert view is not None
    assert (view.kind, view.ref, view.node_param) == ("view", "v1", ("", ""))
    # The batch column shape and an explicit {"ref": …} tile both resolve to the same thing.
    assert parse_item({"promoted": "n2.z"}) == promoted
    assert parse_item({"ref": "view:v1"}) == view
    assert parse_item({"view": "v1"}) == view


def test_nested_promoted_refs_keep_the_whole_node_path() -> None:
    item = parse_item("promoted:inst/plus.y")
    assert item is not None
    assert item.node_param == ("inst/plus", "y")


def test_malformed_refs_are_rejected() -> None:
    for raw in ["n2.z", "promoted:", "promoted:z", "view:", "", 7, None, {"nope": 1}]:
        assert parse_item(raw) is None


# --- sections ----------------------------------------------------------------------------------


def test_sections_parse_with_defaults_and_keep_unknown_keys() -> None:
    section = {"sections": [{"title": "Setup", "items": ["promoted:c.value"]}]}
    app, issue = parse_layout("app", section)
    assert issue is None
    assert isinstance(app, AppLayout)
    assert app.sections[0].title == "Setup"

    wizard, issue = parse_layout("wizard", {"steps": [{"title": "Load", "nodes": ["c"]}]})
    assert issue is None
    assert isinstance(wizard, WizardLayout)
    assert wizard.steps[0].nodes == ["c"] and wizard.steps[0].items == []

    dash, issue = parse_layout(
        "dashboard", {"items": [{"ref": "view:out", "x": 1, "y": 2, "w": 6, "h": 3, "tag": "keep"}]}
    )
    assert issue is None
    assert isinstance(dash, DashboardLayout)
    assert (dash.cols, dash.row_height) == (12, 48)
    tile = dash.items[0]
    assert (tile.x, tile.y, tile.w, tile.h) == (1, 2, 6, 3)
    # Extensions round-trip: an unknown tile key survives the model.
    assert tile.model_dump()["tag"] == "keep"


def test_unknown_layout_names_are_not_parsed() -> None:
    parsed, issue = parse_layout("hologram", {"whatever": True})
    assert parsed is None and issue is None


def test_malformed_section_is_one_bad_layout_issue() -> None:
    parsed, issue = parse_layout("dashboard", {"cols": 0, "items": []})
    assert parsed is None
    assert issue is not None
    assert issue.code == "bad_layout" and issue.layout == "dashboard"
    assert "cols" in issue.message


# --- documents ---------------------------------------------------------------------------------


def test_resolvable_layouts_report_nothing() -> None:
    doc = doc_with(
        app={"sections": [{"title": "Setup", "items": ["promoted:c.value", "view:out"]}]},
        wizard={"steps": [{"title": "Load", "items": ["promoted:c.value"]}]},
        dashboard={"cols": 12, "items": [{"ref": "view:out", "w": 6, "h": 4}]},
        batch={"columns": [{"promoted": "c.value", "column": "value"}], "collect": ["sq.out"]},
    )
    assert layout_issues(doc) == []


def test_stale_refs_are_reported_per_layout() -> None:
    doc = doc_with(
        app={"sections": [{"title": "Setup", "items": ["promoted:sq.x", "view:ghost", "c.value"]}]},
        dashboard={"items": [{"ref": "promoted:gone.value"}]},
    )
    issues = layout_issues(doc)
    assert [(i.layout, i.code, i.ref) for i in issues] == [
        ("app", "unknown_promoted", "sq.x"),
        ("app", "unknown_view", "ghost"),
        ("app", "bad_ref", "c.value"),
        ("dashboard", "unknown_promoted", "gone.value"),
    ]
    assert [i.index for i in issues] == [0, 1, 2, 0]
    # The message distinguishes "not promoted" from "no such node".
    assert "'x' is not promoted" in issues[0].message
    assert "'gone' is not in the document" in issues[3].message


def test_promoted_and_views_pointing_at_removed_nodes_are_reported() -> None:
    doc = doc_with()
    del doc.nodes["sq"]
    doc.promoted.append(
        type(doc.promoted[0])(node="ghost", param="z", label=None, group=None, order=2)
    )
    doc.views.append(doc.views[0].model_copy(update={"id": "out"}))
    issues = layout_issues(doc)
    assert [(i.layout, i.code, i.ref) for i in issues] == [
        ("promoted", "unknown_node", "ghost.z"),
        ("views", "unknown_node", "out"),
        ("views", "duplicate_view", "out"),
        ("views", "unknown_node", "out"),
    ]


def test_batch_layout_refs_are_checked_through_the_runner_parser() -> None:
    doc = doc_with(batch={"columns": ["ghost.value", "c.value"], "collect": ["nope.out"]})
    issues = layout_issues(doc)
    assert [(i.code, i.ref) for i in issues] == [
        ("unknown_node", "ghost.value"),
        ("unknown_node", "nope.out"),
    ]
    assert all(issue.layout == "batch" for issue in issues)


def test_documents_without_layouts_are_clean() -> None:
    assert layout_issues(load_doc("math_chain")) == []
