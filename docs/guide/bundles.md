# Bundles: sharing a workflow and its evidence (phase 11)

A `.acw` **bundle** is a workflow packed with everything needed to re-run it *and* to judge it:
the document, the exact pack versions it ran with, a hash per input file, the results it
produced, preview images and a per-node provenance record. Share menu ▸ **Export bundle…**.

## What is inside

```
workflow.json      the document, exactly as saved
lock.json          pack versions, python version, platform, app version, the uv freeze
inputs/refs.json   one entry per input file: path, blake3, size, whether it is embedded
inputs/<files>     embedded copies of the small ones
outputs/<ref>.*    finished node outputs (CSV for tables, .npz for arrays, JSON otherwise)
figures/*.png      rendered previews, and figures/card.png for the gallery
provenance.json    per node: cache key, state, elapsed, the pack it came from
trust.json         the hash of every Python snippet — decisions are *not* included
README.md          a generated summary you can read without the app
```

Three choices in the export dialog change what travels:

- **Embed input files up to N MB** (200 by default). A file below the limit is copied into the
  bundle; a larger one travels as a path and a hash, and the importer is told where it should be.
- **Include outputs**: *Final results* (what nothing else consumes), *Every node*, or *None*.
- **Render preview images** for the gallery card.

Two things are never in a bundle. `astro.Any` outputs — in-process Python objects — have no file
form and are dropped. And **pickle is never written and never read**: a bundle carrying a
pickle-shaped member is refused on import.

The bundle is written into `<workspace>/bundles/` so it sits next to the data it describes; the
dialog's *Download* link is for sending it somewhere else.

## Importing

Drop a `.acw` onto the canvas, or Share ▸ **Import bundle…**. The archive is checked *before a
byte is written* — path traversal, symlinks, pickle members, and a cap on entry count, total
size and compression ratio — and then the workflow opens with anything that still needs your
attention reported:

| What you may see | What it means |
|---|---|
| **Missing packs** | `requires.packs` names something this machine does not have. Install it from Manager ▸ Registry, then reopen. |
| **N input files are missing** | The bundle carried their hashes but not their contents (too large to embed). Put them where the document expects them, or repoint the loader nodes. |
| **N input files differ** | A file of that name is already here, with different content. Yours is kept; nothing is overwritten. |
| **N input files restored** | Embedded copies were unpacked under `imports/`, and the document now points at them. |
| A red **quarantine banner** | The workflow contains Python. See below. |

The imported workflow gets a **fresh id but keeps its node ids**, so promoted parameters, pinned
views and every layout section still resolve — the modes work exactly as the author left them.

## Code nodes arrive quarantined

A shared workflow can carry arbitrary Python, so a bundle's code nodes do not run until you have
read them.

Every snippet is addressed by the **hash of its source**, and you decide once per hash. Until
every snippet in a document has been trusted, the workflow opens with a banner, its code nodes
report *review and trust this code snippet before it can run*, and neither they nor anything
downstream of them executes.

**Review code** shows each snippet in full, with its node and its hash, and offers **Trust** or
**Block**. Trusting one enables every node carrying that exact snippet. **Editing** a trusted
snippet changes its hash, so the gate closes again by construction — you cannot trust a snippet
and then be handed a different one.

Code you write yourself is trusted the moment you save it. Only documents that arrived from
outside start quarantined. Decisions live in the workspace database and can be revisited (a
snippet you forget goes back to being unreviewed).

> Trusting a snippet means allowing it to run with your files and your network access. Read it.

## Reproducing a bundle elsewhere

`lock.json` records the pack versions, the Python version and the platform the run happened on.
To reproduce a result on another machine:

1. Import the bundle. Fix whatever it reports — usually installing a pack.
2. Compare `lock.json` with Manager ▸ Installed. Same versions means the same numbers.
3. Run. `provenance.json` holds the cache key of every node in the original run; a node that
   produces the same key produces the same output by construction.

## Templates are bundles

A pack's templates are `.acw` files inside the pack (design §7.3), which is why the gallery and
the import path share a reader: both a zip bundle and a bare `workflow.json` open. A pack that
wants a gallery card ships `<template>.png` beside the document — which is exactly what a bundle
export's `figures/card.png` gives you.
