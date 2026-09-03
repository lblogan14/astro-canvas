"""Table reader: FITS binary tables, ECSV, CSV/ASCII, VOTable and JSON rows into ``astro.Table``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from astropy.io import fits
from astropy.table import Table as AstroTable

from astro_canvas_core.types import Table

TableFormat = Literal["auto", "fits", "ecsv", "csv", "ascii", "votable", "json"]
TABLE_FORMATS: tuple[str, ...] = ("auto", "fits", "ecsv", "csv", "ascii", "votable", "json")
_FITS_SUFFIXES = (".fits", ".fit", ".fts")


class TableReadError(ValueError):
    """The file could not be read as a table."""


def _column_array(column: Any) -> npt.NDArray[Any] | None:
    """A 1-d numpy array for an astropy column (``None`` for multi-dimensional cells)."""
    if np.ma.isMaskedArray(column):
        kind = np.asarray(column).dtype.kind
        if kind in "iu":
            # Missing integers become NaN, so the column turns into float64.
            data = np.ma.filled(np.ma.asarray(column, dtype=np.float64), np.nan)
        elif kind == "f":
            data = np.ma.filled(column, np.nan)
        elif kind == "b":
            data = np.ma.filled(column, False)
        else:
            data = np.ma.filled(column, "")
    else:
        data = column
    array = np.asarray(data)
    if array.ndim != 1:
        return None
    if array.dtype.kind in "SU" or array.dtype == object:
        return np.asarray([str(v) for v in array.tolist()], dtype=np.str_)
    if array.dtype.kind == "b":
        return array.astype(bool)
    if array.dtype.kind in "iu":
        return array.astype(np.int64)
    if array.dtype.kind == "f":
        return array.astype(np.float64)
    return np.asarray([str(v) for v in array.tolist()], dtype=np.str_)


def from_astropy(table: AstroTable) -> Table:
    """Convert an astropy ``Table`` (masked or plain) into the ``astro.Table`` port type."""
    columns: dict[str, npt.NDArray[Any]] = {}
    units: dict[str, str] = {}
    skipped: list[str] = []
    for name in table.colnames:
        column = table[name]
        array = _column_array(column)
        if array is None:
            skipped.append(name)
            continue
        columns[str(name)] = array
        unit = getattr(column, "unit", None)
        if unit is not None and str(unit):
            units[str(name)] = str(unit)
    meta: dict[str, Any] = {}
    for key, value in dict(table.meta or {}).items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        meta[str(key)] = value
    if skipped:
        meta["skipped_columns"] = skipped
    return Table(columns=columns, units=units, meta=meta)


def _read_fits_table(path: Path, ext: int | str | None) -> AstroTable:
    with fits.open(path, memmap=False) as hdul:
        if ext is None:
            for index, hdu in enumerate(hdul):
                if isinstance(hdu, fits.BinTableHDU | fits.TableHDU):
                    ext = index
                    break
            if ext is None:
                raise TableReadError("no table extension in the FITS file")
        if isinstance(ext, str) and ext.strip().lstrip("-").isdigit():
            ext = int(ext)
        try:
            hdu = hdul[ext]
        except (KeyError, IndexError):
            raise TableReadError(f"no extension {ext!r} in the file") from None
        if not isinstance(hdu, fits.BinTableHDU | fits.TableHDU):
            raise TableReadError(f"extension {ext!r} is not a table")
        table = AstroTable(hdu.data)
        table.meta["extname"] = hdu.name
        return table


def read_astropy_table(path: Path, fmt: str = "auto", ext: int | str | None = None) -> AstroTable:  # noqa: PLR0911
    """Read ``path`` into an astropy ``Table`` (format from ``fmt`` or the suffix)."""
    if fmt not in TABLE_FORMATS:
        raise TableReadError(f"unknown table format {fmt!r}")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    if fmt == "fits" or (fmt == "auto" and suffix in _FITS_SUFFIXES):
        return _read_fits_table(path, ext)
    if fmt == "json" or (fmt == "auto" and suffix == ".json"):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
            return AstroTable(rows=data)
        if isinstance(data, dict) and all(isinstance(v, list) for v in data.values()):
            return AstroTable(data)
        raise TableReadError("JSON table must be a list of row objects or a dict of columns")
    if fmt == "votable" or (fmt == "auto" and suffix in (".vot", ".xml", ".votable")):
        return AstroTable.read(path, format="votable")
    if fmt == "ecsv" or (fmt == "auto" and suffix == ".ecsv"):
        return AstroTable.read(path, format="ascii.ecsv")
    if fmt == "csv" or (fmt == "auto" and suffix == ".csv"):
        return AstroTable.read(path, format="ascii.csv")
    try:
        return AstroTable.read(path, format="ascii")
    except Exception as exc:
        raise TableReadError(f"could not parse table: {exc}") from exc


def read_table(path: Path, fmt: str = "auto", ext: int | str | None = None) -> Table:
    """Read ``path`` into the ``astro.Table`` port type."""
    table = from_astropy(read_astropy_table(path, fmt, ext))
    table.meta.setdefault("source", path.name)
    return table


__all__ = ["TABLE_FORMATS", "TableFormat", "TableReadError", "from_astropy", "read_table"]
