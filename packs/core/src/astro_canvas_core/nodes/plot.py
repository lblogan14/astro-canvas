"""``core.plot.*`` nodes: Plotly figures for spectra, images and tables, plus figure export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np

from astro_canvas.sdk import NodeContext, Param, decimate_indices, node
from astro_canvas_core.io.paths import describe_file, resolve_in_workspace
from astro_canvas_core.types import Figure, Image2D, Spectrum1D, Table, image_tile, zscale_limits

COLORMAPS = ("viridis", "gray", "magma", "cubehelix", "inferno", "plasma", "cividis")
_PLOTLY_SCALES = {
    "viridis": "Viridis",
    "gray": "Greys",
    "magma": "Magma",
    "cubehelix": "Cividis",
    "inferno": "Inferno",
    "plasma": "Plasma",
    "cividis": "Cividis",
}


def _clean(values: np.ndarray) -> list[float | None]:
    return [None if not np.isfinite(v) else float(v) for v in values.tolist()]


@node(id="core.plot.spectrum", name="Plot Spectrum", category="Plot", icon="chart-line")
def plot_spectrum(
    spec: Spectrum1D,
    show_error: Annotated[bool, Param(label="Show error")] = True,
    show_continuum: Annotated[bool, Param(label="Show continuum")] = True,
    title: str = "",
    max_points: Annotated[int, Param(min=100, max=200000, advanced=True)] = 20000,
) -> Figure:
    """Build a Plotly line plot of a spectrum (WebGL traces, decimated to ``max_points``).

    Args:
        spec: The spectrum to draw.
        show_error: Draw the error array as a second trace.
        show_continuum: Draw the continuum when present.
        title: Figure title (defaults to the source file name).
        max_points: Point budget per trace (MinMaxLTTB decimation preserves extrema).

    Returns:
        A Plotly figure (JSON ``data``/``layout``).
    """
    pick = decimate_indices(spec.wave, spec.flux, n_out=max_points)
    wave = spec.wave[pick]
    traces: list[dict[str, Any]] = [
        {
            "type": "scattergl",
            "mode": "lines",
            "name": "flux",
            "x": _clean(wave),
            "y": _clean(spec.flux[pick]),
            "line": {"width": 1, "color": "#5B8DEF"},
        }
    ]
    if show_error and spec.error is not None:
        traces.append(
            {
                "type": "scattergl",
                "mode": "lines",
                "name": "error",
                "x": _clean(wave),
                "y": _clean(spec.error[pick]),
                "line": {"width": 1, "color": "#D64545"},
            }
        )
    if show_continuum and spec.continuum is not None:
        traces.append(
            {
                "type": "scattergl",
                "mode": "lines",
                "name": "continuum",
                "x": _clean(wave),
                "y": _clean(spec.continuum[pick]),
                "line": {"width": 1.5, "color": "#1C9C5A", "dash": "dash"},
            }
        )
    x_title = {
        "observed": f"Wavelength ({spec.wave_unit})",
        "rest": f"Rest wavelength ({spec.wave_unit})",
        "velocity": "Velocity (km/s)",
    }[spec.frame]
    layout = {
        "title": {"text": title or str(spec.meta.get("source", ""))},
        "xaxis": {"title": {"text": x_title}},
        "yaxis": {"title": {"text": f"Flux ({spec.flux_unit})"}},
        "dragmode": "zoom",
        "margin": {"l": 60, "r": 20, "t": 40, "b": 50},
        "legend": {"orientation": "h"},
    }
    return Figure(kind="plotly", plotly={"data": traces, "layout": layout})


@node(id="core.plot.image", name="Plot Image", category="Plot", icon="image")
def plot_image(
    image: Image2D,
    scale: Annotated[Literal["zscale", "minmax", "percentile"], Param(label="Scaling")] = "zscale",
    stretch: Annotated[Literal["linear", "asinh", "log"], Param(label="Stretch")] = "linear",
    colormap: Annotated[str, Param(choices=COLORMAPS, label="Colour map")] = "viridis",
    max_size: Annotated[int, Param(min=32, max=2048, advanced=True)] = 512,
    title: str = "",
) -> Figure:
    """Build a Plotly heatmap of an image (downsampled to ``max_size`` per edge).

    Args:
        image: The image to draw.
        scale: How to pick display limits.
        stretch: Intensity stretch applied before drawing.
        colormap: Colour map name.
        max_size: Maximum tile edge in pixels.
        title: Figure title.

    Returns:
        A Plotly figure with one ``heatmap`` trace.
    """
    tile = image_tile(image.data, max_size)
    step = tile["step"]
    data = image.data[::step, ::step].astype(np.float64)
    if scale == "zscale":
        lo, hi = zscale_limits(data)
    elif scale == "percentile":
        lo, hi = (float(v) for v in tile["percentile"])
    else:
        lo, hi = (float(v) for v in tile["minmax"])
    with np.errstate(all="ignore"):
        if stretch == "asinh":
            span = max(hi - lo, 1e-30)
            data = np.arcsinh((data - lo) / span * 10.0) / np.arcsinh(10.0)
            lo, hi = 0.0, 1.0
        elif stretch == "log":
            span = max(hi - lo, 1e-30)
            data = np.log10(np.clip((data - lo) / span, 0.0, None) * 1000.0 + 1.0) / 3.0
            lo, hi = 0.0, 1.0
    z = [_clean(row) for row in data]
    trace = {
        "type": "heatmap",
        "z": z,
        "zmin": lo,
        "zmax": hi,
        "colorscale": _PLOTLY_SCALES.get(colormap, "Viridis"),
        "x": (np.arange(data.shape[1]) * step).tolist(),
        "y": (np.arange(data.shape[0]) * step).tolist(),
        "colorbar": {"title": {"text": image.unit or ""}},
    }
    layout = {
        "title": {
            "text": title or str(image.header.get("OBJECT") or image.header.get("_SOURCE", ""))
        },
        "xaxis": {"title": {"text": "x (pixel)"}, "constrain": "domain"},
        "yaxis": {"title": {"text": "y (pixel)"}, "scaleanchor": "x", "autorange": True},
        "margin": {"l": 50, "r": 20, "t": 40, "b": 50},
    }
    return Figure(kind="plotly", plotly={"data": [trace], "layout": layout})


@node(id="core.plot.table", name="Plot Table", category="Plot", icon="table")
def plot_table(
    table: Table,
    rows: Annotated[int, Param(min=1, max=5000, label="Rows")] = 100,
    title: str = "",
) -> Figure:
    """Build a Plotly table figure of the first ``rows`` rows.

    Args:
        table: The table to display.
        rows: Number of rows to include.
        title: Figure title.

    Returns:
        A Plotly figure with one ``table`` trace.
    """
    header = list(table.columns)
    cells: list[list[Any]] = []
    for name in header:
        column = table.columns[name][:rows]
        if column.dtype.kind == "f":
            cells.append(_clean(column))
        else:
            cells.append([str(v) for v in column.tolist()])
    trace = {
        "type": "table",
        "header": {
            "values": [f"{n} ({table.units[n]})" if n in table.units else n for n in header]
        },
        "cells": {"values": cells},
    }
    layout = {"title": {"text": title}, "margin": {"l": 10, "r": 10, "t": 40, "b": 10}}
    return Figure(kind="plotly", plotly={"data": [trace], "layout": layout})


@node(id="core.plot.figure_export", name="Export Figure", category="Plot", icon="download")
def figure_export(
    figure: Figure,
    path: Annotated[str, Param(label="Output path")] = "outputs/figure.json",
    format: Annotated[Literal["json", "html", "png"], Param(label="Format")] = "json",  # noqa: A002
    ctx: NodeContext | None = None,
) -> Any:
    """Write a figure into the workspace as Plotly JSON, a standalone HTML page, or PNG.

    PNG export needs the figure to already be a PNG (``kind='png'``); rendering Plotly JSON to
    PNG requires a browser engine and is done from the viewer's download button instead.

    Args:
        figure: The figure to export.
        path: Workspace-relative output path (folders are created).
        format: Output format.

    Returns:
        The written file.
    """
    root = Path(ctx.workspace) if ctx is not None else Path.cwd()
    target = resolve_in_workspace(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if format == "png":
        if figure.png is None:
            raise ValueError("only PNG figures can be exported as PNG; use json or html")
        target.write_bytes(figure.png)
    elif figure.plotly is None:
        raise ValueError("a PNG figure cannot be exported as Plotly JSON/HTML")
    elif format == "json":
        target.write_text(json.dumps(figure.plotly, separators=(",", ":")), encoding="utf-8")
    else:
        payload = json.dumps(figure.plotly, separators=(",", ":"))
        target.write_text(
            "<!doctype html><html><head><meta charset='utf-8'><title>Astro Canvas figure</title>"
            "<script src='https://cdn.plot.ly/plotly-3.0.0.min.js' charset='utf-8'></script>"
            "</head><body><div id='fig' style='width:100%;height:100vh'></div><script>"
            f"var f={payload};Plotly.newPlot('fig',f.data,f.layout,{{responsive:true}});"
            "</script></body></html>",
            encoding="utf-8",
        )
    return describe_file(root, target)
