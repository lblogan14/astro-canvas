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

## Phase 06: redshift finding (`rb_zfind` as a workflow)

| Node | rbcodes | Notes |
|---|---|---|
| `rbcodes.zfind.curated_linelist` | `GUIs.zfind.linelists` | the five presets with `weight`/`kind` columns |
| `rbcodes.zfind.line_search`, `absorber_search` | `GUIs.zfind.engine.line_search` | emission mode -> `ZFindResult`; absorption mode -> `AbsorberResult` |
| `rbcodes.zfind.picket_fence_search` | `GUIs.zfind.engine.picket_fence_search`, `picket_fence.PicketFenceZ` | weighted matched filter, Mode A/B |
| `rbcodes.zfind.template_search`, `multi_template_search` | `GUIs.zfind.engine.template_search` | bundled MARZ templates (`kernels/zfind_templates/marz`) |
| `rbcodes.zfind.pca_search`, `multi_pca_search` | `GUIs.zfind.engine.pca_search` | bundled redrock eigenvectors (`kernels/zfind_templates/pca`); `cost="expensive"`, progress, cancel |
| `rbcodes.zfind.rank` | `GUIs.zfind.adapters` | up to four scans -> `Redshift` + `ZCandidates`; editor **z-accept** |
| `rbcodes.zfind.absorbers_to_catalog` | `GUIs.zfind.adapters.absorbers_to_multispec` | `Table` of accepted absorbers |

Port types `rbcodes.ZFindResult`, `rbcodes.AbsorberResult`, `rbcodes.ZSolution`, `rbcodes.ZCandidates`
(`astro_canvas_rbcodes/types.py`). Template: `templates/redshift-finder.acw` (SDSS galaxy at z = 0.0059 and
quasar at z = 3.01). The kernels are ports of `GUIs/zfind/{engine,picket_fence,linelists,adapters}.py`;
`tests/packs/rbcodes/test_zfind_matches_rbcodes.py` asserts 1e-9 agreement where rbcodes is importable and
`fixtures/reference_zfind.json` (from `generate_reference_zfind.py`) pins rbcodes' numbers for the 3.12 tests.

## Phase 07: multi-spectrum viewing and line identification (`rb_multispec` as a workflow)

| Node | rbcodes | Notes |
|---|---|---|
| `rbcodes.multispec.view` | `GUIs.multispecviewer.multispec` | interactive: stacks a `SpectrumCollection`, holds the absorber catalogue and the identified lines in its parameters; outputs both as tables plus a `MultispecView`; editor **multispec-viewer** |
| `rbcodes.multispec.absorber_catalog` | `AbsorberManager` | any catalogue -> `Zabs`/`LineList`/`Color`/`Visible`, colours from `rb_utility.rb_set_color` |
| `rbcodes.multispec.export_linelist`, `import_linelist` | `io_manager` | the fixed-width `txt`, the `csv` and the combined `MultispecViewer` JSON |
| `rbcodes.multispec.reconcile_linelists` | `utils.reconcile_linelists` | merge several sessions' identifications within a velocity threshold |
| `rbcodes.multispec.quick_fit` | `LineFitter.fit_gaussian`, `fit_com` | two-anchor continuum, emission/absorption from the residual's sign |
| `rbcodes.multispec.vstack` | `vStack` | one velocity panel per transition inside the spectrum |

Port type `rbcodes.MultispecView` (renderer `multispec-thumb`). Template:
`templates/multi-spectrum-viewer.acw` (three SDSS spectra, the zfind absorber search seeding the
catalogue, the z = 1.3855 MgII doublet pre-identified). `LineFitter` and `io_manager` are Qt-free
upstream, so the nodes call them directly when rbcodes is installed; `kernels/line_fit.py` and
`kernels/multispec_io.py` are the ports used otherwise, and `tests/packs/rbcodes/test_multispec_io.py`
asserts that rb_multispec's own reader opens what `export_linelist` writes.

### rbcodes or the vendored kernels

`rbcodes` still pins `python_requires <3.11`, so it installs only on Python 3.10 (the marker in
`pyproject.toml`). When it is importable the nodes call it; otherwise they use the line-by-line ports in
`astro_canvas_rbcodes/kernels/` (`compute_EW`, `rb_setline` with the bundled `lines/`, `rb_iter_contfit`,
`fit_continuum_full_spec`, `rb_specbin`, `compute_SNR_1d`, the `rb_zfind` engine, `LineFitter`,
`io_manager` and `utils.reconcile_linelists`; MIT, from rbcodes 2.4.0 @ `4499012`). Every output
records which backend ran in `meta["rbcodes"]`. `backend/tests/packs/rbcodes/test_kernels_match_rbcodes.py`
asserts that both agree to 1e-9 on identical arrays; `test_absorption_pipeline.py` compares the nodes with
reference values produced by rbcodes itself (`fixtures/reference_ew.json`, regenerate with
`fixtures/generate_reference.py` in a 3.10 environment). Sample data lives in `sample_data/` (see `SOURCES.md`).
See `docs/dev/rbcodes-compat.md` for the Python 3.12 compatibility status.
