# astro-canvas-rbcodes

Node pack exposing [rbcodes](https://github.com/rongmon/rbcodes) (Rongmon Bordoloi) as Astro Canvas nodes.
Registers through the `astro_canvas.nodes` entry point `rbcodes`. Importing the package pins `MPLBACKEND=Agg` and
never imports `rbcodes` itself (Qt side effects); node modules import it lazily inside the node functions.

## Phase 05: absorption-line equivalent widths (`launch_specgui` as a workflow)

| Node | rbcodes | Notes |
|---|---|---|
| `rbcodes.lines.line_list`, `rbcodes.lines.find_transition` | `IGM.rb_setline` | the 16 bundled line lists (`atom`, `LLS`, `DLA`, ...) as `LineList`, lookup by closest/exact wavelength or name |
| `rbcodes.absorption.set_redshift` | `rb_spec.shift_spec` | observed -> rest frame; accepts a `Redshift` port |
| `rbcodes.absorption.set_transition` | `rb_setline` | editor **line-picker** |
| `rbcodes.absorption.slice` | `rb_spec.slice_spec` | velocity slice (`frame="velocity"`, `v0_wrest`); editor **range-select** |
| `rbcodes.continuum.fit` | `rb_iter_contfit`, `fit_optimal_polynomial`, `rb_spec.fit_continuum` | masked Legendre fit, BIC order scan, weights, plus `spline`/`flat`/`ransac`; editor **continuum-mask**; outputs `continuum` and `normalized` |
| `rbcodes.continuum.full_spectrum` | `fit_continuum_full_spec.fit_quasar_continuum` | chunked, blended continuum of a whole spectrum (`cost="expensive"`, progress per chunk) |
| `rbcodes.absorption.compute_ew` | `IGM.compute_EW` | `EWMeasurement` (W, N, log N, velocity centroid, saturation flag, optional SNR) |
| `rbcodes.absorption.doublet_check` | `rb_spec.plot_doublet` | two-panel Plotly figure |
| `rbcodes.absorption.save_rbspec_json`, `load_rbspec_json` | `rb_spec.save_slice`, `load_rb_spec_object` | the exact `save_slice` JSON schema, loadable by `launch_specgui` |

Template: `templates/absorption-line-measurement.acw` (SDSS quasar `sdss1.fits`, MgII 2796 at z = 1.3855),
served through `GET /api/templates` and the Workflows panel.

### rbcodes or the vendored kernels

`rbcodes` still pins `python_requires <3.11`, so it installs only on Python 3.10 (the marker in
`pyproject.toml`). When it is importable the nodes call it; otherwise they use the line-by-line ports in
`astro_canvas_rbcodes/kernels/` (`compute_EW`, `rb_setline` with the bundled `lines/`, `rb_iter_contfit`,
`fit_continuum_full_spec`, `rb_specbin`, `compute_SNR_1d`; MIT, from rbcodes 2.4.0 @ `4499012`). Every output
records which backend ran in `meta["rbcodes"]`. `backend/tests/packs/rbcodes/test_kernels_match_rbcodes.py`
asserts that both agree to 1e-9 on identical arrays; `test_absorption_pipeline.py` compares the nodes with
reference values produced by rbcodes itself (`fixtures/reference_ew.json`, regenerate with
`fixtures/generate_reference.py` in a 3.10 environment). Sample data lives in `sample_data/` (see `SOURCES.md`).
See `docs/dev/rbcodes-compat.md` for the Python 3.12 compatibility status.
