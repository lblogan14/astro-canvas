# Migrating from `rb_zfind`

`rb_zfind` is one window: a spectrum, a line list, a method, a redshift curve, and a table of
candidates you click through until one of them is right. Astro Canvas ships it as the
**redshift-finder** template with a **Dashboard** layout — because the thing you were doing was
looking at four panels at once, not stepping through them.

Open **Workflows ▸ Templates ▸ Redshift Finder ▸ Use**, or from the gallery press **Open** and it
lands in Dashboard mode.

## Method by method

| `rb_zfind` | Node | Notes |
|---|---|---|
| Line search (emission) | `rbcodes.zfind.line_search` | `engine.line_search(mode="emission")`; the SNR-like score, minima are the candidates |
| Line search (absorption) | `rbcodes.zfind.absorber_search` | `engine.line_search(mode="absorption")`; a significance curve and up to 20 ranked absorbers |
| Picket fence | `rbcodes.zfind.picket_fence_search` | `engine.picket_fence_search` and `PicketFenceZ`, including Mode B (detect, then match) |
| Template (MARZ) | `rbcodes.zfind.template_search`, `multi_template_search` | the same five bundled MARZ templates, reduced chi-square |
| PCA (redrock) | `rbcodes.zfind.pca_search`, `multi_pca_search` | the DESI eigenvectors; **expensive**, so it runs in a worker process with progress and cancel |
| The curated line lists | `rbcodes.zfind.curated_linelist` | `zfind_em`, `zfind_stellar`, `zfind_igm`, `zfind_galaxy`, `zfind_qso` — the same five, with `weight` and `kind` columns |
| The candidate table and its Accept | `rbcodes.zfind.rank` + the **z-accept** editor | `adapters.zfind_to_multispec_z` |
| Export absorbers for the multi-spectrum viewer | `rbcodes.zfind.absorbers_to_catalog` | `adapters.absorbers_to_multispec` |

## Running more than one method at once

This is the change worth the migration. In `rb_zfind` a method is a radio button: you pick one,
look, pick another, and hold the comparison in your head. Here every method is a node, so all of
them run on the same spectrum at the same time and **Rank and Accept** takes up to four of them
as inputs. The template does exactly that for the galaxy: picket fence, line search and MARZ
template side by side, with the PCA search wired in and waiting for **Run** because it is the
expensive one.

The candidates from every connected scan are concatenated in port order and numbered. They are
*not* re-sorted across methods — the statistics are a negative score, a reduced chi-square and a
significance in sigma, and ordering those against each other would be arithmetic with no meaning.
Each scan's own ranking is kept.

## The z-accept editor is the candidate table

Open it from the **Rank and Accept** node. What `rb_zfind`'s window showed in two panels, it shows
in two panels:

- the **curve** of whichever scan is in view, tabs to switch between the connected scans,
  candidates marked, the selected one in orange;
- the **spectrum** underneath with the continuum and a curated line list drawn at the selected
  redshift — emission green, absorption red, labelled — so "is this real" is the same visual check
  it always was.

Click a candidate on the curve or a row in the table; hovering a row previews its redshift without
committing. The side panel gives `z ± z_err`, the statistic, the method and how many lines or
pixels went into it. **Apply** writes `accepted`, and *everything downstream re-runs* — which is
the part `rb_zfind` could not do.

## What downstream means

`rank`'s `redshift` output is a `Redshift` port, and `rbcodes.absorption.set_redshift` takes one.
Wire them together and an absorption-line measurement follows the redshift you just accepted:
change your mind about the candidate, and the equivalent width, the continuum fit and the saved
JSON all update. The same output feeds the multi-spectrum viewer's absorber catalogue.

## Continuum handling differs, once

rbcodes fits a BIC-optimal Legendre polynomial when a spectrum carries no continuum. Astro
Canvas' SDSS reader stores the pipeline `model` column as the spectrum's `continuum`, and that
column *already contains the lines* — subtracting it erases the signal you are searching for.

So the search nodes default to `continuum = "fit"`: ignore the stored array and fit a polynomial,
which is what rbcodes does. Set `"spectrum"` to use a continuum you fitted yourself (from
`rbcodes.continuum.full_spectrum`, say) and `"none"` for a zero continuum, which is rbcodes'
`fit_continuum=False`.

One known consequence, recorded rather than hidden: `template_search` with the MARZ **QSO**
template does not recover the z = 3.01 quasar in `sdss1.fits`. The BIC polynomial continuum
flattens the broad lines and `data_norm="normalize"` divides them out. rbcodes gives the same
numbers on the same input, so this is the template's behaviour and not the port's — the
redshift-finder template therefore uses the picket fence for the quasar.

## What you gain

**The scan is a document.** Which spectrum, which list, which grid, which method, which candidate
you accepted: all in one `workflow.json`, re-runnable and shareable. The `.acw` bundle adds the
input hashes and the resolved package versions.

**Four hundred spectra.** Promote the input path and switch to Batch mode: one row per spectrum,
the accepted redshift and its error as collected columns, exported as ECSV. `astro-canvas run`
does it without a browser.

**Cancel actually works.** The PCA search runs in a worker process; pressing Cancel kills it. In
`rb_zfind` a long redrock scan owned the event loop.

## What is different

**No Update button** — nodes re-run on their own when something they depend on changes. The
expensive PCA node is the exception and waits for **Run**, along with anything downstream of it.

**`pca_search` always uses the vendored kernel**, even where rbcodes is importable, because the
kernel is what reports progress and honours cancellation. `rbcodes.engine.pca_search` is still
exercised by the comparison test at `rtol=1e-9`, so the numbers are checked against it.

**The 16 atomic line lists** (`rbcodes.lines.line_list`) are a separate node from the five curated
zfind presets. The z-accept editor's overlay currently offers the five presets; the atomic lists
are available to the search nodes and to the multi-spectrum viewer.
