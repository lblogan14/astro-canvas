# Bundle format (`.acw`) and the manager API

A bundle is a zip carrying one workflow and everything needed to re-run and to judge it (design
§7.2). The user-facing side is [the bundles guide](../guide/bundles.md); this page is the
contract. The machine-readable REST contract is
`backend/src/astro_canvas/server/openapi/openapi.json` (regenerate with `task api:gen`).

## Layout

```
workflow.json      the document, byte-for-byte what `GET /api/workflows/{id}` returns
lock.json          BundleLock
inputs/refs.json   InputRef[]
inputs/<path>      embedded input files, at their workspace-relative paths
outputs/<node>.<port>.{csv,npz,json}
figures/<view id>.png, figures/card.png
provenance.json    {workflow_id, name, nodes: NodeProvenance[]}
trust.json         {snippets: [{node, hash, lines}]}
README.md          generated summary
```

`workflow.json` is the only required member. A bare `workflow.json` file **also** opens as a
bundle, which is how pack templates ship (`.acw` files that are plain documents, phase 05).

```jsonc
// lock.json
{ "app_version": "0.1.0", "python": "3.12.7", "platform": "win32-AMD64",
  "packs": {"astro-canvas-core": "0.1.0", "astro-canvas-rbcodes": "0.1.0"},
  "requirements": ["numpy==2.5.2", "..."],       // uv pip freeze at export time
  "created": "2026-09-04T05:39:18+00:00" }

// inputs/refs.json
[ { "param_ref": "load.path",                    // "<node>.<param>", a file-picker param
    "path": "samples/rbcodes/sdss1.fits",
    "blake3": "…64 hex…", "bytes": 519840, "mime": "application/fits",
    "embedded": true, "missing": false } ]

// provenance.json
{ "workflow_id": "…", "name": "…",
  "nodes": [ { "node": "ew", "type": "rbcodes.absorption.compute_ew", "version": "1.0.0",
               "key": "…blake3 cache key…", "state": "done", "elapsed_ms": 41.2,
               "cache_hit": false, "pack": "rbcodes" } ] }
```

Two exclusions are part of the format, not an implementation detail:

- **`astro.Any` outputs are dropped.** They are in-process Python objects with no file form; the
  manifest lists them under `skipped_outputs`.
- **Pickle is never written and never read.** A member with a pickle-shaped suffix (`.pkl`,
  `.pickle`, `.pt`, `.joblib`, `.dill`, `.marshal`) makes the archive invalid.

## Import safety

Every archive is inspected in memory before a byte is written (`manager/archive.py`):

| Rule | Limit |
|---|---|
| Entry names | no absolute paths, no drive prefixes, no `..` segment, no symlink members |
| Entry count | 4096 |
| Total uncompressed size | 4 GiB |
| Compression ratio | 200× |
| Forbidden suffixes | the pickle family above |
| Upload size | 2 GiB (`POST /api/bundles/import`) |

An import gives the workflow a **fresh id** and keeps every **node id**, because `promoted`,
`views` and the layout sections address nodes; renaming them would break every layout. The same
`layout_issues()` validator `POST /workflows` uses reports unresolvable refs, under
`layout_errors`.

## The trust gate

A code node is any node whose type is in `CODE_NODE_TYPES` (`core.code.python`); its `source`
param is hashed with blake3 after normalising line endings. Decisions live in the workspace's
`trust` table keyed by that hash — never by node or by workflow.

An imported document is marked `meta.quarantine: true`. While it is quarantined, every code node
whose hash has no `trusted` decision compiles to a `quarantined` node issue, which keeps it and
everything downstream out of the executable graph:

```jsonc
{ "code": "quarantined", "message": "review and trust this code snippet before it can run" }
```

Saving a document that is *not* quarantined trusts its snippets (locally authored code needs no
dialog); saving one that is drops the flag once every snippet has a decision.

## Dynamic ports

`core.code.python` declares its ports in two of its own params. Its `NodeSpec` carries:

```jsonc
"dynamic_ports": { "inputs": "inputs", "outputs": "outputs", "values": "values" }
```

meaning: the `inputs` param holds the input port declarations, `outputs` the output ones, and the
node function receives the port values in its `values` parameter. Each declaration is
`{"name": "spec", "type": "astro.Spectrum1D"}`; a name must be a Python identifier and malformed
or duplicate entries are dropped.

`astro_canvas.sdk.ports.effective_ports(spec, params)` is the single definition of what ports an
instance has; `frontend/src/nodes/dynamicPorts.ts` mirrors it so the canvas draws — and
validates — the same ports the compiler wires.

## REST

### Bundles

| Route | Body / query | Returns |
|---|---|---|
| `POST /api/bundles/export` | `{workflow_id, embed_inputs_max_mb=200, include_outputs="leaves"\|"all"\|"none", include_figures=true, dir?}` | `BundleManifest` |
| `GET /api/bundles/download` | `?path=<workspace-relative>` | the file |
| `POST /api/bundles/import` | multipart `file`, `restore_into="imports"`, `open_now=true` | `BundleImportResult` |

`BundleImportResult` carries `workflow_id`, `lock`, `missing_packs`, `layout_errors`, `inputs`
(each `ok` / `restored` / `missing` / `hash_mismatch`), `quarantined`, `snippets` and `warnings`.

### Manager

| Route | Purpose |
|---|---|
| `GET /api/manager/status` | uv path and version, target interpreter, settings, `restart_required` |
| `POST /api/manager/settings` | security level, uv path, registry URL (per workspace) |
| `GET /api/manager/packs` | every discovered pack with its DB state and load error |
| `POST /api/manager/packs/resolve` | `{source, action}` → `InstallPlan` (the dry run) |
| `POST /api/manager/packs/install` | `{source, confirm: true}` → `InstallResult` |
| `POST /api/manager/packs/{name}/update`, `DELETE /api/manager/packs/{name}` | `InstallResult` |
| `POST /api/manager/packs/{name}/enabled` | `{enabled}` → `PackDetail` |
| `POST /api/manager/packs/{name}/import-test` | import the pack in a subprocess |
| `GET/POST /api/manager/snapshots`, `GET /api/manager/snapshots/{id}`, `POST …/rollback` | freeze snapshots |
| `GET /api/manager/registry` | `?refresh&q&category` → the cached index |
| `GET/POST /api/manager/trust`, `DELETE /api/manager/trust/{hash}` | snippet decisions |
| `GET /api/workflows/{id}/trust` | `TrustReview` for the banner and the dialog |

Every environment change is two calls: `resolve` returns the plan the dialog shows, and only a
plan with `ok: true` may be confirmed. `install` is refused without `confirm: true`.

`InstallPlan` is `{source, action, changes: [{name, action, from_version, to_version}], conflicts,
ok, message, output}` where `action` is `add | upgrade | downgrade | remove | reinstall`.
`conflicts` holds the resolver's explanation, unwrapped into one paragraph; `output` is the raw
uv text the dialog shows under *uv output*.

### Events

`packs.changed {event}` is broadcast (`workflow_id: "*"`) after an install, an enable/disable, an
uninstall or a rollback. The client refreshes the Manager and reloads `/api/nodes`, so a change
made in one tab lands in every other one.
