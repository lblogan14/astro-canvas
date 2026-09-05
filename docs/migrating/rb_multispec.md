# Migrating from `rb_multispec`

`rb_multispec` stacks several spectra on a shared wavelength axis, lets you type a redshift, draw
a line list over everything, click features to identify them, fit them, keep a catalogue of
absorber systems, and export the lot. All of that is one node — `rbcodes.multispec.view` — and its
editor, which is the same window with the same keys.

Open **Workflows ▸ Templates ▸ Multi-Spectrum Viewer ▸ Use**. It stacks three spectra and starts
where you would start.

## Where each part went

| `rb_multispec` | Node | Notes |
|---|---|---|
| `multispec.MainWindow` / `SpectralPlot` | `rbcodes.multispec.view` | the stack, the redshift, the overlay, the identifications; outputs `absorbers`, `identified_lines` and a drawn `MultispecView` |
| `AbsorberManager` | `rbcodes.multispec.absorber_catalog` | normalises any catalogue to `Zabs`/`LineList`/`Color`/`Visible`, cycling `rb_utility.rb_set_color` — the same palette in the same order |
| `io_manager.save_line_list` / `save_combined_data` | `rbcodes.multispec.export_linelist` | `txt`, `csv` or the combined JSON, byte-for-byte |
| `io_manager.load_line_list` / `load_combined_data` | `rbcodes.multispec.import_linelist` | the lines and, from JSON, the absorbers |
| `utils.reconcile_linelists` | `rbcodes.multispec.reconcile_linelists` | merges duplicate identifications within a velocity threshold |
| `LineFitter.fit_gaussian` / `fit_com` | `rbcodes.multispec.quick_fit` | one row: centroid, FWHM, amplitude, direction |
| `vStack` | `rbcodes.multispec.vstack` | one velocity panel per transition of a list that falls inside the spectrum |
| `LineSelectionDialog` | the editor's overlay menu | the 16 atomic lists, the 5 curated zfind presets, plus anything wired into `extra_lines` |

## The editor is the window

Open it from the pencil-ruler button on a **Multi-Spectrum Viewer** node, and it is the layout you
know: the stack on the left sharing one wavelength axis, only the bottom panel drawing it, each
panel autoscaling its flux to the visible window; the identifications table on the right; the
redshift, the line list and the fit buttons in a toolbar.

**The keys are the keys.** Same letters, same meanings:

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

Four keys did not come across, and none of them has a browser meaning:

- **`q`** (quit) — close the editor with `Escape`, or Apply.
- **`Y`** and **`V`** (the manual y-limit and velocity-limit dialogs) — `t`/`b` set the flux limits
  at the cursor, and the velocity stack has its own window control.
- **`G`** (the advanced fit dialog) — the quick fits are `g`/`c` as before; a constrained,
  multi-component fit is a job for a **Quick Line Fit** node with its parameters in the inspector,
  or for the LLS/Voigt fitters, which are v0.2.
- **`K`** (launch zfind) — the canvas wires zfind in instead: a `rbcodes.zfind.rank` node's
  `redshift` output goes straight into the viewer's `redshift` port, and its
  `absorbers_to_catalog` output into the `absorber_seed`. Nothing is launched, and nothing is
  lost when you close a window.

## Where the catalogues live now

In `rb_multispec` the absorber list and the identifications were window state; you exported them
or they were gone. Here they are the node's `catalog` and `identifications` **parameters**, so:

- they are saved with the document, and they come back when you re-open it;
- they are also the node's two table **outputs**, so a downstream node — an export, a join
  against your own catalogue, a batch over them — sees exactly what you built;
- editing them re-runs whatever depends on them, and **Undo** takes back an identification.

`Apply` writes the redshift, the overlay list, both catalogues and the display settings as one
undo step. Nothing is committed before that.

## Your files still work

`Export Line List` writes exactly what `io_manager` writes — `txt`, `csv` and the combined JSON —
and `import_linelist` reads all three, including a combined JSON's absorber block. So you can
finish a session in rbcodes and continue it here, or the other way round.

## What you gain

**Ten spectra, one document.** Save it, and the stack, the redshift, the systems and the
identifications come back together. Export the `.acw` and somebody else gets it with the input
hashes.

**The fits are in the graph if you want them.** The editor's `g`/`c` fits are drawn in the browser
with `LineFitter`'s own formulas (linear two-anchor continuum, unweighted Gaussian, clipped centre
of mass) so the overlay is instant. Wire a **Quick Line Fit** node up when you want the numbers as
data — a table you can export, plot, or batch over.

**Velocity stacks are a node.** `vstack` produces the panels as a value, so a stack can be pinned
into a Dashboard tile or exported, not just looked at.

## What is different

**`view` is an interactive node.** Most nodes are pure functions of their inputs; this one holds
what you built in its parameters, which is why its editor writes back. That is the same bargain
`rb_multispec` made, made explicit.

**Ten spectra need a folder loader or four `collect` ports.** `core.list.collect` takes four
spectra today (the SDK has no variadic input ports yet), so a stack of ten means chaining
collects. It is on the v0.2 list.

**Two `LineList` ports, not a list.** `extra_lines` and `extra_lines_2` for the same reason.

**Line labels drop above 40 ticks in view.** Zoom in to get them back, or press `L`. rb_multispec
drew them all and let them overlap.
