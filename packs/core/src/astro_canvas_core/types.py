"""Core port types (``astro.*``) shared by every pack."""

from __future__ import annotations

import base64
import contextlib
import math
from collections.abc import Mapping
from typing import Any as TypingAny
from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, JsonValue, model_validator

from astro_canvas.sdk import (
    Blob,
    BlobError,
    Float1D,
    Float32_2D,
    Float32_3D,
    NDArray,
    PortType,
    StrArray,
    decimate_indices,
    port_type,
)

Frame = Literal["observed", "rest", "velocity"]
ARROW_PART = "table.arrow"
DEFAULT_TILE = 128
"""Default edge length of image thumbnails in summaries (``n_out`` in the viewport raises it)."""
MAX_TILE = 1024
DEFAULT_TABLE_ROWS = 50
SUMMARY_BYTES = 32 * 1024 * 1024
"""How much of a cube a summary may read; larger cubes are sampled with a stride."""


def _viewport_int(
    viewport: Mapping[str, TypingAny] | None, key: str, default: int, cap: int
) -> int:
    try:
        value = int((viewport or {}).get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, cap))


def zscale_limits(data: npt.NDArray[TypingAny]) -> tuple[float, float]:
    """IRAF/ds9-style zscale display limits of ``data`` (NaNs ignored), via astropy."""
    from astropy.visualization import ZScaleInterval  # noqa: PLC0415 - lazy import

    finite = np.asarray(data, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return 0.0, 1.0
    if finite.size < 5 or float(finite.min()) == float(finite.max()):
        return float(finite.min()), float(finite.max())
    lo, hi = ZScaleInterval().get_limits(finite)
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo == hi:
        return float(finite.min()), float(finite.max())
    return float(lo), float(hi)


def _stride_to_budget(
    index: npt.NDArray[np.intp], item_bytes: int, max_bytes: int | None
) -> npt.NDArray[np.intp]:
    """Thin ``index`` with an even stride so ``len(index) * item_bytes <= max_bytes``."""
    if max_bytes is None or max_bytes <= 0 or item_bytes <= 0 or index.size == 0:
        return index
    step = max(1, math.ceil(index.size * item_bytes / max_bytes))
    return index[::step]


def image_tile(data: npt.NDArray[TypingAny], max_size: int) -> dict[str, TypingAny]:
    """A stride-downsampled float32 tile (edge <= ``max_size``) plus display statistics.

    The tile travels inside the JSON summary as base64 little-endian float32 rows (``height`` x
    ``width``); ``step`` is the integer stride so the client can map tile pixels back to data.
    """
    array = np.asarray(data, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError("image_tile expects a 2-d array")
    ny, nx = array.shape
    step = max(1, math.ceil(max(ny, nx) / max(1, max_size)))
    tile = np.ascontiguousarray(array[::step, ::step], dtype="<f4")
    finite = tile[np.isfinite(tile)]
    lo, hi = zscale_limits(tile)
    stats: dict[str, TypingAny] = {
        "width": int(tile.shape[1]),
        "height": int(tile.shape[0]),
        "step": int(step),
        "dtype": "f4",
        "b64": base64.b64encode(tile.tobytes()).decode("ascii"),
        "zscale": [lo, hi],
    }
    if finite.size:
        p1, p99 = np.percentile(finite, [1.0, 99.0])
        stats["minmax"] = [float(finite.min()), float(finite.max())]
        stats["percentile"] = [float(p1), float(p99)]
    else:
        stats["minmax"] = [0.0, 1.0]
        stats["percentile"] = [0.0, 1.0]
    return stats


# --- scalars -----------------------------------------------------------------------------------


@port_type(id="astro.Float", color="#9CA3AF", summary_renderer="value-chip")
class Float(PortType):
    """A floating-point number."""

    value: float


@port_type(id="astro.Int", color="#9CA3AF", summary_renderer="value-chip")
class Int(PortType):
    """An integer."""

    value: int


@port_type(id="astro.Str", color="#9CA3AF", summary_renderer="value-chip")
class Str(PortType):
    """A string."""

    value: str


@port_type(id="astro.Bool", color="#9CA3AF", summary_renderer="value-chip")
class Bool(PortType):
    """A boolean."""

    value: bool


@port_type(id="astro.Json", color="#A78BFA", summary_renderer="value-chip")
class Json(PortType):
    """Any JSON value (objects, arrays, scalars)."""

    value: JsonValue


@port_type(id="astro.File", color="#F59E0B", summary_renderer="file-chip")
class File(PortType):
    """A workspace file: relative path, content hash, size, and MIME type."""

    path: str
    blake3: str | None = None
    size: int = 0
    mime: str | None = None


# --- spectra -----------------------------------------------------------------------------------


@port_type(
    id="astro.Spectrum1D",
    color="#5B8DEF",
    summary_renderer="spectrum-thumb",
    compatible_with=["astro.SpectrumCollection"],
)
class Spectrum1D(PortType):
    """A one-dimensional spectrum: wavelength (or velocity) grid, flux, optional error/continuum."""

    wave: Float1D
    flux: Float1D
    error: Float1D | None = None
    continuum: Float1D | None = None
    wave_unit: str = "Angstrom"
    flux_unit: str = "erg / (s cm2 Angstrom)"
    frame: Frame = "observed"
    z: float | None = None
    v0_wrest: float | None = None
    meta: dict[str, TypingAny] = {}

    @model_validator(mode="after")
    def _same_length(self) -> Spectrum1D:
        n = self.wave.shape[0]
        for name in ("flux", "error", "continuum"):
            arr = getattr(self, name)
            if arr is not None and arr.shape[0] != n:
                raise ValueError(f"{name} has {arr.shape[0]} points, wave has {n}")
        return self

    def __len__(self) -> int:
        return int(self.wave.shape[0])

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        """Decimated ``wave``/``flux`` (and ``error``/``continuum``) for the preview.

        ``viewport`` may carry ``lo``/``hi`` (axis range to keep) and ``n_out`` (point budget,
        default 4000, max 20000). Every series is sampled at the same MinMaxLTTB indices so the
        client can draw error bands and continuum overlays without re-aligning.
        """
        n_out = _viewport_int(viewport, "n_out", 4000, 20000)
        index = np.arange(len(self))
        if viewport and "lo" in viewport and "hi" in viewport:
            lo, hi = float(viewport["lo"]), float(viewport["hi"])
            index = index[(self.wave >= min(lo, hi)) & (self.wave <= max(lo, hi))]
        wave, flux = self.wave[index], self.flux[index]
        pick = index[decimate_indices(wave, flux, n_out=n_out)]
        # Non-finite values become ``null``: ``json.dumps`` would emit ``NaN``, which browsers
        # reject (SDSS pixels with ``ivar = 0`` have an infinite/NaN error).
        out: dict[str, TypingAny] = {
            "type": self.type_id(),
            "n": len(self),
            "n_view": int(index.size),
            "range": [float(self.wave[0]), float(self.wave[-1])] if len(self) else None,
            "wave": _json_list(self.wave[pick]),
            "flux": _json_list(self.flux[pick]),
            "wave_unit": self.wave_unit,
            "flux_unit": self.flux_unit,
            "frame": self.frame,
            "z": self.z,
            "v0_wrest": self.v0_wrest,
        }
        if self.error is not None:
            out["error"] = _json_list(self.error[pick])
        if self.continuum is not None:
            out["continuum"] = _json_list(self.continuum[pick])
        return out


@port_type(id="astro.SpectrumCollection", color="#3B6FD6", summary_renderer="spectrum-stack")
class SpectrumCollection(PortType):
    """An ordered list of spectra (e.g. one per object or exposure)."""

    items: list[Spectrum1D]
    labels: list[str] = []

    @model_validator(mode="after")
    def _labels_match(self) -> SpectrumCollection:
        if self.labels and len(self.labels) != len(self.items):
            raise ValueError("labels must match items")
        return self

    def __len__(self) -> int:
        return len(self.items)

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        """Up to ``max_items`` (default 8, at most 64) item summaries at ``n_out`` points each.

        ``count`` is always the full length, so a client can tell that it received a prefix; the
        multi-spectrum viewer raises ``max_items`` to show every panel.
        """
        per_item = {"n_out": _viewport_int(viewport, "n_out", 512, 20000)}
        max_items = _viewport_int(viewport, "max_items", 8, 64)
        return {
            "type": self.type_id(),
            "count": len(self.items),
            "labels": self.labels,
            "items": [s.summary(per_item) for s in self.items[:max_items]],
        }


# --- tables and images -------------------------------------------------------------------------


@port_type(id="astro.Table", color="#10B981", summary_renderer="table-grid")
class Table(PortType):
    """A column-oriented table (Arrow IPC on disk; astropy ``Table`` friendly)."""

    columns: dict[str, NDArray]
    units: dict[str, str] = {}
    meta: dict[str, TypingAny] = {}

    @model_validator(mode="after")
    def _rectangular(self) -> Table:
        lengths = {len(col) for col in self.columns.values()}
        if len(lengths) > 1:
            raise ValueError(f"columns have different lengths: {sorted(lengths)}")
        return self

    @property
    def n_rows(self) -> int:
        return len(next(iter(self.columns.values()))) if self.columns else 0

    def to_blob(self) -> Blob:
        import pyarrow as pa  # noqa: PLC0415 - lazy: pyarrow only when blobbing tables

        table = pa.table({name: pa.array(col) for name, col in self.columns.items()})
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        manifest = {
            "type": self.type_id(),
            "data": {"units": self.units, "meta": self.meta, "dtypes": self.dtypes()},
        }
        return Blob(manifest=manifest, parts={ARROW_PART: sink.getvalue().to_pybytes()})

    @classmethod
    def from_blob(cls, blob: Blob) -> Table:
        import pyarrow as pa  # noqa: PLC0415 - lazy: pyarrow only when blobbing tables

        if blob.manifest.get("type") != cls.type_id() or ARROW_PART not in blob.parts:
            raise BlobError("blob is not an astro.Table")
        table = pa.ipc.open_stream(pa.py_buffer(blob.parts[ARROW_PART])).read_all()
        data = blob.manifest.get("data", {})
        dtypes: dict[str, str] = data.get("dtypes", {})
        columns: dict[str, npt.NDArray[TypingAny]] = {}
        for name in table.column_names:
            values = table.column(name).to_pylist()
            columns[name] = np.asarray(values, dtype=dtypes.get(name))
        return cls(columns=columns, units=data.get("units", {}), meta=data.get("meta", {}))

    def dtypes(self) -> dict[str, str]:
        return {name: col.dtype.str for name, col in self.columns.items()}

    def head_arrow(self, rows: int) -> bytes:
        """Arrow IPC stream of the first ``rows`` rows."""
        import pyarrow as pa  # noqa: PLC0415 - lazy: pyarrow only when blobbing tables

        table = pa.table({name: pa.array(col[:rows]) for name, col in self.columns.items()})
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        return bytes(sink.getvalue().to_pybytes())

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        """Shape, column names/units/dtypes and the first rows (JSON and Arrow IPC base64)."""
        rows = _viewport_int(viewport, "rows", DEFAULT_TABLE_ROWS, 1000)
        head = {name: _json_list(col[:rows]) for name, col in self.columns.items()}
        out: dict[str, TypingAny] = {
            "type": self.type_id(),
            "n_rows": self.n_rows,
            "columns": list(self.columns),
            "units": self.units,
            "dtypes": self.dtypes(),
            "head": head,
        }
        # Arrow is a convenience for the grid widget; the JSON head always works.
        with contextlib.suppress(Exception):
            out["arrow_b64"] = base64.b64encode(self.head_arrow(rows)).decode("ascii")
        return out


def _json_list(values: npt.NDArray[TypingAny]) -> list[TypingAny]:
    if values.dtype.kind == "f":
        return [None if not math.isfinite(v) else float(v) for v in values.tolist()]
    return [v for v in values.tolist()]


@port_type(id="astro.Image2D", color="#EC4899", summary_renderer="image-thumb")
class Image2D(PortType):
    """A 2-d image with FITS header and WCS (as plain dicts)."""

    data: Float32_2D
    header: dict[str, TypingAny] = {}
    wcs: dict[str, TypingAny] | None = None
    unit: str | None = None

    @property
    def shape(self) -> tuple[int, int]:
        return int(self.data.shape[0]), int(self.data.shape[1])

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        """A downsampled float32 tile (edge <= ``n_out``, default 128) with zscale limits."""
        size = _viewport_int(viewport, "n_out", DEFAULT_TILE, MAX_TILE)
        return {
            "type": self.type_id(),
            "shape": list(self.shape),
            "unit": self.unit,
            "wcs": self.wcs,
            "object": self.header.get("OBJECT"),
            "tile": image_tile(self.data, size),
        }


@port_type(id="astro.Cube3D", color="#DB2777", summary_renderer="cube-thumb")
class Cube3D(PortType):
    """An IFU data cube ``flux[nz, ny, nx]`` with its wavelength axis.

    ``flux`` and ``var`` are stored as their own blob parts, so a cube read back from the cache is
    a read-only ``numpy.memmap`` over the content-addressed store rather than a copy in the
    server's heap (``PortType.from_blob_file``). Collapses and summaries therefore touch only the
    channels they need; nothing here reads the whole array.
    """

    __mmap_fields__ = ("flux", "var")

    flux: Float32_3D
    var: Float32_3D | None = None
    wave: Float1D
    wcs: dict[str, TypingAny] | None = None
    header: dict[str, TypingAny] = {}
    instrument: str | None = None

    @model_validator(mode="after")
    def _axes(self) -> Cube3D:
        if self.wave.shape[0] != self.flux.shape[0]:
            raise ValueError("wave length must equal flux.shape[0]")
        if self.var is not None and self.var.shape != self.flux.shape:
            raise ValueError("var must have the same shape as flux")
        return self

    @property
    def shape(self) -> tuple[int, int, int]:
        return int(self.flux.shape[0]), int(self.flux.shape[1]), int(self.flux.shape[2])

    def band(self, lo: float | None = None, hi: float | None = None) -> npt.NDArray[np.bool_]:
        """Channel mask for ``[lo, hi]`` (every channel when the window selects nothing)."""
        keep = np.ones(self.wave.shape[0], dtype=bool)
        if lo is not None:
            keep &= self.wave >= lo
        if hi is not None:
            keep &= self.wave <= hi
        if not keep.any():
            keep[:] = True
        return keep

    def white_light(
        self,
        lo: float | None = None,
        hi: float | None = None,
        max_bytes: int | None = None,
    ) -> npt.NDArray[np.float32]:
        """Mean over the spectral axis (optionally restricted to ``[lo, hi]``), NaN-aware.

        ``max_bytes`` caps how much of the cube is read: channels are then sampled with an even
        stride, which is what summaries use so a 500 MB cube never lands in memory at once.
        """
        keep = np.flatnonzero(self.band(lo, hi))
        keep = _stride_to_budget(keep, self.plane_bytes(), max_bytes)
        with np.errstate(all="ignore"):
            image = np.nanmean(self.flux[keep], axis=0)
        return np.asarray(image, dtype=np.float32)

    def plane_bytes(self) -> int:
        """Bytes in one spectral plane (``ny * nx * 4``)."""
        return int(self.flux.shape[1]) * int(self.flux.shape[2]) * 4

    def integrated(self, max_bytes: int | None = None) -> npt.NDArray[np.float64]:
        """Spatially summed spectrum, read in wavelength chunks (never the whole cube at once).

        With ``max_bytes`` the spatial rows are strided and the sum is rescaled, so the curve keeps
        its shape and amplitude while only a fraction of the cube is paged in.
        """
        nz, ny, _ = self.shape
        step = 1
        if max_bytes is not None and max_bytes > 0:
            per_row = int(self.flux.shape[2]) * 4 * nz
            step = max(1, math.ceil(per_row * ny / max_bytes))
        rows = np.arange(0, ny, step)
        chunk = max(1, min(nz, (16 * 1024 * 1024) // max(1, len(rows) * int(self.shape[2]) * 4)))
        out = np.empty(nz, dtype=np.float64)
        with np.errstate(all="ignore"):
            for start in range(0, nz, chunk):
                stop = min(nz, start + chunk)
                block = np.asarray(self.flux[start:stop, rows, :], dtype=np.float64)
                out[start:stop] = np.nansum(block, axis=(1, 2))
        return out * (ny / max(1, len(rows)))

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        """White-light thumbnail (``lo``/``hi`` restrict the band) plus the integrated spectrum.

        Both are computed from a strided sample capped at ``SUMMARY_BYTES``: previewing a cube
        must stay cheap however large it is.
        """
        size = _viewport_int(viewport, "n_out", DEFAULT_TILE, MAX_TILE)
        lo = viewport.get("lo") if viewport else None
        hi = viewport.get("hi") if viewport else None
        band = (float(lo) if lo is not None else None, float(hi) if hi is not None else None)
        integrated = self.integrated(max_bytes=SUMMARY_BYTES)
        pick = decimate_indices(self.wave, integrated, n_out=512)
        return {
            "type": self.type_id(),
            "shape": list(self.shape),
            "instrument": self.instrument,
            "object": self.header.get("OBJECT"),
            "wave_unit": self.header.get("_WAVEUNIT", "Angstrom"),
            "wave_range": [float(self.wave[0]), float(self.wave[-1])] if self.wave.size else None,
            "band": [band[0], band[1]],
            "has_var": self.var is not None,
            "wcs": self.wcs,
            "tile": image_tile(self.white_light(*band, max_bytes=SUMMARY_BYTES), size),
            "spectrum": {
                "wave": _json_list(self.wave[pick]),
                "flux": _json_list(integrated[pick]),
            },
        }


# --- lines, redshifts, continua ----------------------------------------------------------------


@port_type(id="astro.Transition", color="#F97316", summary_renderer="chip")
class Transition(PortType):
    """One atomic transition: rest wavelength (Angstrom), oscillator strength, damping constant."""

    name: str
    wrest: float
    fval: float
    gamma: float | None = None


@port_type(id="astro.LineList", color="#FB923C", summary_renderer="linelist-chip")
class LineList(PortType):
    """A list of transitions as parallel arrays.

    ``weight`` and ``kind`` (``emission``/``absorption``) are optional columns used by redshift
    finders (rbcodes' curated zfind presets carry both); atomic lists leave them unset.
    """

    wrest: Float1D
    name: StrArray
    fval: Float1D
    gamma: Float1D | None = None
    weight: Float1D | None = None
    kind: StrArray | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _same_length(self) -> LineList:
        n = self.wrest.shape[0]
        if self.name.shape[0] != n or self.fval.shape[0] != n:
            raise ValueError("wrest, name and fval must have the same length")
        for column in ("gamma", "weight", "kind"):
            arr = getattr(self, column)
            if arr is not None and arr.shape[0] != n:
                raise ValueError(f"{column} must have the same length as wrest")
        return self

    def __len__(self) -> int:
        return int(self.wrest.shape[0])

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        """Up to ``rows`` transitions (default 2000) as parallel lists for line pickers."""
        rows = _viewport_int(viewport, "rows", 2000, 5000)
        out: dict[str, TypingAny] = {
            "type": self.type_id(),
            "n": len(self),
            "source": self.source,
            "wrest": self.wrest[:rows].tolist(),
            "name": [str(v) for v in self.name[:rows].tolist()],
            "fval": self.fval[:rows].tolist(),
        }
        if self.gamma is not None:
            out["gamma"] = self.gamma[:rows].tolist()
        if self.weight is not None:
            out["weight"] = self.weight[:rows].tolist()
        if self.kind is not None:
            out["kind"] = [str(v) for v in self.kind[:rows].tolist()]
        return out


@port_type(id="astro.Redshift", color="#EAB308", summary_renderer="chip")
class Redshift(PortType):
    """A redshift with optional uncertainty and provenance."""

    z: float
    z_err: float | None = None
    method: str | None = None
    source: str | None = None


@port_type(id="astro.Continuum", color="#84CC16", summary_renderer="continuum-thumb")
class Continuum(PortType):
    """A fitted continuum on a spectrum's grid plus the masks and method used."""

    cont: Float1D
    masks: list[tuple[float, float]] = []
    method: str = ""
    order: int | None = None
    params: dict[str, TypingAny] = {}
    bic: float | None = None

    def __len__(self) -> int:
        return int(self.cont.shape[0])

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        """The continuum values (whole when they fit ``n_out``, else strided with ``index``).

        ``index`` lists the sampled positions on the spectrum grid so an editor can overlay the
        continuum on a full-resolution spectrum; ``masks``, ``order`` and ``bic`` travel as is.
        """
        n_out = _viewport_int(viewport, "n_out", 20000, 200000)
        n = len(self)
        strided = np.unique(np.linspace(0, max(n - 1, 0), n_out).astype(int))
        index = np.arange(n) if n <= n_out else strided
        return {
            "type": self.type_id(),
            "n": n,
            "index": index.tolist(),
            "cont": _json_list(self.cont[index]),
            "masks": [[float(lo), float(hi)] for lo, hi in self.masks],
            "method": self.method,
            "order": self.order,
            "bic": self.bic,
            "params": summarize_params(self.params),
        }


def summarize_params(value: TypingAny) -> TypingAny:
    """JSON-safe copy of a params dict (arrays to lists, numpy scalars to Python, NaN to null)."""
    if isinstance(value, np.ndarray):
        return summarize_params(value.tolist())
    if isinstance(value, np.generic):
        return summarize_params(value.item())
    if isinstance(value, Mapping):
        return {str(k): summarize_params(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [summarize_params(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


@port_type(id="astro.RangeMask", color="#22C55E", summary_renderer="chip")
class RangeMask(PortType):
    """Intervals ``[lo, hi]`` in a stated frame and unit."""

    ranges: list[tuple[float, float]]
    frame: Frame = "observed"
    unit: str = "Angstrom"


# --- regions, measurements, figures, escape hatch ----------------------------------------------


class Region(BaseModel):
    """One aperture in pixel coordinates (and optionally sky coordinates in degrees)."""

    shape: Literal["circle", "box", "annulus", "polygon"]
    pixel: list[float]
    sky: list[float] | None = None
    label: str | None = None


@port_type(id="astro.Region2D", color="#14B8A6", summary_renderer="region-overlay")
class Region2D(PortType):
    """A set of apertures drawn on an image."""

    regions: list[Region]


@port_type(id="astro.EWMeasurement", color="#6366F1", summary_renderer="kv-tile")
class EWMeasurement(PortType):
    """Equivalent width and apparent-optical-depth column density of one transition."""

    W: float
    W_e: float
    N: float | None = None
    N_e: float | None = None
    logN: float | None = None
    logN_e: float | None = None
    vel_centroid: float | None = None
    vel_disp: float | None = None
    vel50_err: float | None = None
    SNR: float | None = None
    saturated: bool = False
    flag: int = 0
    vmin: float | None = None
    vmax: float | None = None
    transition: Transition | None = None


@port_type(id="astro.Figure", color="#8B5CF6", summary_renderer="figure")
class Figure(PortType):
    """A rendered figure: Plotly JSON or PNG bytes."""

    kind: Literal["plotly", "png"]
    plotly: dict[str, TypingAny] | None = None
    png: bytes | None = None

    @model_validator(mode="after")
    def _payload(self) -> Figure:
        if (self.kind == "plotly") != (self.plotly is not None) or (self.kind == "png") != (
            self.png is not None
        ):
            raise ValueError("Figure needs exactly the payload matching its kind")
        return self

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        """Kind and size; the payload itself is inlined when it is small enough to preview."""
        import json  # noqa: PLC0415

        out: dict[str, TypingAny] = {"type": self.type_id(), "kind": self.kind}
        if self.png is not None:
            out["size"] = len(self.png)
            if len(self.png) <= 400_000:
                out["png_b64"] = base64.b64encode(self.png).decode("ascii")
        else:
            text = json.dumps(self.plotly, separators=(",", ":"), default=_json_default)
            out["size"] = len(text)
            if len(text) <= 400_000:
                out["plotly"] = json.loads(text)
        return out


def _json_default(value: TypingAny) -> TypingAny:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON-serializable")


@port_type(id="astro.Any", color="#6B7280", summary_renderer="type-name")
class Any(PortType):
    """An opaque in-process Python object. Never persisted to caches or bundles."""

    value: TypingAny

    def to_blob(self) -> Blob:
        raise BlobError("astro.Any values are in-process only and cannot be serialized")

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        return {"type": self.type_id(), "python_type": type(self.value).__name__}


ALL_TYPES: tuple[type[PortType], ...] = (
    Float,
    Int,
    Str,
    Bool,
    Json,
    File,
    Spectrum1D,
    SpectrumCollection,
    Table,
    Image2D,
    Cube3D,
    Transition,
    LineList,
    Redshift,
    Continuum,
    RangeMask,
    Region2D,
    EWMeasurement,
    Figure,
    Any,
)
