# API reference

Every endpoint of the app's HTTP API, generated from the OpenAPI snapshot at
`backend/src/astro_canvas/server/openapi/openapi.json` — run `task api:gen` to refresh both.

A running server serves the same contract interactively at
[`/api/docs`](http://127.0.0.1:8765/api/docs) (Swagger UI) and as raw JSON at
`/api/openapi.json`. Those two, plus `/api/health`, are the only routes that do **not** need a
token.

## Authentication

Everything else needs a bearer token:

```sh
curl -H "Authorization: Bearer $(cat ~/.config/AstroCanvas/token)" \
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


## `auth`

Login, logout and registration on a `--auth users` server (design 12). Public.

| | Endpoint | What it does |
|---|---|---|
| `POST` | `/api/auth/bearer/login` | Auth:Bearer.Login |
| `POST` | `/api/auth/bearer/logout` | Auth:Bearer.Logout |
| `GET` | `/api/auth/info` | Auth Info |
| `POST` | `/api/auth/login` | Auth:Cookie.Login |
| `POST` | `/api/auth/logout` | Auth:Cookie.Logout |
| `POST` | `/api/auth/register` | Register:Register |

### `POST /api/auth/bearer/login`

**Body** `application/x-www-form-urlencoded`

**Returns** `200` `BearerResponse`

### `POST /api/auth/bearer/logout`

**Returns** `200` `application/json`

### `GET /api/auth/info`

Which login methods this server offers (public: the login page needs it).

**Returns** `200` `AuthInfo`

### `POST /api/auth/login`

**Body** `application/x-www-form-urlencoded`

**Returns** `200` `application/json`

### `POST /api/auth/logout`

**Returns** `200` `application/json`

### `POST /api/auth/register`

**Body** `UserCreate`

**Returns** `201` `UserRead`

## `batch`

Running a workflow over a table of rows.

| | Endpoint | What it does |
|---|---|---|
| `POST` | `/api/workflows/{workflow_id}/batch` | Start Batch |
| `GET` | `/api/workflows/{workflow_id}/batch/{batch_id}` | Get Batch |
| `POST` | `/api/workflows/{workflow_id}/batch/{batch_id}/cancel` | Cancel Batch |

### `POST /api/workflows/{workflow_id}/batch`

Run the stored document once per row; returns immediately with the batch record.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Body** `BatchRequest`

**Returns** `202` `BatchInfo`

### `GET /api/workflows/{workflow_id}/batch/{batch_id}`

The batch's per-row states and the results assembled so far.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |
| `batch_id` | path (required) | `string` |  |

**Returns** `200` `BatchInfo`

### `POST /api/workflows/{workflow_id}/batch/{batch_id}/cancel`

Stop queued rows and cancel the ones in flight (expensive nodes have their worker killed).

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |
| `batch_id` | path (required) | `string` |  |

**Returns** `200` `BatchInfo`

## `bundles`

Exporting and importing `.acw` bundles.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/bundles/download` | Download Bundle |
| `POST` | `/api/bundles/export` | Create Bundle |
| `POST` | `/api/bundles/import` | Import Bundle |

### `GET /api/bundles/download`

Serve a bundle that lives in the workspace.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `path` | query (required) | `string` |  |

**Returns** `200` `application/json`

### `POST /api/bundles/export`

Pack a workflow, its inputs, its finished outputs and its provenance into a ``.acw``.

**Body** `BundleExportRequest`

**Returns** `200` `BundleManifest`

### `POST /api/bundles/import`

Validate an uploaded ``.acw``, restore what it carries and save the workflow.

The workflow is stored either way so the user can look at it; ``missing_packs``,
``layout_errors``, ``inputs`` and ``quarantined`` say what still needs attention.

**Body** `multipart/form-data`

**Returns** `201` `BundleImportResult`

## `manager`

The pack manager. Admin-only on a shared server, and absent when `ASTRO_CANVAS_MANAGER=false`.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/manager/packs` | List Packs |
| `POST` | `/api/manager/packs/install` | Install |
| `POST` | `/api/manager/packs/resolve` | Resolve |
| `DELETE` | `/api/manager/packs/{name}` | Uninstall Pack |
| `POST` | `/api/manager/packs/{name}/enabled` | Set Enabled |
| `POST` | `/api/manager/packs/{name}/import-test` | Import Test |
| `POST` | `/api/manager/packs/{name}/update` | Update Pack |
| `GET` | `/api/manager/registry` | Get Registry |
| `POST` | `/api/manager/settings` | Update Settings |
| `GET` | `/api/manager/snapshots` | List Snapshots |
| `POST` | `/api/manager/snapshots` | Create Snapshot |
| `GET` | `/api/manager/snapshots/{snapshot_id}` | Snapshot Packages |
| `POST` | `/api/manager/snapshots/{snapshot_id}/rollback` | Rollback |
| `GET` | `/api/manager/status` | Get Status |

### `GET /api/manager/packs`

Every discovered pack with its database state and load error.

**Returns** `200` `PackDetail`[]

### `POST /api/manager/packs/install`

Install a source the user has confirmed a plan for.

**Body** `InstallRequest`

**Returns** `200` `InstallResult`

### `POST /api/manager/packs/resolve`

Dry-run a source and return the resolution diff (or the conflicts that block it).

**Body** `ResolveRequest`

**Returns** `200` `InstallPlan`

### `DELETE /api/manager/packs/{name}`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `name` | path (required) | `string` |  |

**Returns** `200` `InstallResult`

### `POST /api/manager/packs/{name}/enabled`

Enable or disable a pack; disabled packs stay installed but are not registered.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `name` | path (required) | `string` |  |

**Body** `EnableRequest`

**Returns** `200` `PackDetail`

### `POST /api/manager/packs/{name}/import-test`

Import the pack in a subprocess and report the traceback if it fails.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `name` | path (required) | `string` |  |

**Returns** `200` `ImportTest`

### `POST /api/manager/packs/{name}/update`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `name` | path (required) | `string` |  |

**Returns** `200` `InstallResult`

### `GET /api/manager/registry`

The registry index, filtered. Never fails: a stale cached copy beats an empty tab.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `refresh` | query | `boolean` |  |
| `q` | query | `string` |  |
| `category` | query | `string` or null |  |

**Returns** `200` `RegistryIndex`

### `POST /api/manager/settings`

Persist the security level, uv path or registry URL for this workspace.

**Body** `ManagerSettingsUpdate`

**Returns** `200` `ManagerSettings`

### `GET /api/manager/snapshots`

**Returns** `200` `SnapshotInfo`[]

### `POST /api/manager/snapshots`

Record ``uv pip freeze`` so this environment can be restored later.

**Body** `SnapshotRequest` or null

**Returns** `200` `SnapshotInfo`

### `GET /api/manager/snapshots/{snapshot_id}`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `snapshot_id` | path (required) | `integer` |  |

**Returns** `200` `string`[]

### `POST /api/manager/snapshots/{snapshot_id}/rollback`

Restore a snapshot exactly (``uv pip sync`` against the recorded freeze).

| Parameter | In | Type | Notes |
|---|---|---|---|
| `snapshot_id` | path (required) | `integer` |  |

**Returns** `200` `InstallResult`

### `GET /api/manager/status`

uv, the interpreter packs are installed into, and the current preferences.

**Returns** `200` `ManagerStatus`

## `nodes`

The node and port-type schemas the UI builds itself from, and the discovered packs.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/nodes` | List Nodes |
| `GET` | `/api/nodes/{node_id}` | Get Node |
| `GET` | `/api/packs` | List Packs |
| `GET` | `/api/types` | List Types |

### `GET /api/nodes`

Every registered node schema, sorted by id; optionally filtered by exact category.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `category` | query | `string` or null |  |

**Returns** `200` `NodeSpec`[]

### `GET /api/nodes/{node_id}`

One node schema by id.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `node_id` | path (required) | `string` |  |

**Returns** `200` `NodeSpec`

### `GET /api/packs`

Discovered packs, including the ones that failed to load (with their error).

**Returns** `200` `PackRecord`[]

### `GET /api/types`

Every registered port type, sorted by id.

**Returns** `200` `PortTypeSpec`[]

## `outputs`

A finished node's full output, as msgpack, Arrow, JSON or npz.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/outputs/{node_id}/{port}` | Get Output |

### `GET /api/outputs/{node_id}/{port}`

A finished node's output. ``decimate``/``range`` apply to 1-d spectrum-like values.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `node_id` | path (required) | `string` |  |
| `port` | path (required) | `string` |  |
| `workflow_id` | query (required) | `string` | Workflow the node belongs to. |
| `fmt` | query | `json` | `msgpack` | `arrow` | `npz` |  |
| `decimate` | query | `integer` or null |  |
| `range` | query | `string` or null | ``lo,hi`` on the x axis. |

**Returns** `200` `application/json`

## `runs`

Starting, inspecting and cancelling a run.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/runs` | List Runs |
| `GET` | `/api/runs/{run_id}` | Get Run |
| `POST` | `/api/runs/{run_id}/cancel` | Cancel Run |
| `POST` | `/api/workflows/{workflow_id}/run` | Start Run |

### `GET /api/runs`

Recent runs (persisted across restarts), newest first.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | query | `string` or null |  |
| `limit` | query | `integer` |  |

**Returns** `200` `RunDetail`[]

### `GET /api/runs/{run_id}`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `run_id` | path (required) | `string` |  |

**Returns** `200` `RunDetail`

### `POST /api/runs/{run_id}/cancel`

Cancel the run if it is still executing (kills process workers, flags threads).

| Parameter | In | Type | Notes |
|---|---|---|---|
| `run_id` | path (required) | `string` |  |

**Returns** `200` `CancelResult`

### `POST /api/workflows/{workflow_id}/run`

Queue a run (stale expensive nodes included) and return its id immediately.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Body** `RunRequest` or null

**Returns** `202` `RunAccepted`

## `system`

Health and system information. `/api/health` is the one route that needs no token.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/health` | Health |
| `GET` | `/api/system` | System |

### `GET /api/health`

Return ``ok`` and the server version.

**Returns** `200` `HealthResponse`

### `GET /api/system`

Describe the running server: versions, workspace, disk, packs.

**Returns** `200` `SystemInfo`

## `templates`

Workflow templates shipped by packs, and instantiating one.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/templates` | Get Templates |
| `GET` | `/api/templates/{template_id}` | Get Template |
| `GET` | `/api/templates/{template_id}/figure` | Get Template Figure |
| `POST` | `/api/templates/{template_id}/instantiate` | Instantiate Template |

### `GET /api/templates`

Templates shipped by the installed packs.

**Returns** `200` `TemplateInfo`[]

### `GET /api/templates/{template_id}`

The template document itself (not stored; instantiate to get an editable workflow).

| Parameter | In | Type | Notes |
|---|---|---|---|
| `template_id` | path (required) | `string` |  |

**Returns** `200` `WorkflowDoc`

### `GET /api/templates/{template_id}/figure`

The gallery card image a pack ships next to the template document.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `template_id` | path (required) | `string` |  |

**Returns** `200` `application/json`

### `POST /api/templates/{template_id}/instantiate`

Create a new workflow from the template (fresh id; ``meta.template`` records the origin).

| Parameter | In | Type | Notes |
|---|---|---|---|
| `template_id` | path (required) | `string` |  |

**Body** `InstantiateRequest` or null

**Returns** `201` `WorkflowSaved`

## `trust`

The code node's trust gate: what is quarantined, and deciding about it.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/manager/trust` | List Trust |
| `POST` | `/api/manager/trust` | Set Trust |
| `DELETE` | `/api/manager/trust/{snippet_hash}` | Forget Trust |
| `GET` | `/api/workflows/{workflow_id}/trust` | Review Workflow |

### `GET /api/manager/trust`

Every code-snippet decision this workspace has made.

**Returns** `200` `TrustRecord`[]

### `POST /api/manager/trust`

Trust or block one snippet hash; every node with that snippet follows.

**Body** `TrustRequest`

**Returns** `200` `TrustRecord`

### `DELETE /api/manager/trust/{snippet_hash}`

Forget a decision, so the snippet is quarantined again.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `snippet_hash` | path (required) | `string` |  |

**Returns** `204`

### `GET /api/workflows/{workflow_id}/trust`

The code snippets of one workflow with their decisions: the quarantine banner's source.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Returns** `200` `TrustReview`

## `users`

The signed-in account, and user administration for a superuser.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/users/me` | Users:Current User |
| `PATCH` | `/api/users/me` | Users:Patch Current User |
| `DELETE` | `/api/users/{id}` | Users:Delete User |
| `GET` | `/api/users/{id}` | Users:User |
| `PATCH` | `/api/users/{id}` | Users:Patch User |

### `GET /api/users/me`

**Returns** `200` `UserRead`

### `PATCH /api/users/me`

**Body** `UserUpdate`

**Returns** `200` `UserRead`

### `DELETE /api/users/{id}`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `id` | path (required) | `string` |  |

**Returns** `204`

### `GET /api/users/{id}`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `id` | path (required) | `string` |  |

**Returns** `200` `UserRead`

### `PATCH /api/users/{id}`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `id` | path (required) | `string` |  |

**Body** `UserUpdate`

**Returns** `200` `UserRead`

## `workflows`

Documents: CRUD, version history, the per-node status snapshot and the engine switches for one workflow.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/workflows` | List Workflows |
| `POST` | `/api/workflows` | Create Workflow |
| `DELETE` | `/api/workflows/{workflow_id}` | Delete Workflow |
| `GET` | `/api/workflows/{workflow_id}` | Get Workflow |
| `PUT` | `/api/workflows/{workflow_id}` | Put Workflow |
| `POST` | `/api/workflows/{workflow_id}/exports` | Create Export |
| `GET` | `/api/workflows/{workflow_id}/settings` | Get Settings |
| `POST` | `/api/workflows/{workflow_id}/settings` | Update Settings |
| `GET` | `/api/workflows/{workflow_id}/status` | Workflow Status |
| `GET` | `/api/workflows/{workflow_id}/versions` | List Versions |
| `GET` | `/api/workflows/{workflow_id}/versions/{version_id}` | Get Version |

### `GET /api/workflows`

Stored workflows, most recently modified first.

**Returns** `200` `WorkflowSummary`[]

### `POST /api/workflows`

Store a new document (a fresh id is assigned when the given one already exists).

**Body** `WorkflowDoc`

**Returns** `201` `WorkflowSaved`

### `DELETE /api/workflows/{workflow_id}`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Returns** `204`

### `GET /api/workflows/{workflow_id}`

The stored document, or its newest readable version with ``meta.recovered`` set.

A document that no longer validates is not a lost workflow: every save is in
``workflow_versions``. If none of them validates either, the pydantic error travels as a 422
(`server/errors.py`) so the SPA can say what is wrong rather than "internal server error".

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Returns** `200` `WorkflowDoc`

### `PUT /api/workflows/{workflow_id}`

Replace the document; the engine recompiles it and auto-runs cheap dirty nodes.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Body** `WorkflowDoc`

**Returns** `200` `WorkflowSaved`

### `POST /api/workflows/{workflow_id}/exports`

Write the named outputs into the workspace and return their paths.

A recompute already under way is waited out first (up to a minute), so an export that follows
an edit writes the new values instead of reporting them as missing. Refs that nothing is going
to produce -- a cost-gated node, an unknown one -- come back in ``skipped``.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Body** `ExportRequest`

**Returns** `200` `ExportResult`

### `GET /api/workflows/{workflow_id}/settings`

The scheduler switches for one workflow.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Returns** `200` `WorkflowSettings`

### `POST /api/workflows/{workflow_id}/settings`

Toggle auto-run; enabling it schedules any dirty cheap nodes right away.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Body** `WorkflowSettings`

**Returns** `200` `WorkflowSettings`

### `GET /api/workflows/{workflow_id}/status`

Compile issues and the state of every node (what a reconnecting client needs).

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Returns** `200` `WorkflowStatus`

### `GET /api/workflows/{workflow_id}/versions`

Auto-snapshots (every changed save) and labelled versions, newest first.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |

**Returns** `200` `WorkflowVersionInfo`[]

### `GET /api/workflows/{workflow_id}/versions/{version_id}`

| Parameter | In | Type | Notes |
|---|---|---|---|
| `workflow_id` | path (required) | `string` |  |
| `version_id` | path (required) | `integer` |  |

**Returns** `200` `WorkflowDoc`

## `workspace`

The workspace folder: listing, reading, writing, uploading and switching.

| | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/workspace` | Workspace Info |
| `DELETE` | `/api/workspace/file` | Delete Path |
| `GET` | `/api/workspace/file` | Download File |
| `GET` | `/api/workspace/info` | File Info |
| `POST` | `/api/workspace/mkdir` | Make Directory |
| `POST` | `/api/workspace/select` | Select Workspace |
| `GET` | `/api/workspace/sniff` | Sniff File |
| `GET` | `/api/workspace/tree` | Workspace Tree |
| `POST` | `/api/workspace/upload` | Upload File |

### `GET /api/workspace`

The active workspace folder and recently used ones.

**Returns** `200` `WorkspaceInfo`

### `DELETE /api/workspace/file`

Delete a file, or a folder (``recursive=true`` removes its contents).

| Parameter | In | Type | Notes |
|---|---|---|---|
| `path` | query (required) | `string` | Workspace-relative file or (empty) folder. |
| `recursive` | query | `boolean` |  |

**Returns** `204`

### `GET /api/workspace/file`

Download a workspace file.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `path` | query (required) | `string` | Workspace-relative file path. |

**Returns** `200` `application/json`

### `GET /api/workspace/info`

Size, mtime, MIME and blake3 (cached by path + mtime) of one file.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `path` | query (required) | `string` | Workspace-relative file path. |
| `hash` | query | `boolean` |  |

**Returns** `200` `FileInfoModel`

### `POST /api/workspace/mkdir`

Create a folder (and parents) inside the workspace.

**Body** `MkdirRequest`

**Returns** `201` `EntryModel`

### `POST /api/workspace/select`

Switch the server to another workspace folder (closing every open workflow).

**Body** `SelectRequest`

**Returns** `200` `WorkspaceInfo`

### `GET /api/workspace/sniff`

Guess the data kind of a file and the ``core.io.load_*`` node that reads it.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `path` | query (required) | `string` | Workspace-relative file path. |

**Returns** `200` `SniffResult`

### `GET /api/workspace/tree`

Entries of a folder, folders first; nested folders beyond ``depth`` are listed lazily.

| Parameter | In | Type | Notes |
|---|---|---|---|
| `path` | query | `string` | Workspace-relative folder (``''`` = root). |
| `depth` | query | `integer` |  |
| `hidden` | query | `boolean` |  |

**Returns** `200` `TreeResponse`

### `POST /api/workspace/upload`

Store an uploaded file in the workspace.

Files above 100 MB should be sent as ordered chunks sharing an ``upload_id``; the file lands
at its final path when the last chunk (``chunk_index == chunk_count - 1``) arrives.

**Body** `multipart/form-data`

**Returns** `201` `UploadResult`

## Schemas

The request and response models above are pydantic models on the server and generated TypeScript in `frontend/src/api/schema.d.ts`. The ones worth reading in prose are documented in [the node schema](formats/node-schema.md) (`NodeSpec`, `ParamSpec`, `PortTypeSpec`, `PackRecord`), [the workflow format](formats/workflow.md) (`WorkflowDoc` and everything under it) and [the bundle format](formats/bundle.md). For the rest, the JSON Schema in the snapshot is the reference:

`AuthInfo`, `BatchBinding`, `BatchCollect`, `BatchInfo`, `BatchRequest`, `BatchResults`, `BatchRowInfo`, `BatchSpec`, `BearerResponse`, `Body_auth_bearer_login_api_auth_bearer_login_post`, `Body_auth_cookie_login_api_auth_login_post`, `Body_import_bundle_api_bundles_import_post`, `Body_upload_file_api_workspace_upload_post`, `BundleExportRequest`, `BundleImportResult`, `BundleLock`, `BundleManifest`, `CancelResult`, `CodeSnippet`, `DynamicPorts`, `EdgeDoc`, `EnableRequest`, `EntryModel`, `ErrorModel`, `ExportRequest`, `ExportResult`, `ExportedFile`, `FileInfoModel`, `GroupDoc`, `HTTPValidationError`, `HealthResponse`, `ImportTest`, `ImportedInput`, `InputRef`, `InstallPlan`, `InstallRequest`, `InstallResult`, `InstantiateRequest`, `LayoutIssue`, `ManagerSettings`, `ManagerSettingsUpdate`, `ManagerStatus`, `MkdirRequest`, `NodeDoc`, `NodeIssue`, `NodeRunInfo`, `NodeSpec`, `NodeStatus`, `PackDetail`, `PackInfo`, `PackLoadError`, `PackRecord`, `PackageChange`, `ParamSpec`, `PortSpec`, `PortTypeSpec`, `PromotedDoc`, `RegistryEntry`, `RegistryIndex`, `RegistryTemplate`, `ResolveRequest`, `RunAccepted`, `RunDetail`, `RunRequest`, `SelectRequest`, `SkippedExport`, `SnapshotInfo`, `SnapshotRequest`, `SniffResult`, `SubgraphDoc`, `SubgraphPort`, `SystemInfo`, `TemplateInfo`, `TreeResponse`, `TrustRecord`, `TrustRequest`, `TrustReview`, `UploadResult`, `UserCreate`, `UserRead`, `UserUpdate`, `ValidationError`, `ViewDoc`, `WorkflowDoc`, `WorkflowSaved`, `WorkflowSettings`, `WorkflowStatus`, `WorkflowSummary`, `WorkflowVersionInfo`, `WorkspaceInfo`.
