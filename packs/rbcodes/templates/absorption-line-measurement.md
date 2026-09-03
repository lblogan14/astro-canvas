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
