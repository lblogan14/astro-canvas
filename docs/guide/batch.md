# Batch mode (phase 09)

Batch mode runs the **whole open workflow once per row** of a table. Each column is bound to a
node parameter, chosen node outputs become result columns, and the rows run concurrently with
per-row status. It generalises `launch_specgui -b`: a specgui batch table imports as-is, and the
column names it uses (`slice_vmin`/`slice_vmax` for the velocity window that is sliced out,
`ew_vmin`/`ew_vmax` for the integration limits) keep their separate meanings.

Switch layouts with the toolbar menu (**Canvas → Batch**), or open `/w/<workflow id>/batch`
directly. Batch is one of the four app modes; see [modes.md](modes.md) for the other three.

## The table

| Control | What it does |
|---|---|
| **Import…** | Reads a CSV, TSV or ECSV file, or a specgui `master_batch_table` export (its CSV template or the JSON with a `dataframe` array) |
| **Paste table** | The same, from text you paste in |
| **Add row** / **Remove rows** | Edit the grid directly; every cell is editable |
| Header dropdown | Binds the column to a `<node>.<param>` reference. Promoted parameters come first |
| **Collect into the results table** | Toggle which `<node>.<port>` outputs end up in the results |
| **Continue on error** | On by default: a failing row does not stop the others |
| **Save layout** | Writes the columns and collected outputs into the document's `layouts.batch` |

A template can ship its own batch layout, and the **Absorption Line Measurement** template does:
opening Batch mode there gives you the nine specgui columns already bound and 20 sample rows
(`samples/rbcodes/absorption_batch.csv`, the MgII 2796/2803 doublet over ten integration windows).

Columns that are not bound still travel with the row — useful for labels such as
`transition_name` — but they do not change anything the workflow computes.

## Running

**Run all** submits every row; **Run selected** submits only the ticked ones. Each row shows a
pill (*Pending → Running → Done*, or *Error* / *Cancelled*, hover for the message). **Cancel**
stops the queued rows and cancels the ones in flight — an expensive node running in a worker
process has that worker killed.

Rows run `max_workers` at a time: `cpu-1` when the graph contains expensive nodes, 8 otherwise.

The important property is that **rows share the cache**. A batch key is the ordinary node cache
key, so rows that agree on the front of the pipeline compute it once, and re-running an unchanged
row costs nothing. That is what makes 20 rows over one spectrum fast: the file is loaded once.

## Results

The grid appends one row per input row: the input columns, then the flattened scalar fields of
each collected output, then `status`, `error_message` and `calculation_timestamp` (the same
bookkeeping columns specgui writes). An `EWMeasurement` flattens to `W`, `W_e`, `N`, `N_e`,
`logN`, `logN_e`, `vel_centroid`, `vel_disp` and `SNR`, plus nested fields such as
`transition.wrest`. A collected column whose name clashes with an input column is qualified with
its node id. **CSV** and **ECSV** export the grid; the ECSV header carries the inferred datatypes,
so `astropy.table.Table.read` gets the column types right.

The ⇗ button on a row applies that row's parameters to the canvas and switches back to it, so a
surprising result can be inspected node by node with the editors.

## Doing it without the UI

`POST /api/workflows/{id}/batch` takes `{rows, spec?}` and answers 202 with a `batch_id`; the spec
defaults to the document's `layouts.batch`. Progress arrives on `/ws` as `batch.started`,
`batch.row` and `batch.finished` events (the rows' own node events stay off the socket), and
`GET /api/workflows/{id}/batch/{batch_id}` returns the per-row states and the results assembled so
far. `POST .../cancel` stops it. The same two commands exist over the WebSocket as `batch.run` and
`batch.cancel`. See [docs/formats/workflow.md](../formats/workflow.md) for the full contract.

Cells that arrive as text — every cell of a CSV does — are widened to the parameter's declared
type before the row runs, so `"1.3855"` reaches a `float` parameter as a number.
