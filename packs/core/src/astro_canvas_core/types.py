"""Core port types (``astro.*``) shared by every pack."""

from __future__ import annotations

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
    decimate,
    port_type,
)

Frame = Literal["observed", "rest", "velocity"]
ARROW_PART = "table.arrow"

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
        """Decimated ``wave``/``flux`` (<= ``n_out`` points, default 4000) for the preview."""
        n_out = int((viewport or {}).get("n_out", 4000))
        wave, flux = self.wave, self.flux
        if viewport and "lo" in viewport and "hi" in viewport:
            keep = (wave >= float(viewport["lo"])) & (wave <= float(viewport["hi"]))
            wave, flux = wave[keep], flux[keep]
        dw, df = decimate(wave, flux, n_out=n_out)
        return {
            "type": self.type_id(),
            "n": len(self),
            "wave": dw.tolist(),
            "flux": df.tolist(),
            "wave_unit": self.wave_unit,
            "flux_unit": self.flux_unit,
            "frame": self.frame,
            "z": self.z,
        }


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
        per_item = {"n_out": int((viewport or {}).get("n_out", 512))}
        return {
            "type": self.type_id(),
            "count": len(self.items),
            "labels": self.labels,
            "items": [s.summary(per_item) for s in self.items[:8]],
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

    def summary(self, viewport: Mapping[str, TypingAny] | None = None) -> dict[str, TypingAny]:
        head = int((viewport or {}).get("rows", 20))
        return {
            "type": self.type_id(),
            "n_rows": self.n_rows,
            "columns": list(self.columns),
            "units": self.units,
            "head": {name: col[:head].tolist() for name, col in self.columns.items()},
        }


@port_type(id="astro.Image2D", color="#EC4899", summary_renderer="image-thumb")
class Image2D(PortType):
    """A 2-d image with FITS header and WCS (as plain dicts)."""

    data: Float32_2D
    header: dict[str, TypingAny] = {}
    wcs: dict[str, TypingAny] | None = None
    unit: str | None = None


@port_type(id="astro.Cube3D", color="#DB2777", summary_renderer="cube-thumb")
class Cube3D(PortType):
    """An IFU data cube ``flux[nz, ny, nx]`` with its wavelength axis."""

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
    """A list of transitions as parallel arrays."""

    wrest: Float1D
    name: StrArray
    fval: Float1D
    gamma: Float1D | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _same_length(self) -> LineList:
        n = self.wrest.shape[0]
        if self.name.shape[0] != n or self.fval.shape[0] != n:
            raise ValueError("wrest, name and fval must have the same length")
        if self.gamma is not None and self.gamma.shape[0] != n:
            raise ValueError("gamma must have the same length as wrest")
        return self

    def __len__(self) -> int:
        return int(self.wrest.shape[0])


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
        size = len(self.png) if self.png is not None else len(str(self.plotly))
        return {"type": self.type_id(), "kind": self.kind, "size": size}


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
