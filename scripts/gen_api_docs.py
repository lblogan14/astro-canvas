"""Generate `docs/api.md` from the OpenAPI snapshot.

The live server serves Swagger UI at `/api/docs`, which is the right tool when you have a server.
The published documentation has no server, so the same contract is rendered as a page: every
endpoint grouped by tag, with its parameters, its bodies and the schema names they resolve to.

Run through ``task api:gen`` (which also refreshes the snapshot and the typed frontend client);
``--check`` fails when the page is stale, which is what CI runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "backend" / "src" / "astro_canvas" / "server" / "openapi" / "openapi.json"
PAGE = ROOT / "docs" / "api.md"

METHODS = ("get", "post", "put", "patch", "delete")

#: Tag -> the sentence that says what the group is for. A tag with no entry still renders.
BLURBS = {
    "system": "Health and system information. `/api/health` is the one route that needs no token.",
    "auth": "Login, logout and registration on a `--auth users` server (design 12). Public.",
    "users": "The signed-in account, and user administration for a superuser.",
    "nodes": "The node and port-type schemas the UI builds itself from, and the discovered packs.",
    "workflows": "Documents: CRUD, version history, the per-node status snapshot and the engine "
    "switches for one workflow.",
    "runs": "Starting, inspecting and cancelling a run.",
    "outputs": "A finished node's full output, as msgpack, Arrow, JSON or npz.",
    "batch": "Running a workflow over a table of rows.",
    "templates": "Workflow templates shipped by packs, and instantiating one.",
    "bundles": "Exporting and importing `.acw` bundles.",
    "trust": "The code node's trust gate: what is quarantined, and deciding about it.",
    "manager": "The pack manager. Admin-only on a shared server, and absent when "
    "`ASTRO_CANVAS_MANAGER=false`.",
    "workspace": "The workspace folder: listing, reading, writing, uploading and switching.",
}

HEADER = """# API reference

Every endpoint of the app's HTTP API, generated from the OpenAPI snapshot at
`backend/src/astro_canvas/server/openapi/openapi.json` — run `task api:gen` to refresh both.

A running server serves the same contract interactively at
[`/api/docs`](http://127.0.0.1:8765/api/docs) (Swagger UI) and as raw JSON at
`/api/openapi.json`. Those two, plus `/api/health`, are the only routes that do **not** need a
token.

## Authentication

Everything else needs a bearer token:

```sh
curl -H "Authorization: Bearer $(cat ~/.config/AstroCanvas/token)" \\
     http://127.0.0.1:8765/api/nodes
```

The token is printed at startup, written to `<config>/token`, and settable with
`ASTRO_CANVAS_TOKEN`. On a `--auth users` server the same JWT works as a bearer token for
scripts, and browsers use the httpOnly cookie the login sets instead — see
[server deployment](deploy/server.md).

`/ws` carries the live event protocol (JSON events plus binary frames for full arrays). OpenAPI
does not describe WebSockets, so it is documented in
[the workflow format](formats/workflow.md#websocket-wstoken-client_id) instead.

## Errors

Anything the server generates itself answers with:

```json
{ "detail": "FileNotFoundError: no such file: 'spectrum.fits'",
  "hint": "That file is not in the workspace any more. Pick it again in the Workspace panel.",
  "request_id": "2e0efcd35e4e" }
```

`hint` is the same one-line advice a failing node carries, and `request_id` matches the traceback
in the server log. FastAPI's own request-validation failures keep their `detail` array shape.
"""


def resolve(ref: str) -> str:
    """`#/components/schemas/WorkflowDoc` -> `WorkflowDoc`."""
    return ref.rsplit("/", 1)[-1]


def type_of(schema: dict[str, Any]) -> str:
    """A short human type for a schema node: a schema name, `T[]`, or a JSON type."""
    if "$ref" in schema:
        return f"`{resolve(schema['$ref'])}`"
    if schema.get("type") == "array":
        return f"{type_of(schema.get('items', {}))}[]"
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts = [type_of(part) for part in schema[key] if part.get("type") != "null"]
            joined = " or ".join(dict.fromkeys(parts))
            return f"{joined} or null" if len(parts) < len(schema[key]) else joined
    if "enum" in schema:
        return " | ".join(f"`{value}`" for value in schema["enum"])
    kind = schema.get("type")
    return f"`{kind}`" if kind else "`any`"


def body_type(operation: dict[str, Any], key: str, status: str = "") -> str:
    """The `application/json` (or other) schema of a request or response body."""
    holder = operation.get(key) or {}
    if status:
        holder = holder.get(status) or holder.get("200") or holder.get("201") or {}
    content = holder.get("content") or {}
    for media in ("application/json", "application/octet-stream", "text/plain"):
        if media in content:
            schema = content[media].get("schema") or {}
            return type_of(schema) if schema else f"`{media}`"
    if content:
        media = next(iter(content))
        return f"`{media}`"
    return ""


def success(operation: dict[str, Any]) -> tuple[str, str]:
    """`(status, type)` of the first 2xx response."""
    for status, response in (operation.get("responses") or {}).items():
        if status.startswith("2"):
            return status, body_type({"r": {status: response}}, "r", status)
    return "", ""


def render(spec: dict[str, Any]) -> str:
    grouped: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, operations in spec["paths"].items():
        for method in METHODS:
            operation = operations.get(method)
            if operation is None:
                continue
            for tag in operation.get("tags") or ["untagged"]:
                grouped.setdefault(tag, []).append((method, path, operation))

    out = [HEADER, ""]
    for tag in sorted(grouped):
        out.append(f"## `{tag}`")
        out.append("")
        blurb = BLURBS.get(tag)
        if blurb:
            out.extend([blurb, ""])
        out.append("| | Endpoint | What it does |")
        out.append("|---|---|---|")
        for method, path, operation in sorted(grouped[tag], key=lambda row: (row[1], row[0])):
            summary = (operation.get("summary") or "").strip()
            out.append(f"| `{method.upper()}` | `{path}` | {summary} |")
        out.append("")

        for method, path, operation in sorted(grouped[tag], key=lambda row: (row[1], row[0])):
            out.append(f"### `{method.upper()} {path}`")
            out.append("")
            description = (operation.get("description") or "").strip()
            if description:
                out.extend([description, ""])
            rows: list[str] = []
            for parameter in operation.get("parameters") or []:
                where = parameter.get("in", "")
                required = " (required)" if parameter.get("required") else ""
                doc = (parameter.get("description") or "").strip().replace("\n", " ")
                kind = type_of(parameter.get("schema") or {})
                rows.append(f"| `{parameter['name']}` | {where}{required} | {kind} | {doc} |")
            if rows:
                out.append("| Parameter | In | Type | Notes |")
                out.append("|---|---|---|---|")
                out.extend(rows)
                out.append("")
            request = body_type(operation, "requestBody")
            status, response = success(operation)
            if request:
                out.append(f"**Body** {request}")
                out.append("")
            if response or status:
                out.append(f"**Returns** `{status}`{f' {response}' if response else ''}")
                out.append("")

    out.append("## Schemas")
    out.append("")
    out.append(
        "The request and response models above are pydantic models on the server and generated "
        "TypeScript in `frontend/src/api/schema.d.ts`. The ones worth reading in prose are "
        "documented in [the node schema](formats/node-schema.md) (`NodeSpec`, `ParamSpec`, "
        "`PortTypeSpec`, `PackRecord`), [the workflow format](formats/workflow.md) "
        "(`WorkflowDoc` and everything under it) and [the bundle format](formats/bundle.md). For "
        "the rest, the JSON Schema in the snapshot is the reference:"
    )
    out.append("")
    names = sorted(spec.get("components", {}).get("schemas", {}))
    out.append(", ".join(f"`{name}`" for name in names) + ".")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the page is out of date")
    args = parser.parse_args()

    spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    page = render(spec)
    if args.check:
        current = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
        if current != page:
            print(f"{PAGE.relative_to(ROOT)} is out of date - run `task api:gen`", file=sys.stderr)
            return 1
        print(f"ok: {PAGE.relative_to(ROOT)} matches the OpenAPI snapshot")
        return 0
    PAGE.write_text(page, encoding="utf-8")
    print(f"wrote {PAGE.relative_to(ROOT)} ({len(spec['paths'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
