# App modes: turning a workflow into a GUI (phase 10)

A workflow is a graph, but nobody wants to hand an undergraduate a graph. **App modes** are four
ways to show the same document as a finished interface: a **Form** (App), a step-by-step
**Wizard**, a linked **Dashboard**, and the table runner (**Batch**, see
[batch.md](batch.md)). Switch with the toolbar's layout menu, or open a mode directly by URL:

```
/w/<workflow id>            the canvas
/w/<workflow id>/app        the form
/w/<workflow id>/wizard     the steps
/w/<workflow id>/dashboard  the grid
/w/<workflow id>/batch      the table runner
```

Every mode has a **Show graph** button, and the graph is never more than one click away.

## What a mode shows: promoted parameters and pinned views

A mode shows only what you have marked. Two gestures do that:

- **Promote a parameter** — the star next to any parameter in the Inspector. A promoted
  parameter appears in every mode, in the App form, the Wizard step and as a Dashboard tile.
  Inside a subgraph body the star promotes into *that body* instead, which is what lets an
  instance of it set the parameter (see [canvas.md](canvas.md)).
- **Pin a view** — the pin on any node preview. The pinned output becomes a tile that can be
  expanded to the full-size viewer, and on a dashboard it takes part in linked selection.

Both land in the document (`promoted` and `views` in `workflow.json`) as ordinary undoable edits,
so `Ctrl+Z` removes a star and autosave keeps it.

### The Parameters panel

The star icon in the toolbar (or the sidebar's *Parameters*) opens the panel listing everything a
mode can show, **in the order it will show it**:

| Control | What it does |
|---|---|
| Drag an item | Reorders it; dropping it on a group heading moves it into that group |
| ↑ / ↓ | The same, from the keyboard |
| Pencil | Edits the **label**, **group** and **help text** shown in the modes |
| Item name | Selects the node on the canvas |
| Trash | Removes the promotion (and drops it from every layout that used it) |

Groups are what the default layouts turn into sections and steps, so naming them well is most of
the layout work. Items without a group land in *Parameters*.

## App mode: one form

The promoted parameters as a scrolling form of sections, with the pinned views in a column beside
them (below them on a narrow window). The header carries **Run**, the auto-run state, **Export
results**, **Save layout** and **Show graph**; validation messages from the engine appear under
the form.

With no `layouts.app` in the document the layout is **derived from the promoted groups** — one
section per group, views last — so promoting a handful of parameters is enough to get a working
app. **Save layout** writes what is on screen into the document as one undoable command; until
you press it, opening a mode never modifies the workflow.

## Wizard mode: ordered steps

The Wizard is `launch_specgui`'s tabs rebuilt from the graph. Each step shows its own parameters
and views, and **Next** opens only when every node the step depends on is `done` and free of
validation errors. A step that has not run yet offers **Run step**, which runs exactly those
nodes. **Back** is always available and never discards anything: the values are document
parameters, not wizard state. **Skip to results** jumps to the last step, which carries the views
and **Export results**.

**Edit steps** turns the header into the layout editor: step titles are text inputs, steps can be
added and removed, and items move between steps and the *Not in any step* tray by dragging or
with the ‹ › buttons. Edits stay in a draft until **Save layout**.

The **Absorption Line Measurement** template ships this layout:
Load → Redshift → Transition → Continuum → Measure → Save, each step gating on the nodes it
edits, so a measurement can be completed without ever opening the canvas.

## Dashboard mode: a grid of linked views

A grid (12 columns by default) of view tiles and promoted-parameter panels. It is **locked** by
default — a dashboard is something you use — and **Edit layout** turns the tiles into drag and
resize handles, with an × to remove one. **Save layout** stores the geometry in
`layouts.dashboard`.

### Linked selection

Two views are linked when they **share an upstream node**: the same spectrum feeding a curve and
a table means a selection on one is a filter on the other.

- **Drag across a curve** (a spectrum, a χ² curve, a velocity stack) to select a range on its x
  axis. Every linked table highlights the rows whose axis value falls inside it, and every linked
  curve draws the same band.
- **Click a row** in a table to select it; linked curves mark where it sits.
- The header shows the live selection and clears it; a click without a drag clears it too.

The selection is view state: it is never saved and never undoable.

Which column a range applies to is picked from the table itself — a column named `wave`,
`wavelength`, `lambda`, `wrest`, `wobs`, `z`, `vel`… if there is one, else the first numeric
column.

## Export results

**Export results** (App, Wizard, Dashboard) writes the finished outputs into the workspace rather
than downloading them:

- Tables become **CSV**, values carrying arrays become **`.npz`**, everything else becomes the
  same **JSON** body `GET /api/outputs` serves.
- The folder is `exports/<workflow name>/`, and each file is named `<node>.<port>.<ext>`.
- What gets exported: the batch layout's `collect` list if the document has one, else the pinned
  views, else every leaf output.

Pending edits are saved and the re-run they trigger is waited out first, so an export never
catches the graph half-way through.

## The templates gallery

The **Browse all templates** link in the Workflows sidebar opens the gallery (`/templates`): a
card per installed template with its figure, description, required packs, node count and the
layout it opens into.

- **Open** copies the template into the workspace and opens it in its default layout
  (`meta.default_layout`), copying the sample files it needs into `samples/` on the way.
- **Show graph** does the same but opens the canvas.

The four rbcodes templates ship layouts: Absorption Line Measurement opens as a **Wizard** (plus
App and Batch layouts), while Redshift Finder, Multi-Spectrum Viewer and IFU Cube Explorer open
as **Dashboards** (plus App layouts).

## In the document

`promoted`, `views` and `layouts` are described in
[../formats/workflow.md](../formats/workflow.md#layout-sections). In short: a layout item is a
ref, either `"promoted:<node>.<param>"` or `"view:<id>"`; a saved layout keeps unknown keys
untouched; and refs that no longer resolve come back from the server as `layout_errors`, which
the Parameters panel and the modes show instead of silently rendering an empty form.
