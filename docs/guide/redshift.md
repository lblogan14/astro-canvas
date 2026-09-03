# Redshift finding (phase 06)

The rbcodes pack turns the `rb_zfind` engine into nodes: four search methods that scan a redshift
grid and return a curve with ranked candidates, a **Rank and Accept** node whose `z-accept`
editor turns a candidate into a `Redshift`, and an absorber catalogue for QSO sightlines. As in
phase 05, the searches call rbcodes when it is installed and otherwise the vendored ports of the
same code (`packs/rbcodes/src/astro_canvas_rbcodes/kernels/zfind.py`, `picket_fence.py`,
`zfind_linelists.py`); `meta["rbcodes"]` on every result records which backend ran.

## Start from the template

Open the **Workflows** panel, expand **Templates** and press **Use** on *Redshift Finder*. It loads
two bundled SDSS spectra: the star-forming galaxy `spec-0398-51789-0282.fits` (pipeline
z = 0.00586) and the quasar `sdss1.fits` (z = 3.0133). The galaxy is searched three ways (picket
fence, line search, MARZ template) with the `zfind_galaxy` curated list; the quasar with the picket
fence and `zfind_qso`. All of these are `auto`-cost nodes and run when the workflow opens; the
**PCA Search** on the galaxy is expensive and waits for Run. Every galaxy search lands within
0.002 of the pipeline redshift; the QSO picket fence gives 3.008.

| Node | rbcodes | Notes |
|---|---|---|
| `rbcodes.zfind.curated_linelist` | `zfind.linelists.get_curated_df` | `zfind_em`, `zfind_stellar`, `zfind_igm`, `zfind_galaxy`, `zfind_qso`; adds `weight`/`kind` columns to `LineList` |
| `rbcodes.zfind.line_search` | `zfind.engine.line_search(mode="emission")` | SNR-like score, minima = best z |
| `rbcodes.zfind.absorber_search` | `zfind.engine.line_search(mode="absorption")` | significance curve, up to 20 ranked absorbers |
| `rbcodes.zfind.picket_fence_search` | `zfind.engine.picket_fence_search`, `PicketFenceZ` | weighted matched filter with per-line sign check; Mode B detect-then-match |
| `rbcodes.zfind.template_search`, `multi_template_search` | `zfind.engine.template_search` | five bundled MARZ templates, reduced chi-square |
| `rbcodes.zfind.pca_search`, `multi_pca_search` | `zfind.engine.pca_search` | DESI redrock eigenvectors; **expensive** (process pool, progress, cancel) |
| `rbcodes.zfind.rank` | `zfind.adapters.zfind_to_multispec_z` | up to four scans in, `redshift` + `candidates` out; editor **z-accept** |
| `rbcodes.zfind.absorbers_to_catalog` | `zfind.adapters.absorbers_to_multispec` | `zabs`/`name`/`label` table for the multi-spectrum viewer (phase 07) |

## Continuum handling

rbcodes fits a BIC-optimal Legendre polynomial when a spectrum has no continuum. Astro Canvas'
SDSS reader stores the pipeline `model` column as `continuum`, and that column already contains
the lines, so subtracting it erases the signal. The search nodes therefore default to
`continuum = "fit"` (ignore the stored array, fit a polynomial like rbcodes does); choose
`"spectrum"` to use a continuum you fitted yourself (for example `rbcodes.continuum.full_spectrum`)
or `"none"` for a zero continuum (rbcodes' `fit_continuum=False`).

## Reading the results

A search returns a `ZFindResult`: the redshift grid, one curve per method or template, up to ten
solutions (`z`, curvature error `z_err`, the statistic value, the method label and the number of
lines or pixels used) and the searched spectrum. Node previews draw the curve with the candidates
marked (`zfind-curve`); the statistic is a negative score for the line-based methods (lower is
better), a reduced chi-square for templates and PCA, and a significance in sigma for absorbers.
`AbsorberResult` carries `candidates` instead of solutions; `absorbers_to_catalog` turns the
accepted ones into a `Table`.

**Rank and Accept** concatenates the solutions of its connected scans in port order (each scan's
own ranking is kept, nothing is re-sorted across methods because their statistics differ) and
numbers them; `accepted` is that row index, `None` meaning the first scan's best. The `redshift`
output feeds `rbcodes.absorption.set_redshift`, whose `Redshift` port overrides its `z` parameter;
the `candidates` output is the table (`candidates-table` preview).

## The z-accept editor

Open it from the pencil-ruler button of a **Rank and Accept** node. The top plot shows the curve
of the scan currently in view (tabs switch between connected scans; multi-template results
overlay their curves) with the candidates marked, the selected one in orange. Click near a
candidate on the curve or click a row in the table to select it; hovering a row previews its
redshift. The bottom plot is the searched spectrum with the continuum and a curated line list
overlaid at the previewed/selected redshift (emission lines green, absorption red, labelled with
the transition names); the list defaults to the scan's own preset when it used one and can be
changed. The side panel shows `z ± z_err`, the statistic value, the method and the feature count.
**Apply** writes `accepted` as one undo step; downstream nodes re-run automatically.

## Reference values

`backend/tests/packs/rbcodes/fixtures/reference_zfind.json` holds what rbcodes' own engine returns
for the sample spectra (generated by `generate_reference_zfind.py` in a Python 3.10 environment
where rbcodes installs, with a flat median continuum so the comparison does not depend on the
polynomial fitter's version); `test_zfind_nodes.py` compares the nodes against it and checks
known-redshift recovery. `test_zfind_matches_rbcodes.py` runs where rbcodes is importable and
asserts the vendored kernels agree with it to 1e-9 on identical arrays, including the synthetic
spectra of rbcodes' own `test_zfind_engine_*` suites.
