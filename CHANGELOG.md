# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) — with the usual `0.x` caveat that a
minor bump may break things.

The four distributions are released together and share this file:
[`astro-canvas`](https://pypi.org/project/astro-canvas/),
[`astro-canvas-sdk`](https://pypi.org/project/astro-canvas-sdk/),
[`astro-canvas-core`](https://pypi.org/project/astro-canvas-core/) and
[`astro-canvas-rbcodes`](https://pypi.org/project/astro-canvas-rbcodes/).

## [Unreleased]

## [0.1.0] - 2026-09-05

The first release. A node-based infinite canvas for astronomical data: a FastAPI server with a
reactive execution engine, a Vue 3 canvas, and the science in installable node packs.

### Added

**The canvas.** Vue Flow behind a deliberate adapter seam, with a searchable node library, typed
connections that refuse what cannot be wired, schema-generated parameter forms, inline previews on
every node, a full-size viewer, command-pattern undo/redo, copy/paste, groups, subgraphs with
breadcrumb navigation, elk auto-layout, autosave and version history. 500 nodes pan and zoom at
94 % of the display's frame rate.

**The execution engine.** Dirtiness derived from content-hash cache keys rather than edit events,
so a title change invalidates nothing: `blake3(type | version | params | fingerprint | upstream
keys)`. Cheap nodes run on a thread pool after a 250 ms debounce; expensive ones run in a `pebble`
process pool and wait for an explicit Run, as does everything downstream of them; `auto` nodes
promote themselves once their moving-average runtime passes two seconds. Cancellation is
cooperative for threads and fatal for workers. A memory LRU sits over a content-addressed blob
store, and large arrays (IFU cubes) are memory-mapped out of it rather than copied. Partial
execution is a first-class case: a graph with errors still runs the part that compiles.

**Data.** A workspace folder you browse, upload into and drag files from; loaders for spectra,
tables, images and cubes with instrument-specific readers; archive fetch nodes for SDSS, SIMBAD,
VizieR and MAST; previews that decimate on the server (uPlot thumbnails, image tiles, table heads)
and a viewer with Plotly, a Canvas2D image view with WCS readout, and Arrow tables. A
million-point spectrum previews in 10 ms.

**The rbcodes packs.** `launch_specgui`'s equivalent-width pipeline, `rb_zfind`'s five redshift
search methods, `rb_multispec`'s stacked viewer with its keyboard, and `rb_ifuview`'s cube
collapses, apertures and moment maps — all as headless nodes that call rbcodes where it imports
and a vendored copy of the same kernel where it does not, checked against each other at
`rtol=1e-9`. Six interactive editors (continuum masks, velocity range, line picker, z-accept,
multi-spectrum viewer, aperture drawer) replace the matplotlib canvases, and four workflow
templates open straight into a working graph.

**App modes.** Star a parameter, pin a preview, and the same document renders as a form (App), a
step-by-step Wizard, or a Dashboard of linked views where a range dragged on a spectrum highlights
the matching rows of a table fed by it. The layout lives in the URL.

**Batch mode.** A workflow over a table of rows, with concurrency, continue-on-error, cache reuse
between rows that share a prefix, specgui's batch CSV as an import format, and CSV/ECSV export.

**Packs and bundles.** A pack manager that shows the uv resolution diff before it touches
anything, refuses a plan that conflicts with the app's pins, snapshots the environment before
every install and rolls back exactly; a git-backed registry index; `.acw` bundles carrying the
document, the lock, the input hashes, the results and the figures; and a Python code node with
ports you declare, whose snippets stay quarantined until you have read them.

**Distribution.** A CLI that is the whole app (`serve`, `open`, `run`, `workspace`, `pack`,
`bundle`, `doctor`), one-line installers for macOS/Linux/Windows, click-to-run launchers built
with PyApp, a Docker Compose lab server with user accounts behind Caddy with one private workspace
per person, and a documentation site.

**Accessibility.** WCAG 2.1 AA with zero serious or critical axe-core violations across the shell,
the library, the inspector, the drawer, the palette, the panels, the gallery, all four app modes,
an editor and the viewer. The absorption wizard completes with the keyboard alone;
`prefers-reduced-motion` is honoured; the port palette is Okabe–Ito with a glyph per type, checked
under protanopia, deuteranopia and tritanopia.

### Known limitations

- **LLS and Voigt profile fitting** (`IGM.LLSFitter`, `LLSVoigtFitter`), **`rb_align`** and
  **`rb_zgui`** are not ported. See [coming from rbcodes](docs/migrating/index.md).
- **Nothing is signed.** Windows SmartScreen and macOS Gatekeeper will warn about the
  click-to-run installers; the workarounds are in the install pages.
- **A lab server is sized by its concurrent users**: each account's engine (cache, thread pool
  and, after its first expensive node, a process pool) lives until the process restarts.
- **The code node's sandbox is a denylist**, not a jail. The trust gate is the real protection.
- **`core.list.collect` takes four inputs**: the SDK has no variadic input ports yet, so a stack
  of ten spectra means chaining collects.
- **English only**, though every string goes through `t()`.

[Unreleased]: https://github.com/lblogan14/astro-canvas/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lblogan14/astro-canvas/releases/tag/v0.1.0
