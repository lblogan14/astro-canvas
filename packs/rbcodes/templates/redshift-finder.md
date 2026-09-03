# Redshift Finder

The rbcodes `rb_zfind` engine as an Astro Canvas workflow: four search methods, score curves with
ranked candidates, and an interactive acceptance step that produces a `Redshift`.

Two bundled SDSS spectra are searched. The star-forming galaxy `spec-0398-51789-0282.fits`
(SDSS pipeline z = 0.00586) goes through the weighted **Picket Fence**, the plain **Line Search**
and a MARZ **Template Search** with the `zfind_galaxy` curated line list; the quasar `sdss1.fits`
(z = 3.0133) through the picket fence with `zfind_qso`. A **PCA Search** on the galaxy is wired
in as an expensive node: press Run on it to watch the process-pool path report progress.

| Step | Node | Editor |
|---|---|---|
| Load the spectra | `core.io.load_spectrum` | Workspace picker |
| Line list | `rbcodes.zfind.curated_linelist` | preset (`zfind_em`, `zfind_stellar`, `zfind_igm`, `zfind_galaxy`, `zfind_qso`) |
| Searches | `rbcodes.zfind.picket_fence_search`, `line_search`, `template_search`, `pca_search` | score/chi-square curve with candidate markers (`zfind-curve` preview) |
| Accept | `rbcodes.zfind.rank` | **z-accept**: click a candidate on the curve, see the lines overlaid on the spectrum at that z, Apply writes `accepted` |
| Use it | `rbcodes.absorption.set_redshift` | the `redshift` port overrides the node's `z` |

Expected result with the template parameters: every galaxy search puts its best candidate within
0.002 of z = 0.00586 (picket fence 0.00567, line search 0.00534, template 0.00601); the QSO picket
fence gives z = 3.008 (broad lines, 20 A instrument FWHM). Curves for the line-based methods are
negative scores (minima = best z); templates and PCA give reduced chi-square.
