"""``/api/templates``: workflow templates shipped by packs (``*.acw`` documents).

A pack declares a folder with ``registry.add_templates(path)``; every ``*.acw`` (or ``*.json``)
document in it becomes a template ``<pack>.<file stem>``. A sibling ``<stem>.md`` is served as the
template's README. Instantiating copies the document under a fresh workflow id.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from astro_canvas.engine.graph import WorkflowDoc, new_id
from astro_canvas.engine.layouts import LAYOUT_NAMES
from astro_canvas.sdk import NodeRegistry
from astro_canvas.server.deps import get_runtime
from astro_canvas.server.runtime import seed_samples
from astro_canvas.server.workflows import WorkflowSaved, saved_response

log = structlog.get_logger("astro_canvas.templates")
router = APIRouter(tags=["templates"])

TEMPLATE_SUFFIXES = (".acw", ".json")
FIGURE_SUFFIXES = (".png", ".webp", ".jpg")
"""Gallery figure shipped next to a template (``<stem>.png``); the card falls back without it."""

DEFAULT_LAYOUT_ORDER = ("wizard", "app", "dashboard", "batch")
"""Which layout a template opens into when ``meta.default_layout`` does not say."""


class TemplateInfo(BaseModel):
    """A workflow template a pack ships (``GET /api/templates``)."""

    id: str
    name: str
    description: str = ""
    pack: str
    node_count: int = 0
    file: str
    readme: str | None = None
    packs: dict[str, str] = Field(
        default_factory=dict, description="``requires.packs``: what must be installed."
    )
    tags: list[str] = Field(default_factory=list)
    layouts: list[str] = Field(
        default_factory=list, description="Layout sections the document carries."
    )
    default_layout: str = Field(
        default="canvas", description="The layout the gallery opens the template into."
    )
    figure: bool = False
    """Whether a gallery figure ships with the template (``GET /templates/{id}/figure``)."""


class InstantiateRequest(BaseModel):
    """Optional overrides when creating a workflow from a template."""

    name: str | None = None


@dataclass(frozen=True)
class Template:
    info: TemplateInfo
    path: Path


def _readme(path: Path) -> str | None:
    sidecar = path.with_suffix(".md")
    if sidecar.is_file():
        return sidecar.read_text(encoding="utf-8")
    return None


def figure_path(path: Path) -> Path | None:
    """The gallery image shipped beside a template document, if any."""
    for suffix in FIGURE_SUFFIXES:
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def default_layout(doc: WorkflowDoc) -> str:
    """``meta.default_layout`` when it names a section the document has, else the best one."""
    declared = doc.meta.get("default_layout")
    if isinstance(declared, str) and (declared == "canvas" or declared in doc.layouts):
        return declared
    for name in DEFAULT_LAYOUT_ORDER:
        if name in doc.layouts:
            return name
    return "canvas"


def list_templates(registry: NodeRegistry) -> list[Template]:
    """Every template of every pack, sorted by id; unreadable documents are logged and skipped."""
    out: list[Template] = []
    for pack, folder in sorted(registry.template_dirs.items()):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in TEMPLATE_SUFFIXES or not path.is_file():
                continue
            try:
                doc = WorkflowDoc.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, ValueError, OSError) as exc:
                log.warning("template skipped", pack=pack, file=path.name, error=str(exc))
                continue
            packs = doc.requires.get("packs") or {}
            tags = doc.meta.get("tags") or []
            info = TemplateInfo(
                id=f"{pack}.{path.stem}",
                name=doc.name,
                description=doc.description,
                pack=pack,
                node_count=len(doc.nodes),
                file=path.name,
                readme=_readme(path),
                packs={str(k): str(v) for k, v in packs.items()} if isinstance(packs, dict) else {},
                tags=[str(tag) for tag in tags] if isinstance(tags, list) else [],
                layouts=[name for name in LAYOUT_NAMES if name in doc.layouts],
                default_layout=default_layout(doc),
                figure=figure_path(path) is not None,
            )
            out.append(Template(info=info, path=path))
    return out


def find_template(registry: NodeRegistry, template_id: str) -> Template | None:
    for template in list_templates(registry):
        if template.info.id == template_id:
            return template
    return None


def instantiate(template: Template, *, name: str | None = None) -> WorkflowDoc:
    """A fresh copy of the template document: new id, cleared timestamps, provenance in ``meta``."""
    doc = WorkflowDoc.model_validate_json(template.path.read_text(encoding="utf-8"))
    meta = dict(doc.meta)
    meta.pop("created", None)
    meta.pop("modified", None)
    meta["template"] = template.info.id
    return doc.model_copy(update={"id": new_id(), "name": name or doc.name, "meta": meta})


def _not_found(template_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"unknown template {template_id!r}")


@router.get("/templates", response_model=list[TemplateInfo])
async def get_templates(request: Request) -> list[TemplateInfo]:
    """Templates shipped by the installed packs."""
    return [t.info for t in list_templates(get_runtime(request).registry)]


@router.get("/templates/{template_id}", response_model=WorkflowDoc)
async def get_template(request: Request, template_id: str) -> WorkflowDoc:
    """The template document itself (not stored; instantiate to get an editable workflow)."""
    template = find_template(get_runtime(request).registry, template_id)
    if template is None:
        raise _not_found(template_id)
    return WorkflowDoc.model_validate_json(template.path.read_text(encoding="utf-8"))


@router.post(
    "/templates/{template_id}/instantiate",
    response_model=WorkflowSaved,
    status_code=status.HTTP_201_CREATED,
)
async def instantiate_template(
    request: Request, template_id: str, body: InstantiateRequest | None = None
) -> WorkflowSaved:
    """Create a new workflow from the template (fresh id; ``meta.template`` records the origin)."""
    runtime = get_runtime(request)
    template = find_template(runtime.registry, template_id)
    if template is None:
        raise _not_found(template_id)
    doc = instantiate(template, name=body.name if body else None)
    # Templates point at bundled sample files; make sure this workspace has them (first use).
    copied = seed_samples(runtime.workspace, runtime.registry.sample_dirs)
    if copied:
        log.info("sample data copied", files=len(copied), template=template_id)
    saved = runtime.save(doc)
    return saved_response(runtime, saved)


@router.get("/templates/{template_id}/figure", response_model=None)
async def get_template_figure(request: Request, template_id: str) -> FileResponse:
    """The gallery card image a pack ships next to the template document."""
    template = find_template(get_runtime(request).registry, template_id)
    if template is None:
        raise _not_found(template_id)
    figure = figure_path(template.path)
    if figure is None:
        raise HTTPException(status_code=404, detail=f"template {template_id!r} has no figure")
    return FileResponse(figure)
