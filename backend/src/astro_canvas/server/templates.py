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
from pydantic import BaseModel, ValidationError

from astro_canvas.engine.graph import WorkflowDoc, new_id
from astro_canvas.sdk import NodeRegistry
from astro_canvas.server.runtime import EngineRuntime
from astro_canvas.server.workflows import WorkflowSaved

log = structlog.get_logger("astro_canvas.templates")
router = APIRouter(tags=["templates"])

TEMPLATE_SUFFIXES = (".acw", ".json")


class TemplateInfo(BaseModel):
    """A workflow template a pack ships (``GET /api/templates``)."""

    id: str
    name: str
    description: str = ""
    pack: str
    node_count: int = 0
    file: str
    readme: str | None = None


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
            info = TemplateInfo(
                id=f"{pack}.{path.stem}",
                name=doc.name,
                description=doc.description,
                pack=pack,
                node_count=len(doc.nodes),
                file=path.name,
                readme=_readme(path),
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


def get_runtime(request: Request) -> EngineRuntime:
    runtime: EngineRuntime = request.app.state.runtime
    return runtime


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
    saved = runtime.save(doc)
    return WorkflowSaved(doc=saved, node_errors=runtime.scheduler(saved.id).issues)
