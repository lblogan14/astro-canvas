# Concepts

The vocabulary the rest of these pages assume. Six ideas, and they compose.

## Nodes and ports

A **node** is one operation. It has typed **input ports** on the left, **params** in its body and
**output ports** on the right. Connecting an output to an input makes an **edge**, and the type
system decides whether the connection is allowed before you drop it.

On the Python side a node is a plain function, and everything the app knows about it is derived
from its signature:

```python
@node(id="core.math.expr", category="Math", cost="cheap")
def expression(x: Float, expression: str = "x ** 2") -> Float:
    """Evaluate a small arithmetic expression.

    Args:
        x: The value the expression refers to.
        expression: Python arithmetic over ``x``.
    """
```

`x: Float` is an input port because `Float` is a registered port type. `expression: str` is a
param, rendered as a text widget — and also connectable, because every param can be driven by an
edge instead. The docstring becomes the help text you read in the app; it is part of the
contract, not decoration. Full rules: [node schema](formats/node-schema.md).

**Port types** are the wire format. `astro.Spectrum1D`, `astro.Image2D`, `astro.Table`,
`astro.Cube` and the scalars each know how to serialise themselves (Arrow IPC for tables, mapped
arrays for cubes) and how to summarise themselves for a preview. `astro.Any` deliberately does
not: an `Any` value stays in memory and is never written to a bundle.

## Reactive, not batch

Astro Canvas does not have a Run-everything button that you press when you are done editing.
Every node has a **cache key**:

```
key = blake3(type | version | canonical_json(params) | fingerprint | upstream keys)
```

Change a param and the key changes, so the node and everything downstream is **dirty** and
re-runs. Rename the node, move it, resize it — the key does not change, so nothing runs. That is
why editing a document feels free: dirtiness is derived from content, never from edit events.

The states are `idle → dirty → queued → running → done`, plus `error` and `cancelled`.

## Cheap, expensive and auto

Auto-running everything would be miserable the moment a node takes ten seconds. So each node
declares a **cost**:

| Cost | Behaviour |
|---|---|
| `cheap` | Runs automatically, 250 ms after you stop typing |
| `expensive` | Goes **stale** and waits for **Run** — and so does everything downstream |
| `auto` | Cheap until its moving-average runtime passes two seconds, then expensive |

`auto` is the interesting one: it measures the node *in your workspace, on your data*, and
promotes it when it earns the promotion. Those statistics are stored per node instance, so a fit
that is fast on a 500-pixel spectrum and slow on a cube behaves correctly in both.

Cheap nodes run on a thread pool inside the server; expensive ones run in a separate process, so
cancelling one kills the worker rather than politely asking it to stop.

## The workspace

A **workspace** is a folder you own:

```
AstroCanvas/
├─ samples/          # sample data copied out of the installed packs on first run
├─ uploads/          # what you dragged in
├─ downloads/        # what archive-query nodes fetched, keyed by query hash
├─ bundles/          # exported .acw files
└─ .astro-canvas/
   ├─ app.db         # workflows, versions, run history, packs, snapshots, trust decisions
   ├─ blobs/         # content-addressed results
   └─ scratch/
```

Everything about a project is inside it, which makes "start a clean one for this paper" a real
option:

```sh
astro-canvas workspace new ~/papers/lya
```

Switching workspaces switches more than files: the security level, which packs are enabled and
which code snippets you have trusted all live in that database.

## Documents, layouts and modes

A workflow is one JSON document ([format](formats/workflow.md)): nodes, edges, groups,
subgraphs, and the *presentation* — which params are promoted, which previews are pinned, and how
they are laid out.

That last part is what makes **app modes** work. The same document renders as:

- **Canvas** — the graph.
- **App** — a form of the starred parameters with the pinned results beneath.
- **Wizard** — the same, one step at a time.
- **Dashboard** — a grid of linked views, where a range dragged on a spectrum filters the table
  fed by it.

The mode is in the URL (`/w/<id>/wizard`), so it is a link. See [app modes](guide/modes.md).

## Packs

The app ships no science. **Packs** are ordinary Python distributions that expose an
`astro_canvas.nodes` entry point, and they are installed with `uv` into the same environment the
server runs in — one environment, not one per pack, so a spectrum from `core` really is the same
object `rbcodes` receives.

The manager makes that shared environment safe to touch: it resolves first and shows you the
diff, pins the app's own distributions so a pack that would break them comes back as an honest
conflict, snapshots before every change, import-tests in a subprocess, and can roll back exactly.
See [node packs](guide/packs.md) and, for writing one,
[publishing a pack](packs/publishing.md).

## Reproducibility

Three mechanisms, and they only matter together:

1. **Content-addressed results.** A result is stored under the hash of everything that produced
   it, so "is this plot current?" is a lookup, not a judgement call.
2. **Provenance.** Each node records what it ran with — the pack, the version, the params, the
   input hashes.
3. **Bundles.** One `.acw` file carries the document, a dependency lock, the input hashes, the
   results, the figures and that provenance. Import it somewhere else and anything missing is
   listed rather than silently substituted.

See [bundles](guide/bundles.md).
