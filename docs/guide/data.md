# Data and visualization (phase 04)

Astro Canvas works on a **workspace folder** on the machine that runs the server (by default
`<Documents>/AstroCanvas`). Everything a workflow reads or writes lives inside it: uploads, sample
data, archive downloads and node outputs. Paths in node parameters are always workspace-relative;
absolute paths, `..` and symlinks are refused by the server.

## The Workspace panel

Open it with the folder button in the toolbar (next to *Workflows*).

| Action | How |
|---|---|
| Browse | Folders load lazily when expanded; hidden folders (`.astro-canvas`) stay hidden. |
| Add a file to the canvas | Drag a file onto the canvas, double-click it, or select it and press **Add to canvas**. The server sniffs the file (FITS headers, table columns, JSON keys) and creates the matching loader node with `path` set: `Load Spectrum`, `Load Image`, `Load Cube` or `Load Table`. Unknown files get a `Load Table` node and a warning. |
| Upload | **Upload files** (multiple), or drop files from your desktop onto the panel or the canvas (canvas drops also create loader nodes). Files above 100 MB are sent in 32 MB chunks; progress shows in the panel. Uploads land in the selected folder (default `uploads/`). |
| New folder, refresh, download, delete | Buttons in the panel header and the per-file menu. |
| Switch workspace | The ⋯ menu in the panel header: type an absolute path (created when missing) or pick a recent workspace. Switching closes the open workflows; the page reloads on the new workspace. |

The `File` widget on loader nodes (the folder icon next to the path box) opens the same tree as a
picker. External changes to the folder are picked up by a file watcher and the tree refreshes.

### Sample data

On first start the server copies the bundled sample files of every installed pack into
`<workspace>/samples/<pack>/`. The rbcodes pack ships three SDSS spectra, the rbcodes
multi-extension `test.fits`, `galaxy1.fits`, an ASCII spectrum, and two synthetic files generated
for Astro Canvas: an image with a rotated TAN WCS and a small KCWI-style cube with its variance
sidecar (see `packs/rbcodes/sample_data/SOURCES.md`).

## Loader nodes (`core.io.*`)

| Node | Reads | Notes |
|---|---|---|
| `Load Spectrum` | FITS binary tables (SDSS `COADD`, HSLA, JWST `x1d`, generic `WAVE/FLUX/ERROR` columns), multi-extension `FLUX/ERROR/WAVELENGTH/CONTINUUM` (the rbcodes layout), header-WCS 1-d arrays (with `DC-FLAG`/log axes and sidecar error files), SDSS `spSpec` rows, DESI bricks and camera coadds, ECSV/ASCII tables, rb_spec JSON | `format` forces a parser; wavelengths are converted to Angstrom when the unit is known. When the `rbcodes` distribution is importable its `rb_spectrum` readers run first (`use_rbcodes`). |
| `Load Table` | FITS tables, ECSV, CSV/ASCII, VOTable, JSON rows/columns | Multi-dimensional columns are skipped and listed in `meta.skipped_columns`. |
| `Load Image` | 2-d FITS (first 2-d HDU, or `ext`) | Header and WCS travel as plain dicts. Cost `auto`. |
| `Load Cube` | 3-d FITS: generic, KCWI (`*_icube*.fits` + `*_vcube*.fits` variance), MUSE (`DATA`/`STAT`), MaNGA (`FLUX`/`IVAR`/`WAVE`) | Wavelength axis from `WAVE` extensions or `CTYPE3`/`CD3_3`, converted to Angstrom. Cost `auto`. |
| `Save Spectrum`, `Save Table`, `Save JSON` | write into the workspace (FITS/ECSV/JSON/CSV; ECSV/CSV/FITS/VOTable/JSON) | Return a `File` value (path, size, blake3). |

Loader nodes carry a **fingerprint** of the file (mtime and size), so replacing a file re-runs
everything downstream on the next edit or Run.

## Spectrum tools and plots

`Rebin`, `Smooth` (boxcar/Gaussian, NaN-aware), `Air to Vacuum` (rbcodes formula), `Normalize`
(by a `Continuum` port or the spectrum's own continuum), `Signal-to-Noise`, plus `Plot Spectrum`,
`Plot Image` and `Plot Table` (Plotly figures) and `Export Figure` (Plotly JSON or a standalone
HTML page; PNG only for PNG figures).

## Archive fetch nodes (`core.fetch.*`)

`Fetch SDSS Spectrum` (by plate/MJD/fiber or the nearest object to RA/Dec), `Resolve Name
(SIMBAD)`, `VizieR Cone Search` and `MAST Observation Search` talk to the archives' public
endpoints and cache every reply in `<workspace>/downloads/<service>/` keyed by a hash of the
query, so re-running a workflow offline reuses the files. They are *expensive* nodes: they wait
for **Run**. The core pack declares `security = "needs-network"` for them.

## Previews and the viewer

Every finished node shows an inline preview picked by output type:

| Type | Preview | Expand (⤢) |
|---|---|---|
| `Spectrum1D` | uPlot line with error band and continuum, decimated (MinMaxLTTB) to about two points per pixel; re-requested when the node is resized | Plotly (WebGL). Box-zoom asks the server for a re-decimated slice of the visible range (100 ms debounce); double-click resets. Toggle error/continuum, or switch to a velocity axis around a rest wavelength. |
| `Image2D` | zscale-scaled thumbnail | Full-resolution Canvas2D view: zscale / min-max / percentile scaling, linear / asinh / log / sqrt stretch, viridis / gray / magma / cubehelix colour maps, wheel zoom and drag pan, pixel + value + RA/Dec readout (TAN WCS computed client-side). |
| `Cube3D` | White-light image plus the integrated spectrum | Same image view; drag a range on the spectrum to show the white-light image of that band. |
| `Table` | First rows | Sortable grid over the full table (Arrow IPC), with a download link. |
| `Figure` | PNG or a chip | Plotly figure. |
| scalars, `File`, measurements | chip / key-value tile | Key-value tile with the raw payload. |

Summaries are small JSON payloads (≤ 4000 points for spectra, ≤ 512² tiles for images); full
arrays arrive as binary frames decoded into typed arrays, never through `JSON.parse`. At most six
Plotly WebGL contexts are alive at once; older ones pause and can be resumed.
