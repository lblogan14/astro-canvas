# Multi-spectrum viewing and line identification (phase 07)

The rbcodes pack turns `rb_multispec` into a canvas experience: a **Multi-Spectrum Viewer** node
that stacks a spectrum collection on a shared wavelength axis, overlays line lists at a redshift,
holds an absorber catalogue and a list of identified lines, and hands both catalogues on as tables.
Around it are the file nodes that read and write rb_multispec's own formats, a reconciliation node
for merging several sessions' line lists, the quick Gaussian / centre-of-mass fitter and a
velocity-stack node. Everything calls rbcodes when it is installed and the vendored ports
(`kernels/line_fit.py`, `kernels/multispec_io.py`) otherwise; `meta["rbcodes"]` records which
backend ran.

## Start from the template

Open the **Workflows** panel, expand **Templates** and press **Use** on *Multi-Spectrum Viewer*. It
stacks three bundled SDSS spectra — the quasars `sdss1.fits` (z = 3.0133, with the well-known
z = 1.3855 MgII absorber) and `sdss2.fits`, and the star-forming galaxy
`spec-0398-51789-0282.fits` — seeds the viewer's absorber catalogue from an **Absorber Search** on
the first quasar, and exports the identified lines as a MultispecViewer JSON document.

| Node | rbcodes | Notes |
|---|---|---|
| `rbcodes.multispec.view` | `multispec.MainWindow` / `SpectralPlot` | interactive: `catalog` and `identifications` parameters hold the tables; outputs `absorbers`, `identified_lines` and a `MultispecView` |
| `rbcodes.multispec.absorber_catalog` | `AbsorberManager` | normalises any catalogue to `Zabs`/`LineList`/`Color`/`Visible`, cycling `rb_utility.rb_set_color` |
| `rbcodes.multispec.export_linelist` | `io_manager.save_line_list` / `save_combined_data` | `txt`, `csv` or the combined JSON |
| `rbcodes.multispec.import_linelist` | `io_manager.load_line_list` / `load_combined_data` | outputs the lines and (JSON only) the absorbers |
| `rbcodes.multispec.reconcile_linelists` | `utils.reconcile_linelists` | merges duplicate identifications within a velocity threshold |
| `rbcodes.multispec.quick_fit` | `LineFitter.fit_gaussian` / `fit_com` | one row: centroid, FWHM, amplitude, direction |
| `rbcodes.multispec.vstack` | `vStack` | one velocity panel per transition of a list that falls inside the spectrum |

## The viewer node

`view` takes a `SpectrumCollection` (`core.list.collect`) and draws one panel per spectrum. Its
other inputs are *seeds*: an `absorber_seed` table (rb_multispec's own columns, or the
`zabs`/`name`/`label` catalogue `rbcodes.zfind.absorbers_to_catalog` produces) and a `line_seed`
table of identifications, used while the corresponding parameter is still empty. Two optional
`LineList` ports add computed lists to the overlay menu, and a `redshift` port overrides the `z`
parameter exactly as in **Set Redshift**.

The node is *interactive*: what you edit in the editor is written back to its `catalog` and
`identifications` parameters, so the two table outputs are the catalogues you built and they
re-run everything downstream. `display` holds the wavelength window, the boxcar smoothing width
and what the panels show; the third output, `view`, is a `rbcodes.MultispecView` carrying the
panels as drawn plus both catalogues, and it renders as the `multispec-thumb` inline preview.

## The multispec-viewer editor

Open it from the pencil-ruler button of a **Multi-Spectrum Viewer** node.

The stack fills the left side: every panel shares the wavelength axis, only the bottom one draws
it, and each panel autoscales its flux to the visible window. Drag horizontally on a panel to run
a quick fit over that range; click a feature to identify the nearest transition of the current
list at the current redshift (it is appended to the table on the right, with the panel's file
name). The toolbar carries:

- the **redshift**, typed or slid, plus a *Use z* button when a `Redshift` is connected;
- the **overlay line list**: rbcodes' 16 atomic lists, the 5 curated zfind presets and anything
  wired into `extra_lines`;
- **Add absorber**, which stores a system at the current redshift with the next colour of
  rb_multispec's palette (tick its checkbox to draw its own list at its own redshift);
- **Gaussian fit** / **CoM fit**, which arm two-click anchoring;
- **Reset view**, the **velocity stack** side panel and the **shortcuts** list.

Line labels are dropped when more than 40 ticks are in view — zoom in to get them back, or press
`L` to switch them off entirely.

**Apply** writes the redshift, the overlay list, both catalogues and the display settings in one
undo step.

### Keyboard shortcuts

Parity with `rb_multispec` where it makes sense in a browser (its `q`, `Y`, `K` and advanced-fit
dialogs have no equivalent here):

| Keys | Action |
|---|---|
| `r` | Reset the view |
| `x` / `X` | Set the left / right wavelength limit at the cursor |
| `t` / `b` | Set the top / bottom flux limit of the hovered panel |
| `a` | Autoscale every panel |
| `A` | Add an absorber system at the current redshift |
| `[` / `]` | Page one window left / right |
| `o` | Zoom out |
| `S` / `U` | More / less boxcar smoothing |
| `L` | Toggle the line labels |
| `Z` | Swap back to the previous redshift |
| `v` | Toggle the velocity stack |
| `g` `g` / `c` `c` | Gaussian / centre-of-mass fit between two cursor anchors |
| `1` `2` `4` `6` `8` `C` `M` `F` | Read the cursor as Lya, Lyb, SiIV, OVI, NeVIII, CIV, MgII or FeII and set the redshift |
| `R` | Clear the fit overlay |
| `?` | Show or hide the shortcut list |

The fits the editor draws are computed in the browser with the same formulas as
`rbcodes.multispec.quick_fit` (`LineFitter`'s linear two-anchor continuum, unweighted Gaussian or
clipped centre of mass), so the overlay matches the node; wire a **Quick Line Fit** node up when
you want the numbers in the graph.

## File formats

`Export Line List` writes exactly what rb_multispec writes (R1 §4.6):

- **`txt`** — fixed width, `Name` (30 characters), `Wave_obs` (15, four decimals) and `Zabs` (10,
  six decimals) under a two-line header.
- **`csv`** — the same columns comma-separated, plus `Wave_rest` and `Spectrum`.
- **`json`** — the combined document: `line_list`, `absorbers`, `spectrum_files` and a `metadata`
  block whose `application_name` is `MultispecViewer` and whose `version` is `1.5.0`. This is the
  file rb_multispec's *Load* reads back, and the only format that carries the absorber systems.

`Import Line List` reads all three. `Reconcile Line Lists` merges several of them: entries of the
same transition (ignoring `[b]`/`[p]` annotations) whose rest wavelengths lie within
`velocity_threshold` km/s of each other collapse into one row at the mean rest wavelength and mean
redshift, with a `MergedCount` column; the unique redshifts that survive become absorber systems
with cycling colours.

`backend/tests/packs/rbcodes/test_multispec_io.py` asserts, wherever rbcodes is installed, that
`rbcodes.GUIs.multispecviewer.io_manager` opens the files written here and that the vendored
reconciliation agrees with `multispecviewer.utils` line for line.

## Velocity stacks

`Velocity Stack` slices one panel per transition of a line list whose observed wavelength at the
absorber redshift falls inside the spectrum, on a common velocity axis (rbcodes' `c = 2.9979e5`
km/s), ordered by rest wavelength and labelled with the transition. The result is a
`SpectrumCollection`, so it plots with the usual spectrum widgets. The editor's `v` panel shows
the same slices for the hovered spectrum without leaving the viewer.
