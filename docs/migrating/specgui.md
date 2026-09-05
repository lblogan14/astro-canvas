# Migrating from `launch_specgui`

`launch_specgui` is six tabs in a fixed order: **Input Spectrum · Set Redshift · Select
Transition · Fit Continuum · Measurements · Save Results**. That order is not incidental — it is
the measurement — so Astro Canvas ships it as a template with a **Wizard** layout whose six steps
are those six tabs.

Open **Workflows ▸ Templates ▸ Absorption Line Measurement ▸ Use**, or from the gallery
(`/templates`) press **Open** and pick Wizard. You get the same six panels, one at a time, with
Next unlocked as each step's node finishes. Nothing about the canvas is on screen unless you ask
for it (**Show graph**).

## Tab by tab

| specgui tab | Wizard step | Node | Notes |
|---|---|---|---|
| Input Spectrum | Load | `core.io.load_spectrum` | the same `rb_read_spectrum` readers when rbcodes is importable, this pack's readers otherwise; **Prefer rbcodes parsers** is the switch |
| Set Redshift | Redshift | `rbcodes.absorption.set_redshift` | `shift_spec`; a `Redshift` input port overrides the typed value, which is how the redshift finder feeds it |
| Select Transition | Transition | `rbcodes.absorption.set_transition` | `rb_setline`; the **line picker** editor replaces the dropdown and the click-to-identify |
| Fit Continuum | Continuum | `rbcodes.continuum.fit` | `fit_continuum` / `rb_iter_contfit` / `fit_optimal_polynomial`; the **continuum masks** editor replaces the interactive canvas |
| Measurements | Measure | `rbcodes.absorption.slice` + `compute_ew` | `slice_spec` + `IGM.compute_EW`; the **range** editor sets vmin/vmax |
| Save Results | Save | `rbcodes.absorption.save_rbspec_json` | `save_slice`, byte-for-byte the same JSON |

## The things you did with the mouse

**Masking the continuum.** In specgui you dragged on the plot in the Fit Continuum tab. Here you
open the **continuum masks** editor on the continuum node (the pencil-ruler button in its header),
and drag on the same velocity slice. Two differences worth knowing: the editor runs the *actual
node* on every change rather than a re-implementation, so what you see is what the graph will
compute; and it lists the BIC per polynomial order, with the best in bold, so "which order" is a
number rather than a feeling. **Apply** writes `masks`, `order` and `method` as one undo step.

**Picking the transition.** specgui's transition tab had a line list dropdown and a click-to-pick.
The **line picker** editor is the same thing, plus the doublet partner marked for the seven common
doublets (MgII, CIV, SiIV, NV, OVI, AlIII, FeII), so checking the second member is a glance.

**Setting the integration range.** The **range** editor: two handles on the velocity plot, or type
the numbers. Same `vmin`/`vmax`, same `compute_EW`.

## Your batch CSV still works

specgui's batch mode read a CSV of sightlines. **Batch** mode reads the same file: open the
template, switch to Batch (`/w/<id>/batch`), press **Import** and choose your CSV. The columns are
matched to the promoted parameters by name — `filename`, `zabs`, `transition`, `vmin`, `vmax` and
the rest are recognised — and anything unmatched is offered as a dropdown.

Then it is better than it was:

- rows run concurrently, and one bad row does not stop the rest (`continue_on_error`);
- rows that share a prefix of the graph share its cached outputs, so a hundred sightlines through
  the same spectrum load it once;
- the results table exports as CSV or ECSV, with `status` and `error_message` columns;
- and `astro-canvas run` does the whole thing from a shell script, with no browser.

See [batch mode](../guide/batch.md).

## What you gain

**The measurement is a file.** Save the workflow and you have the whole chain — which spectrum,
which redshift, which masks, which order, which range — in one `workflow.json`. Re-open it in six
months and it re-runs. Export it as a [`.acw` bundle](../guide/bundles.md) and it carries the
input hashes, the resolved package versions and the results, which is what makes a figure
reproducible by somebody else.

**One spectrum, many absorbers.** In specgui, a second absorber meant starting over. Here you
duplicate the redshift-to-measurement chain (select the nodes, `Ctrl+D`), point it at another
redshift, and both measurements live in the same document with the same loaded spectrum.

**The redshift can come from a fit.** Wire `rbcodes.zfind.rank`'s `redshift` output into
`set_redshift` and the measurement follows whatever the z-accept editor accepted. That connection
is the one thing the two GUIs could never do between them.

## What is different

**No `Update` button.** Nodes re-run when their inputs or parameters change, so there is nothing
to press. A node that measured itself slower than two seconds becomes cost-gated and *does* wait
for **Run** — the quasar continuum fit (`rbcodes.continuum.full_spectrum`) is the one in this
template that behaves that way, deliberately.

**The plot is not the input device.** specgui's matplotlib canvas was both. Here the inline
preview and the viewer are read-only, and clicking happens in editors. It is one more keystroke
to open an editor, and in exchange an accidental drag can never change a measurement.

**Advanced continuum options are on the node.** `rb_iter_contfit`'s sigma clipping, the maximum
order for the BIC scan, and the optimiser switch are the continuum node's *advanced* parameters
(the collapsed section in the inspector) rather than a separate dialog.
