# Absorption Line Measurement

The rbcodes `launch_specgui` pipeline as an Astro Canvas workflow. It reproduces the canonical
`rb_spec` sequence (`from_file -> shift_spec -> slice_spec -> fit_continuum -> compute_EW ->
save_slice`) on the bundled SDSS quasar `sdss1.fits`, which has an intervening MgII absorber at
z = 1.3855 (MgII 2796/2803 and FeII 2600 are all detected).

| Step | Node | Editor |
|---|---|---|
| Load the spectrum | `core.io.load_spectrum` | Workspace picker |
| Absorber redshift | `rbcodes.absorption.set_redshift` | plain parameter (or a `Redshift` port) |
| Transition | `rbcodes.absorption.set_transition` | **line-picker**: click a feature, pick the nearest transition, see doublet partners |
| Velocity slice | `rbcodes.absorption.slice` | **range-select**: drag the window handles |
| Continuum | `rbcodes.continuum.fit` | **continuum-mask**: drag to add mask ranges, live BIC table, Apply writes `masks`/`order`/`method` |
| Measurement | `rbcodes.absorption.compute_ew` | key/value tile (W, W_e, N, logN, velocity centroid) |
| Export | `rbcodes.absorption.save_rbspec_json` | writes `outputs/*.json`, loadable by `launch_specgui` |

Expected result with the template parameters (rbcodes 2.4.0): W = 2.071 A, W_e = 0.084 A,
log N = 13.986 for MgII 2796 over +/- 200 km/s, BIC-optimal Legendre order 1.

## Batch layout (`launch_specgui -b`)

The template ships a `layouts.batch` definition, so switching the toolbar layout to **Batch**
opens a table whose columns are the promoted parameters, keeping specgui's separation between the
velocity window that is *sliced out* (`slice_vmin`/`slice_vmax`) and the *integration limits*
(`ew_vmin`/`ew_vmax`):

| Column | Parameter |
|---|---|
| `filename` | `load.path` |
| `redshift` | `redshift.z` |
| `transition`, `linelist`, `method` | `transition.wrest`, `.linelist`, `.method` |
| `slice_vmin`, `slice_vmax` | `slice.vmin`, `slice.vmax` |
| `ew_vmin`, `ew_vmax` | `ew.vmin`, `ew.vmax` |

`ew.out` is collected, so each result row carries `W`, `W_e`, `N`, `N_e`, `logN`, `logN_e`,
`vel_centroid`, `vel_disp` and `SNR` next to `status`, `error_message` and
`calculation_timestamp`. `samples/rbcodes/absorption_batch.csv` holds 20 ready-made rows (the
MgII doublet over ten integration windows); a specgui batch CSV or `master_batch_table` JSON
export imports with the same column names and maps itself onto these nodes.
