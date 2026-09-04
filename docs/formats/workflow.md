# Workflow document, execution API and events

The canvas document is `workflow.json` (format `astro-canvas/workflow`, version 1). The
execution engine compiles it into a DAG of node calls, caches every output by content hash,
and streams progress over a WebSocket. This page is the contract phase 03 (canvas) builds on.
The machine-readable REST contract is `backend/src/astro_canvas/server/openapi/openapi.json`
(regenerate with `task api:gen`, which also rebuilds `frontend/src/api/schema.d.ts`).

## `workflow.json` (format version 1)

```jsonc
{
  "format": "astro-canvas/workflow", "version": 1,
  "id": "0192f7c1…", "name": "Absorption Line Measurement", "description": "…",
  "nodes": {
    "n1": { "type": "core.spec.crop", "version": null, "title": "Crop",
            "pos": [120, 80], "size": [280, 200],
            "params": {"lo": 1200, "hi": 1300},
            "linked": ["hi"],                 // params converted to input ports
            "ui": {"collapsed": false}, "cost": null, "disabled": false, "notes": "" },
    "sg": { "type": "subgraph:measure" }      // instance of a subgraph below
  },
  "edges": { "e1": {"from": ["n0", "out"], "to": ["n1", "spec"]} },
  "groups": { "g1": {"title": "Continuum", "nodes": ["n4"], "color": "#…"} },
  "subgraphs": {
    "measure": { "name": "Measure line", "nodes": {…}, "edges": {…},
                 "inputs":  [{"name": "spec", "node": "inner1", "port": "spec"}],
                 "outputs": [{"name": "ew", "node": "inner9", "port": "out"}],
                 "promoted": [{"node": "inner5", "param": "vmin", "label": "EW vmin"}] }
  },
  "promoted": [ {"node": "n2", "param": "z", "label": "Redshift", "group": "Setup", "order": 1} ],
  "views": [ {"id": "v1", "node": "n6", "port": "measurement", "kind": "ew-summary"} ],
  "layouts": { "app": {…}, "wizard": {…}, "dashboard": {…}, "batch": {…} },
  "requires": { "packs": {"astro-canvas-core": ">=0.1,<0.2"}, "python": ">=3.10" },
  "meta": { "created": "…", "modified": "…", "author": "…", "tags": ["sample"] }
}
```

Rules the compiler applies (`astro_canvas.engine.graph.compile`):

| Rule | Effect |
|---|---|
| Unknown top-level or node fields | preserved (round-trip safe); `layouts`, `promoted`, `views`, `groups` are passed through untouched |
| `linked` | the named params become input ports typed by the param's `link_type` (`astro.Float`, `astro.Json`, …); the upstream scalar value is unwrapped into the param |
| `disabled` | the node is removed; its first output whose type matches a connected input is passed through, otherwise consumers get `upstream_disabled` |
| `subgraph:<id>` | inlined as `<instance>/<inner id>` nodes; edges to instance `inputs`/`outputs` names are rewired to the inner ports (through nested instances too, up to 8 levels). A **disabled** instance is not inlined and behaves like any disabled node without a passthrough |
| `subgraphs[].promoted` | the inner params an instance may set. The instance addresses one by its ref `"<inner node>.<param>"`: a value in the instance's `params` overrides the inner param, and a ref in the instance's `linked` exposes it as an input port on the instance (and links it on the inner node). Refs nest, so an outer subgraph promotes `"inner.plus.y"` |
| `cost` | overrides the node type's cost class (`cheap`, `expensive`, `auto`) |
| `pos`, `size`, `title`, `ui`, `notes` | UI only; they never affect cache keys |

Validation errors are returned **per node** (`node_errors: {node_id: [{code, message, port?, param?}]}`)
with codes `unknown_node`, `unknown_subgraph`, `subgraph_depth`, `unknown_port`, `dangling_edge`,
`multiple_inputs`, `type_mismatch`, `missing_input`, `missing_param`, `unknown_param`, `bad_param`,
`upstream_disabled`, `cycle`. Nodes with errors, and everything downstream of them, are excluded
from execution; the rest of the graph still runs.

Sample documents live in `backend/tests/fixtures/workflows/` (`math_chain.json`,
`subgraph_math.json`, `disabled_passthrough.json`, and `invalid/*.json` with golden errors in
`expected/`).

## Execution model

* **Cache key** `blake3(type_id | version | canonical_json(params with defaults filled) | fingerprint | sorted upstream (port, key:port))`.
  Keys are stable across processes; UI-only edits do not change them.
* **States** `idle → dirty → queued → running → done | error | cancelled`, plus `stale` for dirty
  nodes gated by cost. Saving a document (`PUT`) recompiles it, marks nodes whose key changed
  dirty and, after a 250 ms debounce, auto-runs the **cheap** ones. **Expensive** nodes (and
  their descendants) wait for `run`. `auto` nodes count as cheap until their moving-average
  runtime exceeds 2 s (persisted per node id in `node_stats`).
* **Executors**: cheap nodes run on a thread pool inside the server; expensive nodes run in a
  `pebble` process pool with inputs passed as blob references. Cancelling a thread node sets
  `ctx.is_cancelled()`; cancelling a process node kills the worker.
* **Lazy inputs** (`PortSpec.lazy`) are handed to the node as `None` and computed on demand via
  `ctx.needs(port)`; for nodes executing in a process they are resolved eagerly.
* **Expanding nodes** (`@node(expand=True)`) return `astro_canvas.sdk.Expansion`; sub-nodes run as
  `<parent>/<sub>` and are cached under keys derived from the parent's key.
* **Caches**: in-memory LRU (`ASTRO_CANVAS_CACHE_MEMORY_MB`, default 2048), content-addressed
  blob store `<workspace>/.astro-canvas/blobs` indexed in `app.db` (`ASTRO_CANVAS_CACHE_DISK_GB`,
  default 20; `ASTRO_CANVAS_CACHE_MAX_AGE_DAYS`, default 30). `astro.Any` values are memory-only.
* **Persistence**: `workflows`, `workflow_versions` (snapshot per changed save), `runs`,
  `node_runs`, `outputs`, `node_stats` in `<workspace>/.astro-canvas/app.db` (Alembic-managed).

## REST API (`/api`, bearer token)

Every `/api/*` route except `/api/health`, `/api/openapi.json` and `/api/docs` requires
`Authorization: Bearer <token>` (or `?token=`). The token is `ASTRO_CANVAS_TOKEN` or generated at
startup and written to `<config>/token` (`ASTRO_CANVAS_CONFIG_DIR`); `astro-canvas serve` prints
the `?token=` URL. Set `ASTRO_CANVAS_AUTH=false` to disable.

| Method & path | Purpose |
|---|---|
| `GET /workflows` | summaries (`id, name, description, created, modified, node_count, hash`) |
| `POST /workflows` | create (409 if the id exists) → `{doc, node_errors}` |
| `GET /workflows/{id}` · `PUT /workflows/{id}` · `DELETE /workflows/{id}` | read / replace (recompiles, auto-runs) / delete |
| `GET /workflows/{id}/versions` · `GET /workflows/{id}/versions/{vid}` | snapshots |
| `GET /workflows/{id}/status` | `{node_errors, nodes: {id: node.status}, current_run, auto_run}` for reconnecting clients |
| `GET /workflows/{id}/settings` · `POST /workflows/{id}/settings` `{auto_run}` | read / toggle the scheduler's auto-run switch (enabling it runs dirty cheap nodes immediately) |
| `POST /workflows/{id}/run` `{targets?}` | 202 `{run_id}`; runs to the targets (default every leaf) |
| `GET /templates` · `GET /templates/{id}` | pack-shipped workflow templates (`id = <pack>.<file stem>`, `name, description, pack, node_count, file, readme`) / the template document itself |
| `POST /templates/{id}/instantiate` `{name?}` | 201 `{doc, node_errors}`: a stored copy under a fresh id (`meta.template` records the origin) that compiles and auto-runs like any workflow |
| `GET /runs?workflow_id=` · `GET /runs/{id}` | history (`status, started, finished, targets, nodes[]`) |
| `POST /runs/{id}/cancel` | `{cancelled}` |
| `GET /outputs/{node}/{port}?workflow_id=&fmt=json\|msgpack\|arrow\|npz&decimate=N&range=lo,hi` | full outputs; `decimate`/`range` apply to spectrum-like values |
| `GET /workspace` · `POST /workspace/select` `{path, create}` | active workspace (root, recent list) / switch folders (closes open workflows, restarts the watcher) |
| `GET /workspace/tree?path=&depth=1&hidden=false` | folder listing, folders first; deeper folders are lazy (`children: null`) |
| `GET /workspace/info?path=&hash=true` | size, mtime, MIME, blake3 (cached in the `files` table by path + mtime) |
| `GET /workspace/file?path=` · `DELETE /workspace/file?path=&recursive=` | download / delete |
| `GET /workspace/sniff?path=` | `{kind: spectrum\|image\|cube\|table\|unknown, node}` from headers/columns |
| `POST /workspace/mkdir` `{path}` · `POST /workspace/upload` (multipart `file, dir, filename, on_conflict, upload_id, chunk_index, chunk_count`) | create folders / upload (chunked above 100 MB) |

Every workspace path is resolved inside the root; absolute paths, `..` and symlinks answer 400.

## WebSocket `/ws?token=…&client_id=…`

Same-origin only (Origin must match Host; localhost variants are interchangeable). Closes with
`4401` (bad token) or `4403` (bad origin). Server → client JSON events all carry `type, ts,
workflow_id`:

| `type` | fields |
|---|---|
| `hello` / `subscribed` / `run.accepted` / `cancel.result` / `pong` / `error` | command replies (`subscribed` carries `current_run` and `auto_run`) |
| `graph.validation` | `node_errors` |
| `node.status` | `node_id, state, run_id, cache_hit, elapsed_ms, cost_class, stale` |
| `node.progress` · `node.log` · `node.error` | `frac, message` · `level, message, fields` · `message, traceback, hint` |
| `node.output.summary` | `node_id, port, type_id, summary, tag` (≤ 4000 points for spectra; `port="$preview"` for `ctx.preview`; `tag` echoes `viewport.tag` so viewer-only slices do not replace thumbnails) |
| `workspace.changed` | `paths` (workspace-relative); broadcast to every subscriber (`workflow_id = "*"`) |
| `run.started` / `run.finished` | `run_id, targets, n_nodes, cached` (+ `status, elapsed_ms`) |
| `preview.computed` | reply to `preview.compute`: `node_id` or `node_type`, `tag`, `ok`, `ports`, `elapsed_ms`, `error` (the tagged `node.output.summary` events for every output precede it) |

Client → server: `subscribe {workflow_id}` (replies with `subscribed`, `graph.validation` and one
`node.status` per node), `run {targets?}`, `cancel {run_id?, node_id?}`,
`preview.request {node_id, port, viewport: {lo, hi, n_out, rows, tag}}` (re-decimated summary: `lo/hi` restrict the axis or the cube band, `n_out` is the point budget or tile edge, `rows` the table head),
`output.request {node_id, port}` (binary frame),
`preview.compute {node_id | node_type, params, tag, viewport}` (phase 05: run one node body with candidate
params outside the scheduler, nothing cached or committed; inputs come from the graph's cached upstream
outputs for `node_id`, or the node type runs on `params` alone; replies are tagged `node.output.summary`
events plus `preview.computed`), `ping`.

Binary frames: `u32 msg_type (1 = output) | u32 header_len | msgpack header | buffers`, header
`{node_id, port, type_id, data, arrays: [{name, dtype, shape, offset, nbytes}]}`; each array is a
C-contiguous little-endian buffer at `offset` in the payload (`dtype="bytes"` for raw parts).

### Summary payloads (phase 04, extended in 06 and 07)

| Type | `summary` |
|---|---|
| `Spectrum1D` | `n, n_view, range, wave[], flux[], error?[], continuum?[], wave_unit, flux_unit, frame, z, v0_wrest` (all series sampled at the same MinMaxLTTB indices; non-finite values are `null`, since phase 06) |
| `Image2D` | `shape, unit, wcs, object, tile: {width, height, step, dtype: "f4", b64, zscale, minmax, percentile}` (base64 little-endian float32 rows) |
| `Cube3D` | `shape, instrument, wave_unit, wave_range, band, has_var, wcs, tile` (white light over `lo..hi`), `spectrum: {wave, flux}` (integrated, ≤ 512 points) |
| `SpectrumCollection` | `count` (always the full length), `labels[]`, `items[]` (each a `Spectrum1D` summary at `n_out`, default 512; at most `max_items`, default 8, cap 64 — the multi-spectrum viewer raises it) |
| `Table` | `n_rows, columns, units, dtypes, head: {col: values}` (first `rows`, default 50), `arrow_b64` (Arrow IPC of the head) |
| `Figure` | `kind, size` plus `plotly` or `png_b64` when ≤ 400 kB |
| `Continuum` | `n, index[], cont[]` (whole when ≤ `n_out`, default 20000, else strided with `index` on the spectrum grid), `masks`, `method`, `order`, `bic`, `params` (JSON-safe; `bic_results` rows) |
| `LineList` | `n, source, wrest[], name[], fval[], gamma?[], weight?[], kind?[]` (first `rows`, default 2000) |
| `rbcodes.ZFindResult` | `statistic` (`chi2`\|`score`), `n, z_range, z[], curves: [{label, values[]}]` (all sampled at the same MinMaxLTTB indices, `n_out` default 2000, non-finite → `null`), `solutions: [{z, z_err, chi2_dof, method, template_type, n_features}]`, `spectrum` (the searched spectrum's own summary), `warnings[]`, `linelist` |
| `rbcodes.AbsorberResult` | same shape with `statistic: "significance"` and `candidates: [{z, significance, n_lines, is_doublet, linelist_name, lines_matched[]}]` |
| `rbcodes.ZCandidates` | `n, accepted, statistics[], rows: [{index, source, rank, z, z_err, score, method, template_type, n_features}]` |
| `rbcodes.MultispecView` | `count, labels[], range, z, linelist`, `panels[]` (each a `Spectrum1D` summary at `n_out`, default 400; at most `max_panels`, default 8, cap 64), `absorbers: [{zabs, linelist, color, visible, label}]`, `identified: [{name, wave_obs, zabs, wave_rest, spectrum}]` |
| scalars, `File`, others | `{type, data: {...}}` (arrays summarised as shape/dtype/min/max) |

## CLI

`astro-canvas run workflow.json [--target n] [--workspace dir] [--json] [--no-processes]` executes
a document headlessly and prints one line per node (state, elapsed, cache flag, output types);
exit code 1 on validation errors or a failed/cancelled run.
