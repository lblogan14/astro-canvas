# Tutorial: wrap a function as a node

This builds a complete node pack from nothing: one node that turns
[rbcodes](https://github.com/rongmon/rbcodes)' `estimate_snr` into something you can drop on the
canvas, wire a spectrum into, and read off a number. It takes about twenty minutes.

Everything here is real code. The finished pack lives in
[`docs/examples/snr-pack`](https://github.com/lblogan14/astro-canvas/tree/main/docs/examples/snr-pack)
and the repository's own test suite runs its assertions on every commit, so what you copy is what
is tested.

!!! info "What you need"

    [uv](https://docs.astral.sh/uv/), a working Astro Canvas (`astro-canvas doctor` green), and a
    function you want on the canvas. This one measures signal-to-noise; yours can be anything
    that takes arrays and returns arrays.

## 1. The function we are wrapping

```python
# rbcodes/utils/compute_SNR_1d.py
def estimate_snr(wave, flux, error, binsize=3, snr_range=[-1, -1], verbose=True,
                 plot=False, robust_median=False, sigma_clip_threshold=3):
    """Estimate the signal-to-noise ratio (SNR) per pixel for a given 1D spectrum."""
```

It bins the spectrum, divides flux by error, and returns a dict with the curve and its mean and
median. Three things about it will shape the node:

- **it takes three parallel arrays**, which on the canvas is one `Spectrum1D`;
- **it returns a dict**, and a node returns typed values, so we have to choose what to expose;
- **its module imports `matplotlib.pyplot`**, which needs a headless backend in a server process.

The last one is the kind of detail that only shows up when you run it. Keep it in mind.

## 2. The package

A pack is an ordinary Python distribution with one entry point. Four files:

```
snr-pack/
├── pyproject.toml
└── src/astro_canvas_snr/
    ├── __init__.py
    └── nodes.py
```

```toml title="pyproject.toml"
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "astro-canvas-snr"
version = "0.1.0"
description = "Example Astro Canvas pack: signal-to-noise of a spectrum, from rbcodes"
requires-python = ">=3.10,<3.14"
dependencies = [
  "astro-canvas-sdk>=0.1,<0.2",
  "astro-canvas-core>=0.1,<0.2",
  "numpy>=1.26",
  "astropy>=6",
]

[project.optional-dependencies]
rbcodes = ["rbcodes>=0.2"]

[project.entry-points."astro_canvas.nodes"]
snr = "astro_canvas_snr:register"

[tool.astro-canvas]
display_name = "Signal-to-noise (example)"
publisher = "example"
security = "standard"

[tool.hatch.build.targets.wheel]
packages = ["src/astro_canvas_snr"]
```

Four things in there matter more than they look:

**`astro-canvas-sdk`, never `astro-canvas`.** The SDK is a few hundred kilobytes of pydantic and
numpy. The app is a web server. A pack that depends on the app cannot be installed *into* the app,
and the manager will refuse it.

**`astro-canvas-core`** is where `Spectrum1D` lives. Port types belong to whichever pack defines
them, and a pack that speaks a type depends on the pack that owns it.

**The entry point** in the `astro_canvas.nodes` group is the whole discovery mechanism. `snr` is
the pack's name in the UI and in `astro-canvas pack list`; `astro_canvas_snr:register` is the
function the app calls.

**`security = "standard"`** is a promise: no network, no subprocesses. Say `needs-network` if you
call an archive and `runs-subprocess` if you shell out — the manager shows it before installing,
and a locked-down server can refuse everything above `standard`. See
[publishing a pack](publishing.md).

## 3. `register`

```python title="src/astro_canvas_snr/__init__.py"
from astro_canvas.sdk import PackRegistry

__version__ = "0.1.0"


def register(registry: PackRegistry) -> None:
    from astro_canvas_snr import nodes  # noqa: PLC0415

    registry.add_module(nodes)
```

`add_module` walks the module and picks up everything decorated with `@node` or `@port_type`.
There is no list to keep in sync.

The import is *inside* the function on purpose. The app imports `astro_canvas_snr` at startup to
find `register`, and calls it only when it is building a registry — so anything expensive
(astropy, pyarrow, your own heavy module) should load on registration and not on import. `astro-canvas doctor`
reports the cost of every pack's import, and a pack that takes a second to import makes the app
take a second longer to start for everybody.

## 4. The node

```python title="src/astro_canvas_snr/nodes.py"
import os
from typing import Annotated, Any

import numpy as np
from astro_canvas_core.types import Spectrum1D

from astro_canvas.sdk import NodeContext, Param, node


@node(
    id="snr.spectrum.estimate",
    name="Estimate SNR",
    category="Spectra/Measure",
    icon="activity",
    cost="cheap",
    preview="spectrum-thumb",
    outputs=("snr", "median"),
)
def estimate_snr(
    spec: Spectrum1D,
    binsize: Annotated[int, Param(min=1, max=64, label="Bin size")] = 3,
    wave_min: Annotated[float | None, Param(widget="wavelength", label="Lower bound")] = None,
    wave_max: Annotated[float | None, Param(widget="wavelength", label="Upper bound")] = None,
    robust: Annotated[bool, Param(label="Sigma-clipped median")] = False,
    sigma: Annotated[float, Param(min=1.0, max=10.0, step=0.5, label="Clip threshold")] = 3.0,
    ctx: NodeContext | None = None,
) -> tuple[Spectrum1D, float]:
    """Signal-to-noise per pixel of a rebinned spectrum.

    The spectrum is binned by ``binsize`` pixels, the ratio of flux to error is taken pixel by
    pixel, and the curve is reduced to one number: the median, or a sigma-clipped median when
    ``robust`` is set.

    Args:
        spec: Spectrum with an error array.
        binsize: Pixels combined before the ratio is taken (1 leaves the grid alone).
        wave_min: Lower bound of the range to measure; empty means the first pixel.
        wave_max: Upper bound of the range to measure; empty means the last pixel.
        robust: Reduce with a sigma-clipped median rather than a plain one.
        sigma: Clip threshold, in standard deviations, when ``robust`` is set.

    Returns:
        The SNR curve as a spectrum (its flux *is* the ratio), and the reduced value.
    """
```

That signature *is* the schema. Nothing else declares it:

| In the signature | On the canvas |
|---|---|
| `spec: Spectrum1D` | an **input port** typed `astro.Spectrum1D`, because the annotation is a port type |
| `binsize: int` | a **parameter**, rendered as a number field, because `int` is JSON-native |
| `Param(min=1, max=64)` | the field's limits, and the JSON Schema the UI validates against |
| `Param(widget="wavelength")` | a wavelength field with the spectrum's own unit |
| `float \| None = None` | an optional parameter, empty by default |
| `ctx: NodeContext \| None` | the runtime context — not a port and not a parameter |
| `-> tuple[Spectrum1D, float]` | two **output ports**, named by `outputs=(...)` |
| the docstring's summary | the node's description, in the library and the inspector |
| the docstring's `Args:` | each parameter's help text |

Two things worth knowing about that table:

- **A parameter is also linkable.** Anything rendered as a widget can be turned into an input port
  by the user (the chain icon in the inspector), so `binsize` can be driven by another node
  without you doing anything.
- **`Param(help=...)` overrides the docstring.** Prefer the docstring: it is the only description
  that also serves someone reading the source. Use `Param` for what a docstring cannot carry —
  the widget, the label, the limits.

The `@node` arguments are the presentation and the execution contract:

`cost="cheap"` runs the node in a thread in the server process, on every edit, after a 250 ms
debounce. `"expensive"` puts it in a worker process and makes the user press **Run**. `"auto"`
starts cheap and promotes itself once its moving-average runtime passes two seconds. Binning a
spectrum is microseconds — `cheap` is right, and getting this wrong is the single most common
pack bug: an expensive node marked cheap blocks the event loop for everyone on a lab server.

`preview="spectrum-thumb"` picks the inline renderer. The SNR curve is a `Spectrum1D`, so the
spectrum thumbnail draws it for free.

### The body

```python
    if spec.error is None:
        raise ValueError("the spectrum has no error array, and SNR needs one")

    # rbcodes' module imports `matplotlib.pyplot` when it loads, so the backend has to be
    # headless *before* the import: a node runs in a server process with no display.
    os.environ.setdefault("MPLBACKEND", "Agg")
    from rbcodes.utils.compute_SNR_1d import estimate_snr as rb_estimate_snr

    lo, hi = _range(spec, wave_min, wave_max)
    if ctx is not None:
        ctx.log("info", "estimating SNR", binsize=binsize, lo=lo, hi=hi)

    result: dict[str, Any] = rb_estimate_snr(
        np.asarray(spec.wave, dtype=float),
        np.asarray(spec.flux, dtype=float),
        np.asarray(spec.error, dtype=float),
        binsize=int(binsize),
        snr_range=[lo, hi],
        verbose=False,
        plot=False,
        robust_median=bool(robust),
        sigma_clip_threshold=float(sigma),
    )
```

Four decisions in fifteen lines.

**Raise a `ValueError` with a sentence.** The message reaches the node's badge and the errors
drawer verbatim, so write it for the person who will read it. The engine adds a hint of its own
for the failures it recognises (see [error handling](#7-when-it-goes-wrong)).

**Set `MPLBACKEND` before importing anything that touches matplotlib.** A node runs in a server
process; importing pyplot with a GUI backend either fails or, worse, hangs. This is a hard rule
for anything that reaches into rbcodes' GUI modules, and the reason the import is inside the
function rather than at the top of the file.

**`verbose=False, plot=False`.** The upstream function prints and draws. A node does neither: it
logs through `ctx` and returns values. Whatever a wrapped function does to stdout is noise in a
server log, and whatever it draws to a window is a hang waiting to happen.

**`ctx` is optional and used defensively.** The engine passes one; a direct call from a test does
not have to. `ctx.log`, `ctx.progress(fraction, message)` and `ctx.is_cancelled()` are what make a
long node feel alive and cancellable — a loop that never polls `is_cancelled` cannot be stopped.

### Choosing what to return

The upstream dict has seven keys. The node returns two values:

```python
    curve = Spectrum1D(
        wave=np.asarray(result["wave"], dtype=float),
        flux=np.asarray(result["snr"], dtype=float),
        wave_unit=spec.wave_unit,
        flux_unit="SNR / pixel",
        frame=spec.frame,
        z=spec.z,
        meta={
            "binsize": int(binsize),
            "mean_snr": float(result["mean_snr"]),
            "median_snr": float(result["median_snr"]),
            "source": "rbcodes.utils.compute_SNR_1d.estimate_snr",
        },
    )
    reduced = float(result["robust_snr"] if robust else result["median_snr"])
    return curve, reduced
```

The curve goes out as a `Spectrum1D` whose flux *is* the ratio. That is not a trick: a spectrum is
"values on a wavelength grid", the previews and the viewer already know how to draw one, and it
can be cropped, rebinned and plotted by nodes that were written before this pack existed. Reusing
an existing port type is almost always better than inventing one — invent a `@port_type` when the
thing genuinely has fields nothing else has (see
[the node schema](../formats/node-schema.md#porttypespec)).

The scalar goes out as a plain `float`, which is `astro.Float` on the wire and can drive any
numeric parameter downstream.

Everything else lands in `meta`, which travels with the value and shows up in the inspector. Note
what is in there: **`source`**. A value that came out of somebody else's code should say so.

## 5. Try it

Without installing anything:

```sh
uv run --with ./snr-pack --with 'rbcodes>=0.2' astro-canvas serve --open
```

The node is under **Spectra ▸ Measure** in the library. Wire a Load Spectrum into it and you get a
curve and a number.

If it is not there, `astro-canvas doctor --verbose` says why — a pack that raises on import is
logged and skipped rather than taking the server down, and the traceback is in that output and in
the Manager's Installed tab.

Once you are happy with it, install it properly so it survives a restart:

```sh
astro-canvas pack install ./snr-pack
```

which resolves it against the app's environment, shows you the diff, and refuses a plan that would
change a pin the app depends on.

## 6. The test

A pack's test suite has two halves, and the first one is the one people skip.

```python title="tests/test_snr_node.py"
def test_the_schema_is_what_the_ui_will_show() -> None:
    registry = NodeRegistry()
    astro_canvas_snr.register(registry)
    spec = registry.spec("snr.spectrum.estimate")

    assert [port.name for port in spec.inputs] == ["spec"]
    assert [port.type for port in spec.inputs] == ["astro.Spectrum1D"]
    assert [port.name for port in spec.outputs] == ["snr", "median"]
    assert spec.description.startswith("Signal-to-noise per pixel")
    binsize = next(param for param in spec.params if param.name == "binsize")
    assert binsize.description == (
        "Pixels combined before the ratio is taken (1 leaves the grid alone)."
    )
```

**Assert the schema.** It is derived by introspection, which means a rename, a moved default or a
docstring you tidied can change what the UI shows without changing what the function computes.
This test is the one that catches it.

```python
def test_the_numbers_are_rbcodes_own() -> None:
    spec = spectrum()
    curve, median = estimate_snr(spec, binsize=3, ctx=NullContext())

    expected = reference(spec.wave, spec.flux, spec.error, binsize=3,
                         snr_range=[-1, -1], verbose=False, plot=False)
    assert np.allclose(curve.flux, expected["snr"], rtol=1e-12)
    assert median == pytest.approx(float(expected["median_snr"]), rel=1e-12)
```

**Assert against the original**, not against numbers you recorded from your own wrapper. A test
that compares your output to your own last output only proves you have not changed anything; one
that calls the upstream function proves you are still computing what you claim to. `NullContext`
is the SDK's stand-in for the engine's context: it records everything and cancels nothing.

Where the upstream library will not install everywhere — rbcodes pins `python<3.11` — skip rather
than fail:

```python
pytest.importorskip("rbcodes", reason="rbcodes pins python<3.11 upstream")
```

and keep the schema half running unconditionally. That is exactly the split the rbcodes pack in
this repository uses: its numerical tests run on a 3.10 environment and its schema tests run
everywhere.

## 7. When it goes wrong

Raise, with a sentence. The engine turns the exception into a `node.error` event carrying the
message, the traceback and a **hint** — its own one-line "what to do next", chosen from
[`engine/hints.py`](https://github.com/lblogan14/astro-canvas/blob/main/backend/src/astro_canvas/engine/hints.py)
by exception type. `FileNotFoundError` gets "That file is not in the workspace any more…",
`ModuleNotFoundError` gets "A package this node needs is not installed…", and a `ValueError`
gets nothing, which is why *your* message has to carry its own weight.

Do not catch and return a sentinel. A node that returns `NaN` on failure looks like it worked, and
the graph downstream will happily average it.

## 8. Publishing

The pack is a wheel:

```sh
uv build ./snr-pack
```

To make it installable by name, publish it to PyPI and add it to the registry index so it shows up
in the Manager's Registry tab — both steps are in
[publishing a pack](publishing.md). To ship a **workflow template** with it (a starting graph a
user can open from the gallery), add a `templates/` folder to the package; the format is in
[publishing a pack](publishing.md#3-templates-and-sample-data).

## Where to go next

- [The node schema](../formats/node-schema.md) — every field of `NodeSpec`, `ParamSpec` and
  `PortTypeSpec`, what each annotation maps to, and how blobs work.
- [`backend/sdk/README.md`](https://github.com/lblogan14/astro-canvas/blob/main/backend/sdk/README.md)
  — the SDK's own reference: `@port_type`, lazy inputs, `Expansion`, dynamic ports.
- [Publishing a pack](publishing.md) — versioning against the app, the registry index, security
  classes.
- [Code nodes](../guide/code-nodes.md) — if the thing you want is a ten-line snippet rather than a
  pack, write it in the canvas instead.
