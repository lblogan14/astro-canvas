# Multi-Spectrum Viewer

The rbcodes `rb_multispec` viewer as an Astro Canvas workflow: many spectra stacked on a shared
wavelength axis, line lists overlaid at a redshift, an absorber catalogue you build by hand or
seed from a search, click-to-identify line identifications, quick line fits, and exports in
rb_multispec's own file formats.

Three bundled SDSS spectra are stacked: the quasars `sdss1.fits` (z = 3.0133, with the well-known
z = 1.3855 MgII absorber) and `sdss2.fits`, plus the star-forming galaxy
`spec-0398-51789-0282.fits`. The **Absorber Search** scans the first quasar with the `zfind_igm`
list and its top three candidates are turned into absorber-manager rows that seed the viewer.

| Step | Node | Editor |
|---|---|---|
| Load and stack | `core.io.load_spectrum`, `core.list.collect` | Workspace picker |
| Find absorbers | `rbcodes.zfind.absorber_search`, `absorbers_to_catalog` | `zfind-curve` preview |
| Absorber rows | `rbcodes.multispec.absorber_catalog` | normalises to `Zabs`/`LineList`/`Color`/`Visible` |
| Look and identify | `rbcodes.multispec.view` | **multispec-viewer**: pan, toggle lists, add systems, identify lines, quick fits |
| Export | `rbcodes.multispec.export_linelist` | `txt`, `csv` or the MultispecViewer JSON |
| Velocity stack | `rbcodes.multispec.vstack` | one panel per transition of the system |
| Quick fit | `rbcodes.multispec.quick_fit` | the `g`/`c` fit as a reproducible node |

The viewer node is *interactive*: its `catalog` and `identifications` parameters hold the tables
you edit, and Apply writes them back, so the two table outputs are the catalogues you built. The
template ships with the MgII 2796/2803 doublet of the z = 1.3855 system already identified so the
export has rows before you touch anything.

## Keyboard shortcuts in the editor

Parity with `rb_multispec` where it makes sense on a web canvas (the full list is in
`docs/guide/multispec.md`): `r` reset, `x`/`X` set the left/right wavelength limit, `t`/`b` the
top/bottom flux limit of the hovered panel, `a`/`A` autoscale all/one panel, `[`/`]` page left and
right, `o` zoom out, `S`/`U` more/less boxcar smoothing, `L` labels, `Z` swap back to the previous
redshift, `A` add an absorber at the current redshift, `v` the velocity stack, `g`+`g` a Gaussian
fit and `c`+`c` a centre-of-mass fit between two cursor anchors, and `1`, `2`, `4`, `6`, `8`, `C`,
`M`, `F` for the Lya, Lyb, SiIV, OVI, NeVIII, CIV, MgII and FeII quick identifications.

## Output

`outputs/multispec-lines.json` is the combined MultispecViewer document
(`metadata.application_name = "MultispecViewer"`, version 1.5.0) holding the line list, the
absorber systems and the spectrum file names. `rbcodes.GUIs.multispecviewer.io_manager` loads it
unchanged; `backend/tests/packs/rbcodes/test_multispec_io.py` asserts that against the installed
rbcodes.
