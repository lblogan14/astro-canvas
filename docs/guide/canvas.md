# The canvas (phase 03)

Astro Canvas opens in the browser tab the launcher points at (`astro-canvas serve` prints a
`http://127.0.0.1:8765/?token=…` URL; the token is kept in the tab's session storage). The editor
has four areas:

| Area | What it does |
|---|---|
| **Toolbar** | Workflow name (click to rename), save indicator, undo/redo, fit view, layout menu (Canvas only in v0.1), **Auto-run** toggle, **Run**/Cancel, panel toggles. |
| **Left sidebar** | *Node library* (fuzzy search, categories from the installed packs, favourites, pack badges) and *Workflows* (create, open, rename, duplicate, delete; version history with restore). |
| **Canvas** | The node graph (Vue Flow): minimap, zoom controls, dotted grid, groups. |
| **Right inspector** | The selected node's parameters (all of them, advanced included), cost override, bypass, notes. |
| **Bottom drawer** | Run log, compile issues and node errors (click a row to select the node), `/api/system` stats. |

## Working with nodes

- **Add** a node by dragging it from the library onto the canvas, double-clicking it (added at the
  viewport centre), or pressing `Tab` and typing its name.
- **Connect** ports by dragging from an output handle (right) to an input handle (left). Handles
  are coloured by type with a shape glyph (Okabe–Ito palette). Incompatible drops are refused with
  a message; dropping a connection on empty canvas opens the quick-add palette filtered to node
  types that accept that output, and wires the new node up.
- **Parameters** render inside the node as widgets generated from the node's JSON Schema (numbers
  with units and bounds, sliders, text, code, selects, checkboxes, ranges, lists, colours,
  redshift and wavelength inputs). The **link** button (↔) converts a widget into an input port;
  the port's unlink button turns it back.
- The **node menu** (⋯) offers rename, bypass, cost override, collapse, *run to here*, duplicate
  and delete. Double-click the title to rename. Nodes are resizable when selected.
- **Status** shows as a left stripe and a badge: *Pending*/*Stale* (amber), *Queued*, *Running*
  (blue progress bar), *Done* (green; ⟳ marks a cache hit), *Error* (red, click the icon for the
  message, hint and traceback), *Bypassed*.
- **Groups** (`Ctrl+G`) wrap the selection in a titled, coloured frame; moving the frame moves
  its members. `Ctrl+Shift+G` ungroups.
- **Subgraphs** (`Ctrl+Shift+C`) replace the selection with a single node that contains it; see
  below.

Every edit is saved automatically one second after you stop typing. The engine recompiles the
document, auto-runs cheap nodes and streams status over the WebSocket; expensive nodes show
*Stale* until you press **Run** (or *run to here* on a node).

## Keyboard shortcuts

| Keys | Action |
|---|---|
| `Ctrl+Enter` | Run the workflow |
| `Ctrl+Z` / `Ctrl+Y` (`Ctrl+Shift+Z`) | Undo / redo (moves and typing coalesce into one step) |
| `Ctrl+C` / `Ctrl+V` / `Ctrl+D` | Copy / paste (internal edges kept, offset by 40 px) / duplicate |
| `Delete`, `Backspace` | Delete the selected nodes, edges or groups |
| `Ctrl+G` / `Ctrl+Shift+G` | Group / ungroup |
| `Ctrl+Shift+C` / `Ctrl+Shift+E` | Collapse the selection into a subgraph / expand a subgraph in place |
| `Ctrl+Shift+L` | Auto-layout the graph (or the selection) left to right |
| `Ctrl+A` | Select every node |
| `Tab` | Quick-add palette |
| `Space` + drag | Pan |
| `.` / `F` | Fit view / fit the selection |
| `Ctrl+S` | Save now |
| `Escape` | Close the palette or clear the selection |

The theme follows the operating system by default; the toggle in the header cycles
system → light → dark and remembers the choice.

## Subgraphs

A group is a visual frame; a **subgraph** is a real container. Select some nodes and press
`Ctrl+Shift+C` (or use the node menu) and they are replaced by one node:

- every edge that crossed the boundary becomes a **named port** on the new node, typed from the
  inner port it maps to, so connections and validation behave exactly as before. Two outer
  consumers of the same inner output share one port;
- **double-click** the node (or its ⤵ toolbar button) to work inside the body. A breadcrumb at
  the top left shows the path; click the workflow name to come back out. Subgraphs nest;
- `Ctrl+Shift+E` **expands** an instance again: the inner nodes return to the positions they had,
  offset from where the instance sat, and the boundary edges reconnect;
- an inner parameter can be **promoted** so instances set it directly. It appears on the instance
  as `<inner node>.<param>` and can be linked into an input port like any other parameter.

Collapsing changes nothing the engine sees: the compiler inlines a subgraph into
`<instance>/<inner id>` nodes, and because cache keys are content-based the collapsed graph
re-uses the outputs the expanded one computed.

Everything above is one undo step, and a body plus one instance can be saved as a **blueprint** —
a small workflow document holding just the subgraph — to reuse it in another workflow.

## Auto-layout

`Ctrl+Shift+L` runs elk's layered algorithm over the whole graph, or over the selection when more
than one node is selected. The result is anchored at the selection's current top-left corner and
lands as a single undoable move, so `Ctrl+Z` puts everything back.

## Showing the graph as an app

The toolbar's layout menu switches between the canvas and the four composed layouts (App, Wizard,
Dashboard, Batch). What they show is what you have **starred** (the promotion star on an Inspector
parameter) and **pinned** (the pin on a node preview). See
[modes.md](modes.md).
