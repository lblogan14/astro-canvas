# Coming from the rbcodes GUIs

If you already use `launch_specgui`, `rb_zfind`, `rb_multispec` or `rb_ifuview`, you know the
science. These four pages say where each button went.

| You used | Start here | It became |
|---|---|---|
| `launch_specgui` | [Absorption lines](specgui.md) | the **absorption-line-measurement** template, in Wizard mode |
| `rb_zfind` | [Redshift finding](rb_zfind.md) | the **redshift-finder** template, in Dashboard mode |
| `rb_multispec` | [Multi-spectrum viewing](rb_multispec.md) | the **multi-spectrum-viewer** template and its editor |
| `rb_ifuview` | [IFU cubes](rb_ifuview.md) | the **ifu-cube-explorer** template and the aperture editor |

## What is the same

**The numbers.** Every ported node calls rbcodes' own function where rbcodes is importable, and a
vendored copy of the same kernel where it is not (rbcodes pins `python<3.11` upstream; Astro
Canvas runs on 3.10 to 3.13). The test suite compares the two at `rtol=1e-9` or the tolerance
rbcodes' own tests use, so a measurement you made in the GUI comes out the same here. Where a
port deliberately differs — the two places it does — it says so on the page.

**The file formats.** `rb_spec` JSON, the `rb_write_fits` layout, specgui's batch CSV, the
multispec line lists and combined JSON, ds9 region files: all read and written unchanged. You can
move a half-finished measurement across in either direction.

**The keyboard.** Where a GUI had a keystroke, the equivalent editor has the same keystroke. The
multi-spectrum viewer's twenty-odd keys are the same keys.

## What is different, and why

**A measurement is a document, not a session.** The GUIs hold state in a window: you load, you
set, you fit, you save, and if you close it, that is gone. Here the same steps are *nodes* in a
`workflow.json`, so the measurement is a file you can save, re-open, hand to a student, put in a
repository next to the paper, or run over four hundred sightlines without opening a window. That
is the whole point of the rewrite, and it is the one thing worth adjusting your habits for.

**Nothing recomputes because you clicked.** Each node has a content hash over its parameters and
its inputs; changing the continuum order re-runs the continuum fit and the equivalent width, and
nothing else. Undo is a document operation, not a re-fit. See
[concepts](../concepts.md#reactive-not-batch).

**It runs headless.** `astro-canvas run measurement.json` produces the same outputs with no
browser, which is what makes the batch tier and a lab server possible.

**Plots are for reading, editors are for pointing.** The GUIs mixed the two: one matplotlib canvas
was both the figure and the input device. Here a node's inline preview and the full-size viewer
are read-only — pan, zoom, hover, and that is all — and anything that needs a click happens in an
**editor**, which opens on the node, has a defined output, and writes it into the document when
you press Apply. The continuum masks, the velocity range, the line picker, the z-accept table, the
multi-spectrum viewer and the aperture drawer are all editors.

## What is not here

Honesty first — these did not make v0.1:

| Missing | Where it is |
|---|---|
| `IGM.LLSFitter`, `LLSVoigtFitter` (LLS and Voigt profile fitting) | v0.2; needs `rbvfit` declared upstream |
| `rb_align` (WCS alignment of two cubes, interactive source matching) | v0.2 |
| `rb_zgui` (JWST NIRCam grism 1D+2D redshift GUI) | v0.2; needs a 2D spectrum port type |
| AbsTools' multi-ion stacked measurement | composable today from the absorption nodes plus batch mode; a template in v0.2 |
| The pyds9 live bridge and SAMP (TOPCAT/Aladin) | v0.2; ds9 *region files* work today |
| `rb_ifuview`'s alignment dialog | v0.2 |

Anything on that list still works in rbcodes; the two installations are independent, and nothing
here changes your existing setup.
