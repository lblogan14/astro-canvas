"""``.acw`` bundles: a workflow packed with everything needed to re-run and to judge it (§7.2).

```
workflow.json      the document, exactly as saved
lock.json          pack versions, python version, platform, app version, uv-exported freeze
inputs/refs.json   [{param_ref, path, blake3, bytes, mime, embedded, missing}]
inputs/<files>     embedded copies of the small ones
outputs/<ref>.*    finished node outputs (CSV / npz / JSON, never pickle)
figures/*.png      rendered previews, and figures/card.png for the gallery
provenance.json    per node: cache key, elapsed, state, pack versions at run time
trust.json         code-node hashes (decisions are NOT included - they are the importer's)
README.md          an auto-generated summary
```

Import is the security boundary: the archive is inspected before a byte is written (traversal,
zip bomb, pickle members), the document is validated, missing packs and unresolved layout refs
are reported rather than guessed at, input hashes are verified, and a workflow carrying code
nodes opens quarantined.
"""

from __future__ import annotations

import json
import platform
import sys
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, Field, ValidationError

from astro_canvas._version import __version__
from astro_canvas.engine.graph import NodeDoc, WorkflowDoc, new_id
from astro_canvas.engine.layouts import LayoutIssue, layout_issues
from astro_canvas.engine.scheduler import Scheduler
from astro_canvas.manager.archive import ArchiveError, inspect_zip
from astro_canvas.manager.trust import CodeSnippet, code_snippets
from astro_canvas.sdk import ANY_TYPE, NodeRegistry, PackRecord, UnknownNodeError
from astro_canvas.server.exports import render_export
from astro_canvas.store.files import guess_mime, hash_path
from astro_canvas.store.workspace import PathOutsideWorkspaceError, Workspace

log = structlog.get_logger("astro_canvas.bundles")

BUNDLE_SUFFIX = ".acw"
BUNDLES_DIR = "bundles"
WORKFLOW_MEMBER = "workflow.json"
LOCK_MEMBER = "lock.json"
REFS_MEMBER = "inputs/refs.json"
PROVENANCE_MEMBER = "provenance.json"
TRUST_MEMBER = "trust.json"
README_MEMBER = "README.md"
CARD_FIGURE = "figures/card.png"

FILE_WIDGETS: frozenset[str] = frozenset({"file", "path"})
"""Params rendered with a file picker hold workspace-relative paths worth carrying in a bundle."""

DEFAULT_EMBED_MB = 200
"""Design 7.2: embed input files below 200 MB by default; larger ones travel as a hash."""

OutputSelection = Literal["leaves", "all", "none"]


class BundleError(ValueError):
    """The bundle is not one, or is not safe to read."""


class InputRef(BaseModel):
    """One file a workflow reads, as ``inputs/refs.json`` records it."""

    param_ref: str = Field(description="``'<node>.<param>'`` that names the file.")
    path: str
    blake3: str | None = None
    bytes: int = 0
    mime: str | None = None
    embedded: bool = False
    missing: bool = Field(default=False, description="Not present in the exporting workspace.")


class BundleLock(BaseModel):
    """Exactly what ran, so an import can say whether this machine can reproduce it."""

    app_version: str = __version__
    python: str = Field(default_factory=platform.python_version)
    platform: str = Field(default_factory=lambda: f"{sys.platform}-{platform.machine()}")
    packs: dict[str, str] = Field(default_factory=dict)
    requirements: list[str] = Field(default_factory=list)
    created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NodeProvenance(BaseModel):
    """One node's run record."""

    node: str
    type: str
    version: str = ""
    key: str = ""
    state: str = "idle"
    elapsed_ms: float | None = None
    cache_hit: bool = False
    pack: str | None = None


class BundleManifest(BaseModel):
    """What ``export_bundle`` wrote (also what ``inspect_bundle`` reads back)."""

    workflow_id: str
    name: str
    path: str = Field(default="", description="Workspace-relative path of the ``.acw``.")
    bytes: int = 0
    lock: BundleLock = Field(default_factory=BundleLock)
    inputs: list[InputRef] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)
    skipped_outputs: list[str] = Field(default_factory=list)
    code_hashes: list[str] = Field(default_factory=list)


class ImportedInput(BaseModel):
    """An input file as the import found it in *this* workspace."""

    param_ref: str
    path: str
    status: Literal["ok", "restored", "missing", "hash_mismatch"] = "ok"
    expected_blake3: str | None = None
    actual_blake3: str | None = None


class BundleImportResult(BaseModel):
    """``POST /api/bundles/import``: what was opened and what the user still has to fix."""

    workflow_id: str
    name: str
    lock: BundleLock = Field(default_factory=BundleLock)
    missing_packs: dict[str, str] = Field(
        default_factory=dict, description="``requires.packs`` entries not installed here."
    )
    layout_errors: list[LayoutIssue] = Field(default_factory=list)
    inputs: list[ImportedInput] = Field(default_factory=list)
    outputs_restored: int = 0
    quarantined: bool = False
    snippets: list[CodeSnippet] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def missing_inputs(self) -> list[ImportedInput]:
        return [i for i in self.inputs if i.status == "missing"]


# --- helpers ------------------------------------------------------------------------------------


def file_params(doc: WorkflowDoc, registry: NodeRegistry) -> list[tuple[str, str, str]]:
    """``(node id, param, value)`` for every file-picker param with a non-empty value.

    Subgraph bodies are walked too, so a template that hides its loader inside a subgraph still
    exports its inputs.
    """
    out: list[tuple[str, str, str]] = []
    containers: list[tuple[str, Mapping[str, NodeDoc]]] = [("", doc.nodes)]
    for sg_id, sg in doc.subgraphs.items():
        containers.append((f"{sg_id}/", sg.nodes))
    for prefix, nodes in containers:
        for node_id, node in nodes.items():
            try:
                spec = registry.spec(node.type)
            except UnknownNodeError:
                continue
            for param in spec.params:
                if (param.widget or "") not in FILE_WIDGETS:
                    continue
                value = node.params.get(param.name)
                if isinstance(value, str) and value.strip():
                    out.append((f"{prefix}{node_id}", param.name, value.strip()))
    return sorted(out)


def leaf_refs(scheduler: Scheduler) -> list[str]:
    """``'<node>.<port>'`` for outputs nothing else consumes -- a workflow's results."""
    graph = scheduler.graph
    out: list[str] = []
    for node_id in graph.order:
        consumed = {
            port
            for consumer in graph.consumers(node_id)
            for src, port in graph.nodes[consumer].inputs.values()
            if src == node_id
        }
        for port in scheduler.output_ports(node_id):
            if port not in consumed:
                out.append(f"{node_id}.{port}")
    return out


def all_refs(scheduler: Scheduler) -> list[str]:
    return [
        f"{node_id}.{port}"
        for node_id in scheduler.graph.order
        for port in scheduler.output_ports(node_id)
    ]


def _lock(packs: Iterable[PackRecord], requirements: list[str]) -> BundleLock:
    return BundleLock(
        packs={p.distribution or p.name: p.version for p in packs},
        requirements=sorted(requirements),
    )


def _readme(doc: WorkflowDoc, manifest: BundleManifest) -> str:
    """A human summary so the zip is readable without the app."""
    lines = [
        f"# {doc.name}",
        "",
        doc.description or "_No description._",
        "",
        f"Exported by Astro Canvas {manifest.lock.app_version} on {manifest.lock.created}.",
        "",
        "## Contents",
        "",
        f"- {len(doc.nodes)} nodes, {len(doc.edges)} edges",
        f"- {len(manifest.inputs)} input files "
        f"({sum(1 for i in manifest.inputs if i.embedded)} embedded)",
        f"- {len(manifest.outputs)} exported outputs",
        f"- layouts: {', '.join(sorted(doc.layouts)) or 'none (canvas only)'}",
        "",
        "## Requires",
        "",
    ]
    packs = doc.requires.get("packs") or {}
    if isinstance(packs, dict) and packs:
        lines += [f"- `{name}` {spec}" for name, spec in sorted(packs.items())]
    else:
        lines.append("- no pack constraints recorded")
    lines += ["", "## Locked versions", ""]
    lines += [f"- `{name}` {version}" for name, version in sorted(manifest.lock.packs.items())]
    if manifest.code_hashes:
        lines += [
            "",
            "## Code nodes",
            "",
            f"This bundle contains {len(manifest.code_hashes)} Python snippet(s). Astro Canvas "
            "opens it quarantined: review each snippet and trust it before it will run.",
        ]
    return "\n".join(lines) + "\n"


# --- export -------------------------------------------------------------------------------------


@dataclass
class ExportOptions:
    """Knobs of ``POST /api/bundles/export``."""

    embed_inputs_max_mb: int = DEFAULT_EMBED_MB
    include_outputs: OutputSelection = "leaves"
    include_figures: bool = True


def export_bundle(
    doc: WorkflowDoc,
    scheduler: Scheduler,
    workspace: Workspace,
    registry: NodeRegistry,
    packs: Iterable[PackRecord],
    *,
    target: Path,
    options: ExportOptions | None = None,
    requirements: list[str] | None = None,
) -> BundleManifest:
    """Write ``doc`` and its evidence to ``target`` as a ``.acw`` zip.

    Outputs that cannot be serialised are skipped rather than fatal -- an ``astro.Any`` value has
    no file form at all and design 7.2 says it must be dropped, not embedded.
    """
    opts = options or ExportOptions()
    lock = _lock(packs, requirements or [])
    manifest = BundleManifest(workflow_id=doc.id, name=doc.name, lock=lock)
    limit = max(opts.embed_inputs_max_mb, 0) * 1024 * 1024
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(WORKFLOW_MEMBER, doc.model_dump_json(by_alias=True, indent=2))
        _write_inputs(zf, doc, workspace, registry, manifest, limit)
        _write_outputs(zf, scheduler, manifest, opts.include_outputs)
        if opts.include_figures:
            _write_figures(zf, doc, scheduler, manifest)
        snippets = code_snippets(doc)
        manifest.code_hashes = [s.hash for s in snippets]
        zf.writestr(
            TRUST_MEMBER,
            json.dumps(
                {
                    "snippets": [
                        {"node": s.node, "hash": s.hash, "lines": s.lines} for s in snippets
                    ]
                },
                indent=2,
            ),
        )
        zf.writestr(PROVENANCE_MEMBER, _provenance(doc, scheduler, registry))
        zf.writestr(LOCK_MEMBER, lock.model_dump_json(indent=2))
        zf.writestr(README_MEMBER, _readme(doc, manifest))
    manifest.bytes = target.stat().st_size
    try:
        manifest.path = workspace.relative(target)
    except ValueError:  # pragma: no cover - a target outside the workspace (CLI use)
        manifest.path = str(target)
    log.info("bundle exported", workflow=doc.id, path=manifest.path, bytes=manifest.bytes)
    return manifest


def _write_inputs(
    zf: zipfile.ZipFile,
    doc: WorkflowDoc,
    workspace: Workspace,
    registry: NodeRegistry,
    manifest: BundleManifest,
    limit: int,
) -> None:
    for node_id, param, value in file_params(doc, registry):
        ref = InputRef(param_ref=f"{node_id}.{param}", path=value, mime=guess_mime(value))
        try:
            source = workspace.safe_path(value)
        except PathOutsideWorkspaceError:
            ref.missing = True
            manifest.inputs.append(ref)
            continue
        if not source.is_file():
            ref.missing = True
            manifest.inputs.append(ref)
            continue
        ref.bytes = source.stat().st_size
        ref.blake3 = hash_path(source)
        if ref.bytes <= limit:
            zf.write(source, f"inputs/{value.lstrip('/')}")
            ref.embedded = True
        manifest.inputs.append(ref)
    zf.writestr(
        REFS_MEMBER, json.dumps([i.model_dump(mode="json") for i in manifest.inputs], indent=2)
    )


def _write_outputs(
    zf: zipfile.ZipFile, scheduler: Scheduler, manifest: BundleManifest, selection: OutputSelection
) -> None:
    if selection == "none":
        return
    refs = leaf_refs(scheduler) if selection == "leaves" else all_refs(scheduler)
    for ref in refs:
        node_id, _, port = ref.rpartition(".")
        value = scheduler.output(node_id, port)
        if value is None:
            continue
        if value.type_id() == ANY_TYPE:
            # design 7.2: an in-process object has no file form; it never leaves the machine.
            manifest.skipped_outputs.append(ref)
            continue
        try:
            fmt, payload = render_export(value)
        except Exception as exc:  # noqa: BLE001 - one bad value must not fail the export
            log.warning("output not bundled", ref=ref, error=str(exc))
            manifest.skipped_outputs.append(ref)
            continue
        name = f"outputs/{node_id.replace('/', '-')}.{port}.{fmt}"
        zf.writestr(name, payload)
        manifest.outputs.append(ref)


def _write_figures(
    zf: zipfile.ZipFile, doc: WorkflowDoc, scheduler: Scheduler, manifest: BundleManifest
) -> None:
    """Render the pinned views and the leaf outputs as PNGs; the first one becomes the card."""
    from astro_canvas.manager.figures import render_summary_png  # noqa: PLC0415 - only on export

    seen: set[str] = set()
    wanted: list[tuple[str, str]] = []
    for name, ref in [(v.id, f"{v.node}.{v.port}") for v in doc.views] + [
        (ref.replace("/", "-"), ref) for ref in leaf_refs(scheduler)[:4]
    ]:
        if ref not in seen:
            seen.add(ref)
            wanted.append((name, ref))
    first: bytes | None = None
    for name, ref in wanted:
        node_id, _, port = ref.rpartition(".")
        value = scheduler.output(node_id, port)
        if value is None:
            continue
        try:
            png = render_summary_png(value, title=name)
        except Exception as exc:  # noqa: BLE001 - a figure is a nicety, never a failure
            log.warning("figure not rendered", ref=ref, error=str(exc))
            continue
        if png is None:
            continue
        member = f"figures/{name}.png"
        zf.writestr(member, png)
        manifest.figures.append(member)
        first = first or png
    if first is not None:
        zf.writestr(CARD_FIGURE, first)
        manifest.figures.append(CARD_FIGURE)


def _provenance(doc: WorkflowDoc, scheduler: Scheduler, registry: NodeRegistry) -> str:
    records: list[NodeProvenance] = []
    for node_id in scheduler.graph.order:
        node = scheduler.graph.nodes[node_id]
        rec = scheduler.records.get(node_id)
        try:
            pack = registry.spec(node.type).pack
        except UnknownNodeError:  # pragma: no cover - the graph compiled, so the type exists
            pack = None
        records.append(
            NodeProvenance(
                node=node_id,
                type=node.type,
                version=node.version,
                key=rec.key if rec else "",
                state=rec.state if rec else "idle",
                elapsed_ms=rec.elapsed_ms if rec else None,
                cache_hit=bool(rec and rec.cache_hit),
                pack=pack,
            )
        )
    body = {
        "workflow_id": doc.id,
        "name": doc.name,
        "nodes": [r.model_dump(mode="json") for r in records],
    }
    return json.dumps(body, indent=2)


# --- import -------------------------------------------------------------------------------------


@dataclass
class BundleContents:
    """A validated, in-memory view of a ``.acw``. Nothing has been written to disk yet."""

    doc: WorkflowDoc
    lock: BundleLock
    refs: list[InputRef]
    members: tuple[str, ...]
    payload: bytes

    def read(self, member: str) -> bytes:
        with zipfile.ZipFile(BytesIO(self.payload)) as zf:
            return zf.read(member)


def read_document(data: bytes) -> WorkflowDoc:
    """A workflow from either bundle shape: a ``.acw`` zip, or a bare JSON document.

    Pack templates ship ``.acw`` files that are plain documents (phase 05); a bundle exported by
    this module is a zip. Both open.
    """
    if data[:2] == b"PK":
        with zipfile.ZipFile(BytesIO(data)) as zf:
            inspect_zip(zf)
            names = set(zf.namelist())
            if WORKFLOW_MEMBER not in names:
                raise BundleError(f"the archive has no {WORKFLOW_MEMBER}")
            data = zf.read(WORKFLOW_MEMBER)
    try:
        return WorkflowDoc.model_validate_json(data)
    except ValidationError as exc:
        raise BundleError(f"not an Astro Canvas workflow: {exc.error_count()} problems") from exc
    except ValueError as exc:
        raise BundleError(f"not an Astro Canvas workflow: {exc}") from exc


def open_bundle(data: bytes) -> BundleContents:
    """Validate an uploaded ``.acw`` and read its metadata without extracting anything.

    Raises:
        BundleError: when the archive is unsafe (traversal, bomb, pickle) or is not a bundle.
    """
    if data[:2] != b"PK":
        return BundleContents(
            doc=read_document(data), lock=BundleLock(), refs=[], members=(), payload=data
        )
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            info = inspect_zip(zf)
            names = set(info.names)
            if WORKFLOW_MEMBER not in names:
                raise BundleError(f"the archive has no {WORKFLOW_MEMBER}")
            doc = read_document(zf.read(WORKFLOW_MEMBER))
            lock = BundleLock()
            if LOCK_MEMBER in names:
                try:
                    lock = BundleLock.model_validate_json(zf.read(LOCK_MEMBER))
                except ValueError as exc:
                    log.warning("bundle lock unreadable", error=str(exc))
            refs: list[InputRef] = []
            if REFS_MEMBER in names:
                try:
                    raw = json.loads(zf.read(REFS_MEMBER))
                    refs = [InputRef.model_validate(item) for item in raw]
                except (ValueError, ValidationError) as exc:
                    log.warning("bundle refs unreadable", error=str(exc))
    except ArchiveError as exc:
        raise BundleError(str(exc)) from exc
    except zipfile.BadZipFile as exc:
        raise BundleError("the file is not a readable zip archive") from exc
    return BundleContents(doc=doc, lock=lock, refs=refs, members=tuple(sorted(names)), payload=data)


def missing_packs(doc: WorkflowDoc, packs: Iterable[PackRecord]) -> dict[str, str]:
    """``requires.packs`` entries with no matching installed distribution or pack name."""
    required = doc.requires.get("packs")
    if not isinstance(required, Mapping):
        return {}
    have = {p.name for p in packs} | {p.distribution for p in packs if p.distribution}
    return {str(k): str(v) for k, v in required.items() if str(k) not in have}


def restore_inputs(
    contents: BundleContents, workspace: Workspace, *, into: str
) -> list[ImportedInput]:
    """Put the embedded input files back and report what is missing or has changed.

    A file already present in this workspace is left alone: the importer's copy wins, and a
    content difference is reported as ``hash_mismatch`` rather than silently overwritten.
    """
    out: list[ImportedInput] = []
    members = set(contents.members)
    for ref in contents.refs:
        entry = ImportedInput(param_ref=ref.param_ref, path=ref.path, expected_blake3=ref.blake3)
        try:
            existing = workspace.safe_path(ref.path)
        except PathOutsideWorkspaceError:
            entry.status = "missing"
            out.append(entry)
            continue
        if existing.is_file():
            entry.actual_blake3 = hash_path(existing)
            if ref.blake3 and entry.actual_blake3 != ref.blake3:
                entry.status = "hash_mismatch"
            out.append(entry)
            continue
        member = f"inputs/{ref.path.lstrip('/')}"
        if member not in members:
            entry.status = "missing"
            out.append(entry)
            continue
        target = workspace.safe_path(f"{into}/{ref.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents.read(member))
        entry.status = "restored"
        entry.path = workspace.relative(target)
        entry.actual_blake3 = hash_path(target)
        out.append(entry)
    return out


def rewrite_input_paths(doc: WorkflowDoc, inputs: Iterable[ImportedInput]) -> WorkflowDoc:
    """Point the document's file params at where the restored copies actually landed."""
    moved = {i.param_ref: i.path for i in inputs if i.status == "restored"}
    if not moved:
        return doc
    nodes = dict(doc.nodes)
    for ref, path in moved.items():
        node_id, _, param = ref.rpartition(".")
        node = nodes.get(node_id)
        if node is None:
            continue  # a subgraph body: the ref keeps the exported path
        nodes[node_id] = node.model_copy(update={"params": {**node.params, param: path}})
    return doc.model_copy(update={"nodes": nodes})


def prepare_import(
    contents: BundleContents,
    workspace: Workspace,
    registry: NodeRegistry,
    packs: Iterable[PackRecord],
    *,
    restore_into: str = "imports",
    keep_id: bool = False,
) -> tuple[WorkflowDoc, BundleImportResult]:
    """Turn validated bundle contents into a document ready to save, plus what the user must fix.

    The workflow gets a fresh id (node ids are untouched, so every layout ref still resolves) and
    ``meta.quarantine`` is set when it carries code, which is what makes the trust gate close.
    """
    doc = contents.doc
    inputs = restore_inputs(contents, workspace, into=restore_into)
    doc = rewrite_input_paths(doc, inputs)
    snippets = code_snippets(doc)
    meta = {**doc.meta, "imported": datetime.now(timezone.utc).isoformat()}
    meta.pop("modified", None)
    if snippets:
        meta["quarantine"] = True
    doc = doc.model_copy(update={"id": doc.id if keep_id else new_id(), "meta": meta})
    result = BundleImportResult(
        workflow_id=doc.id,
        name=doc.name,
        lock=contents.lock,
        missing_packs=missing_packs(doc, packs),
        layout_errors=layout_issues(doc),
        inputs=inputs,
        quarantined=bool(snippets),
        snippets=snippets,
    )
    if result.missing_packs:
        result.warnings.append(
            "install the missing packs from Manager > Registry, then reopen this workflow"
        )
    if any(i.status == "hash_mismatch" for i in result.inputs):
        result.warnings.append(
            "an input file in this workspace differs from the one the bundle was made with"
        )
    unknown = sorted(
        {n.type for n in doc.nodes.values() if n.type not in registry and ":" not in n.type}
    )
    if unknown:
        result.warnings.append(f"unknown node types: {', '.join(unknown)}")
    return doc, result


def bundle_name(name: str, workflow_id: str) -> str:
    from astro_canvas.server.exports import slug  # noqa: PLC0415 - shared slug rules

    return f"{slug(name, workflow_id)}{BUNDLE_SUFFIX}"


def bundle_target(workspace: Workspace, doc: WorkflowDoc, folder: str | None = None) -> Path:
    relative = f"{folder or BUNDLES_DIR}/{bundle_name(doc.name, doc.id)}"
    return workspace.safe_path(relative)


__all__ = [
    "BUNDLES_DIR",
    "BUNDLE_SUFFIX",
    "BundleContents",
    "BundleError",
    "BundleImportResult",
    "BundleLock",
    "BundleManifest",
    "ExportOptions",
    "ImportedInput",
    "InputRef",
    "NodeProvenance",
    "OutputSelection",
    "bundle_target",
    "export_bundle",
    "file_params",
    "leaf_refs",
    "missing_packs",
    "open_bundle",
    "prepare_import",
    "read_document",
    "restore_inputs",
]
