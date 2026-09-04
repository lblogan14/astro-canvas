"""The ``layouts`` sections of a document (design 7.1, 8.4): app, wizard and dashboard.

A layout is a UI description the engine never executes. What the engine does do is *check* it:
every item is a ref to a promoted param (``"promoted:<node>.<param>"``) or a pinned view
(``"view:<id>"``), and a ref that no longer resolves is the difference between a form that is
missing one field and a form that silently renders nothing. ``WorkflowDoc.layouts`` therefore
stays an open mapping -- unknown layout names and unknown keys round-trip untouched -- and the
models here are applied per section, reporting problems instead of rejecting the document.

``layouts.batch`` is parsed by :mod:`astro_canvas.engine.batch` (it feeds a runner rather than a
form); its column and collect refs are checked here too so one pass covers all four layouts.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from astro_canvas.engine.batch import spec_from_layout
from astro_canvas.engine.graph import WorkflowDoc

PROMOTED_PREFIX = "promoted:"
VIEW_PREFIX = "view:"

LayoutName = Literal["app", "wizard", "dashboard", "batch"]
LAYOUT_NAMES: tuple[LayoutName, ...] = ("app", "wizard", "dashboard", "batch")

IssueCode = Literal[
    "bad_layout",
    "bad_ref",
    "unknown_promoted",
    "unknown_view",
    "unknown_node",
    "duplicate_view",
]


# --- item refs ---------------------------------------------------------------------------------


class ItemRef(BaseModel):
    """One entry of a layout section: a promoted param or a pinned view."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["promoted", "view"]
    ref: str
    """``"<node>.<param>"`` for a promoted param, the view id for a view."""

    @property
    def text(self) -> str:
        return f"{PROMOTED_PREFIX if self.kind == 'promoted' else VIEW_PREFIX}{self.ref}"

    @property
    def node_param(self) -> tuple[str, str]:
        """The ``(node, param)`` a promoted ref addresses (``("", "")`` for a view)."""
        if self.kind != "promoted":
            return ("", "")
        node, _, param = self.ref.rpartition(".")
        return (node, param)


def parse_item(raw: object) -> ItemRef | None:
    """``"promoted:n2.z"`` / ``"view:v1"`` (or the object form) as an ``ItemRef``, else ``None``."""
    if isinstance(raw, Mapping):
        promoted = raw.get("promoted")
        if isinstance(promoted, str) and promoted:
            return ItemRef(kind="promoted", ref=promoted)
        view = raw.get("view")
        if isinstance(view, str) and view:
            return ItemRef(kind="view", ref=view)
        raw = raw.get("ref")
    if not isinstance(raw, str):
        return None
    if raw.startswith(PROMOTED_PREFIX):
        ref = raw[len(PROMOTED_PREFIX) :]
        return ItemRef(kind="promoted", ref=ref) if "." in ref else None
    if raw.startswith(VIEW_PREFIX):
        ref = raw[len(VIEW_PREFIX) :]
        return ItemRef(kind="view", ref=ref) if ref else None
    return None


# --- sections ----------------------------------------------------------------------------------


class AppSection(BaseModel):
    """One titled block of the App form."""

    model_config = ConfigDict(extra="allow")

    title: str = ""
    items: list[Any] = Field(default_factory=list)
    description: str | None = None


class AppLayout(BaseModel):
    """``layouts.app``: a scrolling form of sections plus a column of views."""

    model_config = ConfigDict(extra="allow")

    sections: list[AppSection] = Field(default_factory=list)


class WizardStep(BaseModel):
    """One step of the Wizard: its items and the nodes that must finish before *Next*."""

    model_config = ConfigDict(extra="allow")

    title: str = ""
    items: list[Any] = Field(default_factory=list)
    description: str | None = None
    nodes: list[str] = Field(
        default_factory=list,
        description="Nodes gating Next; defaults to the nodes the step's items touch.",
    )
    optional: bool = False


class WizardLayout(BaseModel):
    """``layouts.wizard``: ordered steps (design 8.5's specgui tabs)."""

    model_config = ConfigDict(extra="allow")

    steps: list[WizardStep] = Field(default_factory=list)


class DashboardItem(BaseModel):
    """One tile of the Dashboard grid."""

    model_config = ConfigDict(extra="allow")

    ref: str
    x: int = 0
    y: int = 0
    w: int = 4
    h: int = 4


class DashboardLayout(BaseModel):
    """``layouts.dashboard``: a ``cols``-wide grid of view and param tiles."""

    model_config = ConfigDict(extra="allow")

    cols: int = Field(default=12, ge=1, le=48)
    row_height: int = Field(default=48, ge=8, le=400)
    items: list[DashboardItem] = Field(default_factory=list)


SECTION_MODELS: dict[str, type[BaseModel]] = {
    "app": AppLayout,
    "wizard": WizardLayout,
    "dashboard": DashboardLayout,
}


class LayoutIssue(BaseModel):
    """One problem with a layout section, addressed by layout name and item position."""

    model_config = ConfigDict(frozen=True)

    layout: str
    code: IssueCode
    message: str
    ref: str | None = None
    index: int | None = None


def _items_of(layout: BaseModel) -> Iterator[tuple[int, object]]:
    """Every item of a parsed section, numbered in document order."""
    index = 0
    if isinstance(layout, AppLayout | WizardLayout):
        groups: Iterable[AppSection | WizardStep] = (
            layout.sections if isinstance(layout, AppLayout) else layout.steps
        )
        for group in groups:
            for raw in group.items:
                yield index, raw
                index += 1
    elif isinstance(layout, DashboardLayout):
        for tile in layout.items:
            yield index, tile.ref
            index += 1


def parse_layout(name: str, section: object) -> tuple[BaseModel | None, LayoutIssue | None]:
    """Parse one section with its model; a malformed section yields a ``bad_layout`` issue."""
    model = SECTION_MODELS.get(name)
    if model is None or not isinstance(section, Mapping):
        return None, None
    try:
        return model.model_validate(section), None
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        message = f"{where}: {first['msg']}" if where else first["msg"]
        return None, LayoutIssue(layout=name, code="bad_layout", message=message)


def layout_issues(doc: WorkflowDoc) -> list[LayoutIssue]:
    """Every unresolvable ref in ``promoted``, ``views`` and the four layout sections.

    Params and ports are *not* checked against the node registry here -- the compiler already
    reports those per node (``unknown_param``, ``unknown_port``). This pass only answers "does
    this layout still describe things the document has?".
    """
    issues: list[LayoutIssue] = []
    promoted_refs = {p.ref for p in doc.promoted}
    view_ids: set[str] = set()

    for index, promoted in enumerate(doc.promoted):
        if promoted.node not in doc.nodes:
            issues.append(
                LayoutIssue(
                    layout="promoted",
                    code="unknown_node",
                    message=f"promoted param {promoted.ref!r} has no node {promoted.node!r}",
                    ref=promoted.ref,
                    index=index,
                )
            )
    for index, view in enumerate(doc.views):
        if view.id in view_ids:
            issues.append(
                LayoutIssue(
                    layout="views",
                    code="duplicate_view",
                    message=f"view id {view.id!r} is used more than once",
                    ref=view.id,
                    index=index,
                )
            )
        view_ids.add(view.id)
        if view.node not in doc.nodes:
            issues.append(
                LayoutIssue(
                    layout="views",
                    code="unknown_node",
                    message=f"view {view.id!r} has no node {view.node!r}",
                    ref=view.id,
                    index=index,
                )
            )

    for name in LAYOUT_NAMES:
        section = doc.layouts.get(name)
        if section is None:
            continue
        if name == "batch":
            issues.extend(_batch_issues(doc, section))
            continue
        parsed, bad = parse_layout(name, section)
        if bad is not None:
            issues.append(bad)
        if parsed is None:
            continue
        issues.extend(_item_issues(doc, name, parsed, promoted_refs, view_ids))
    return issues


def _item_issues(
    doc: WorkflowDoc,
    name: str,
    parsed: BaseModel,
    promoted_refs: set[str],
    view_ids: set[str],
) -> Iterator[LayoutIssue]:
    for index, raw in _items_of(parsed):
        item = parse_item(raw)
        if item is None:
            yield LayoutIssue(
                layout=name,
                code="bad_ref",
                message=f"{raw!r} is not a 'promoted:<node>.<param>' or 'view:<id>' ref",
                ref=raw if isinstance(raw, str) else None,
                index=index,
            )
        elif item.kind == "promoted" and item.ref not in promoted_refs:
            node, param = item.node_param
            detail = (
                f"node {node!r} is not in the document"
                if node not in doc.nodes
                else f"{param!r} is not promoted"
            )
            yield LayoutIssue(
                layout=name,
                code="unknown_promoted",
                message=f"{item.text}: {detail}",
                ref=item.ref,
                index=index,
            )
        elif item.kind == "view" and item.ref not in view_ids:
            yield LayoutIssue(
                layout=name,
                code="unknown_view",
                message=f"{item.text}: no such view",
                ref=item.ref,
                index=index,
            )


def _batch_issues(doc: WorkflowDoc, section: object) -> list[LayoutIssue]:
    """``layouts.batch`` refs, checked through the runner's own parser."""
    if not isinstance(section, Mapping):
        return []
    spec = spec_from_layout(section)
    out: list[LayoutIssue] = []
    for index, binding in enumerate(spec.bindings):
        if binding.node not in doc.nodes:
            out.append(
                LayoutIssue(
                    layout="batch",
                    code="unknown_node",
                    message=f"column {binding.column!r} binds missing node {binding.node!r}",
                    ref=binding.ref,
                    index=index,
                )
            )
    for index, collect in enumerate(spec.collect):
        if collect.node not in doc.nodes:
            out.append(
                LayoutIssue(
                    layout="batch",
                    code="unknown_node",
                    message=f"collect {collect.ref!r} has no node {collect.node!r}",
                    ref=collect.ref,
                    index=index,
                )
            )
    return out


__all__ = [
    "LAYOUT_NAMES",
    "PROMOTED_PREFIX",
    "VIEW_PREFIX",
    "AppLayout",
    "AppSection",
    "DashboardItem",
    "DashboardLayout",
    "ItemRef",
    "LayoutIssue",
    "LayoutName",
    "WizardLayout",
    "WizardStep",
    "layout_issues",
    "parse_item",
    "parse_layout",
]
