# Node schema (`GET /api/nodes`)

The server describes every node type as a `NodeSpec` JSON object. The frontend renders menus,
widgets and ports from it; the engine validates workflows against it. Produced by
`astro_canvas.sdk` introspection of `@node` functions (see the SDK README for the Python rules).

## Endpoints

| Path | Returns |
|---|---|
| `GET /api/nodes[?category=…]` | `NodeSpec[]` sorted by `id` |
| `GET /api/nodes/{id}` | one `NodeSpec` (404 for unknown ids) |
| `GET /api/types` | `PortTypeSpec[]` sorted by `id` |
| `GET /api/packs` | `PackRecord[]` including packs that failed to load |

The full machine-readable contract is `backend/src/astro_canvas/server/openapi/openapi.json`
(regenerate with `task api:gen`, which also rebuilds `frontend/src/api/schema.d.ts`).

## `NodeSpec`

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Unique dotted id, lowercase (`core.spec.crop`). Pack prefix by convention. |
| `name`, `category` | string | Display name; slash-separated menu path (`Spectra/Transform`). |
| `version` | string | Semver of the node contract. |
| `cost` | `cheap` \| `expensive` \| `auto` | Cost class for reactive execution. |
| `inputs` | `PortSpec[]` | Input ports (annotation is a registered port type). |
| `params` | `ParamSpec[]` | Widget parameters (JSON-native annotations). |
| `outputs` | `PortSpec[]` | Output ports: `out` for a single return, `out0…` for tuples unless `outputs=` names them, field names for `NamedTuple`/dataclass returns, empty for `None`. |
| `description` | string | Docstring summary and long description (Google or NumPy style). |
| `param_docs` | object | Raw docstring descriptions by parameter name (ports included). |
| `icon`, `preview`, `editor` | string \| null | Frontend ids. |
| `pack` | string \| null | Entry-point name of the pack that registered the node. |
| `module` | string | Python module defining the function. |
| `deprecated`, `experimental`, `expand`, `fingerprint`, `is_async` | bool | Flags. |
| `dynamic_ports` | object \| null | Set when the node's ports come from its own params (phase 11). |

### `PortSpec`

`{name, type, description, required, lazy}`. `type` is a port type id such as `astro.Spectrum1D`.
`required` is false when the annotation is `Optional` or has a default. `lazy` ports are resolved on
demand through `ctx.needs(name)`.

### `dynamic_ports`

Almost every node has a fixed shape. The exception is a node that lets the *user* declare its
ports — the code node — where `dynamic_ports` names the parameters holding them:

```jsonc
"dynamic_ports": { "inputs": "inputs", "outputs": "outputs", "values": "values" }
```

The `inputs` param holds `[{"name": "spec", "type": "astro.Spectrum1D"}, …]` and so does
`outputs`; `values` is the function parameter that receives `{port name: value}`. `inputs` and
`outputs` in the spec itself list only the node's *fixed* ports, so a consumer must merge the
declared ones in: `astro_canvas.sdk.ports.effective_ports(spec, params)` on the server,
`applyDynamicPorts(spec, node)` on the client. A declared name must be a Python identifier;
malformed or duplicate entries are dropped rather than raising, because a half-typed row is a
normal state while editing.

### `ParamSpec`

| Field | Meaning |
|---|---|
| `name`, `label`, `description` | Identifier, title (`Param.label` or capitalised name), help text (`Param.help` or docstring). |
| `json_schema` | Self-contained JSON Schema (2020-12) from pydantic, with `$defs` inlined when needed. Carries `default`, `minimum`/`maximum` (`Param.min/max`), `enum` (`Literal` or `Param.choices`), `description`, `title`, and the extensions below. |
| `required` | True when the parameter has no default. |
| `default` | JSON default (Quantity defaults are converted to the declared unit). |
| `widget`, `unit`, `step`, `advanced` | Copied from `Param`. |
| `linkable`, `link_type` | Every param may be converted into an input port; `link_type` is the port type it then takes (`astro.Float`, `astro.Int`, `astro.Str`, `astro.Bool`, otherwise `astro.Json`). |

JSON Schema extensions: `x-unit` (astropy unit string, from `Param(unit=)` or `Quantity[unit]`),
`x-widget`, `x-step`, `x-advanced`, and `x-ndarray: {dtype, ndim}` on array fields of port types.

## `PortTypeSpec`

`{id, name, color, summary_renderer, compatible_with, description, json_schema, module, pack}`.
Compatibility: exact id match; `astro.Any` accepts everything; `astro.Json` accepts scalar types;
a source type may list explicit coercion targets in `compatible_with`
(`astro.Spectrum1D → astro.SpectrumCollection`).

## `PackRecord`

`{name, version, distribution, entry_point, enabled, node_count, type_count, error}` where `error`
is `null` or `{pack, entry_point, error, traceback}`. A failing pack never prevents others from
loading; its partial registrations are rolled back.

## Blobs

Port values serialize with `to_blob()` to a JSON manifest `{type, data}` plus binary parts:
arrays go into one `arrays.npz` (placeholders `{"$ndarray": "<path>"}` in `data`), raw bytes into
their own parts (`{"$bytes": "<path>"}`), tables into `table.arrow` (Arrow IPC stream). `Blob.pack()`
is a deterministic zip used for hashing and bundles. `astro.Any` values cannot be serialized.
