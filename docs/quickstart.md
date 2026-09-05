# Quick start

Ten minutes, no data of your own needed. Every template below ships with its sample files.

## 1. Open the app

However you [installed it](install/index.md), the entry point is the same:

```sh
astro-canvas open
```

That reuses a server that is already running rather than fighting it for the port, so it is safe
to double-click the shortcut twice. What you get is a browser tab on `http://127.0.0.1:8765`,
authenticated by a token the server generated and put in the URL.

## 2. Run a template

The four templates are the rbcodes GUIs, rebuilt as workflows. Open the gallery
(**Templates** in the toolbar), pick one, and press **Open**:

| Template | The rbcodes tool it replaces | What you get |
|---|---|---|
| **Absorption Line Measurement** | `launch_specgui` | An SDSS quasar shifted to the absorber's rest frame, a continuum fit, equivalent widths and column densities |
| **Redshift Finder** | `rb_zfind` | A star-forming galaxy cross-correlated against templates, with the χ² curve and the best redshift |
| **Multi-Spectrum Viewer** | `rb_multispec` | Three SDSS spectra stacked, with line identifications at a shared redshift |
| **IFU Cube Explorer** | `rb_ifuview` | A KCWI cube collapsed to a white-light image, an aperture spectrum and moment maps |

Each opens straight into the interface it was designed for — a form, a wizard or a dashboard —
rather than dropping you in front of a graph. Press **Show graph** in the toolbar when you want
to see the nodes underneath.

## 3. Change something

Pick a number and change it. The redshift on the multi-spectrum template is a good one:

- Everything downstream of the change goes **dirty** and re-runs after a 250 ms pause.
- Everything else does not. Cache keys come from *content*, so a node whose inputs did not change
  is not recomputed — it is not even re-read from disk.
- Rename a node or drag it somewhere else and **nothing re-runs**: the layout is not part of the
  cache key.

Expensive nodes behave differently on purpose. They go dirty and *wait* — marked **stale**, with
a **Run** button — instead of firing off a fit every time you nudge a slider. See
[cost gating](concepts.md#cheap-expensive-and-auto).

## 4. Look at a result properly

Click the preview on any node to open the full viewer: a Plotly spectrum with server-side
resampling (a million points stay interactive), a Canvas2D image view with WCS readout, or an
Arrow table. The inline preview on the node is a thumbnail of the same output — a hint, not the
result.

## 5. Make it yours

- **Star a parameter** in the Inspector and it appears in the App form.
- **Pin a preview** and it appears in the Dashboard.
- Drag a range on a spectrum in a Dashboard and the table fed by it highlights the matching rows.

The layout lives in the URL, so `/w/<id>/wizard` is a link you can send someone. See
[app modes](guide/modes.md).

## 6. Share it

**Share → Export bundle** writes one `.acw` file next to your data: the document, a dependency
lock, the hash of every input, the cached results, the figures and a per-node provenance record.
Drag it onto anyone else's canvas and they get your workflow — with missing packs and missing
inputs *reported*, not guessed at.

Code nodes inside an imported bundle stay **quarantined** until you have read them. That is the
whole security model for shared code, and it is deliberately in your hands rather than in a
sandbox's. See [bundles](guide/bundles.md) and [code nodes](guide/code-nodes.md).

## 7. Bring your own data

Drop a FITS file onto the canvas. The server sniffs it and offers the loader that fits — spectrum,
image, cube or table — already wired up. Files live in your **workspace**
(`<Documents>/AstroCanvas`), which is also where results, bundles and the cache go.

```sh
astro-canvas workspace list          # where it is
astro-canvas workspace new ~/papers/lya   # start a fresh one for a project
```

## Where next

- [**Concepts**](concepts.md) — the ideas the rest of the docs assume.
- [**The canvas**](guide/canvas.md) — every shortcut and gesture.
- [**Batch mode**](guide/batch.md) — run the same workflow over a table of targets.
- [**Command line**](cli.md) — run workflows headlessly, on a cluster or in a cron job.
