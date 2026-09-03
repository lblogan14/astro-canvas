# Absorption-line measurements (phase 05)

The rbcodes pack turns the `launch_specgui` pipeline (`rb_spec`) into nodes: load a spectrum, shift
it to the absorber rest frame, pick a transition, slice a velocity window, fit a masked continuum,
measure the equivalent width and save an `rb_spec` JSON that rbcodes can open again. Every
numerical step calls rbcodes when it is installed and otherwise the vendored copies of the same
functions (`packs/rbcodes/src/astro_canvas_rbcodes/kernels/`); the numbers are the same and every
output records which one ran in `meta["rbcodes"]`.

## Start from the template

Open the **Workflows** panel, expand **Templates** and press **Use** on *Absorption Line
Measurement*. The template loads the bundled SDSS quasar `sdss1.fits` (z = 3.01), shifts to the
intervening MgII absorber at z = 1.3855, slices +/- 1500 km/s around MgII 2796, fits a Legendre
continuum with two masks (the two MgII doublet members), measures W over +/- 200 km/s and writes
`outputs/sdss1_MgII2796_z1.3855.json`. All nodes are cheap, so the graph runs as soon as it opens
(W = 2.071 A, log N = 13.99 with rbcodes 2.4.0). Templates come from packs: `GET /api/templates`
lists them and `POST /api/templates/{id}/instantiate` creates a fresh workflow (`meta.template`
records the origin).

| Node | rbcodes | Editor |
|---|---|---|
| `rbcodes.absorption.set_redshift` | `shift_spec` | – (a `Redshift` port overrides `z`) |
| `rbcodes.absorption.set_transition` | `rb_setline` | **Line picker** |
| `rbcodes.absorption.slice` | `slice_spec` | **Range** (vmin/vmax handles) |
| `rbcodes.continuum.fit` | `fit_continuum`, `rb_iter_contfit`, `fit_optimal_polynomial` | **Continuum masks** |
| `rbcodes.absorption.compute_ew` | `IGM.compute_EW` | – (key/value tile: W, W_e, N, log N, centroid) |
| `rbcodes.absorption.doublet_check` | `plot_doublet` | – (Plotly figure) |
| `rbcodes.absorption.save_rbspec_json` / `load_rbspec_json` | `save_slice` / `load_rb_spec_object` | – |
| `rbcodes.continuum.full_spectrum` | `fit_quasar_continuum` | – (expensive: press Run) |
| `rbcodes.lines.line_list` / `find_transition` | `read_line_list` / `rb_setline` | – |

## Editors

Nodes with an editor show a pencil-ruler button in their header (also in the node menu and in the
Inspector). Editors open as a centred modal by default; the **Dock right** button in the editor
header switches to a sheet on the right, and the choice is remembered in the browser. Every editor
works on the node's *input* (a full-resolution slice requested with the `editor` tag, so node
thumbnails are untouched) and writes back to the node's parameters with **Apply** as one undo
step. Nothing is committed until you press Apply.

**Continuum masks** (`rbcodes.continuum.fit`): the velocity slice with the current masks shaded.
Drag horizontally to add a mask, click a shaded band to remove it, or type a range and press Add.
Every change asks the server to run the node body with the candidate parameters
(`preview.compute`; the fit takes about 20 ms) and overlays the fitted continuum; the BIC-per-order
table lists the scan, the best order in bold, and clicking a row pins that order. Apply writes
`masks`, `order`, `method` and `optimize_order`; downstream nodes re-run automatically.

**Range** (`rbcodes.absorption.slice`, `compute_ew`): the spectrum in velocity around the node's
transition with two orange handles for vmin/vmax (drag them or type the values). Apply writes
`vmin`/`vmax`.

**Line picker** (`rbcodes.absorption.set_transition`): the rest-frame spectrum; click a feature to
list the nearest transitions of the chosen rbcodes line list (loaded through the server, nothing
is duplicated in the browser), pick one, and known doublet partners (MgII, CIV, SiIV, NV, OVI,
AlIII, FeII) are marked so you can check the second member. Apply writes `wrest`, `linelist` and
`method=closest`.

## Files rbcodes can read

`Save rb_spec JSON` writes exactly the `rb_spec.save_slice` document: `zabs`, `linelist`, `trans`,
`fval`, `trans_wave`, `vmin`/`vmax`, `W`, `W_e`, `N`, `N_e`, `logN`, `logN_e`, velocity centroid and
dispersion, the slice arrays (`wave_slice`, `flux_slice`, `error_slice`, `velo`, `cont`, `fnorm`,
`enorm`, `Tau`), `continuum_masks`, `continuum_fit_params` and `metadata` with the rbcodes version.
Flux, error and continuum are divided by the median flux of the full spectrum, as `rb_spec` does
when it loads a file, so `launch_specgui analysis.json` and `load_rb_spec_object` open the file
unchanged. `Load rb_spec JSON` reads such files back into a slice, a continuum and a measurement;
`core.io.load_spectrum` also accepts them.

## Numbers

`backend/tests/packs/rbcodes/fixtures/reference_ew.json` holds W, W_e, N, log N and velocity
centroids computed by rbcodes 2.4.0 itself on the sample data (four cases: MgII 2796 and 2803,
FeII 2600 with a fixed order, and a weighted fit with SNR). The pipeline reproduces them to better
than 2e-4 relative; the only difference is that rbcodes keeps the SDSS wavelength grid in float32.
On identical float64 arrays the vendored kernels agree with rbcodes to 1e-9
(`test_kernels_match_rbcodes.py`, run where rbcodes is importable). The rbcodes test suite itself
accepts 5 % on W and 0.3 dex on log N.
