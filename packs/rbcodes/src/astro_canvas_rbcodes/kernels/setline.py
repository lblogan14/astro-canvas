"""Port of ``rbcodes.IGM.rb_setline`` (atomic line lists shipped in ``lines/``)."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

LineListName = Literal[
    "atom",
    "LLS",
    "LLS Small",
    "DLA",
    "LBG",
    "Gal",
    "Eiger_Strong",
    "Gal_Em",
    "Gal_Abs",
    "Gal_long",
    "AGN",
    "HI_recomb",
    "HI_recomb_light",
    "HI",
    "EUV",
    "LLS_EUV",
]

FILES: dict[str, str] = {
    "atom": "atom_full.dat",
    "LLS": "lls.lst",
    "LLS Small": "lls_sub.lst",
    "DLA": "dla.lst",
    "LBG": "lbg.lst",
    "Gal": "gal_vac.lst",
    "Eiger_Strong": "Eiger_Strong.lst",
    "Gal_Em": "Galaxy_emission_Lines.lst",
    "Gal_Abs": "Galaxy_absorption_Lines.lst",
    "Gal_long": "Galaxy_Long_E_n_A.lst",
    "AGN": "AGN.lst",
    "HI_recomb": "HI_recombination.lst",
    "HI_recomb_light": "HI_recombination_light.lst",
    "HI": "hi.lst",
    "EUV": "euv.lst",
    "LLS_EUV": "lls_euv.lst",
}
LINE_LISTS: tuple[str, ...] = tuple(FILES)

_CACHE: dict[str, list[dict[str, Any]]] = {}


def line_list_path(label: str) -> Path:
    if label not in FILES:
        valid = ", ".join(sorted(FILES))
        raise ValueError(f"Invalid line list label: {label!r}. Valid options are: {valid}")
    return Path(str(files("astro_canvas_rbcodes.kernels").joinpath(f"lines/{FILES[label]}")))


def _read_csv_table(path: Path) -> dict[str, list[str]]:
    """Minimal reader for the header tables rbcodes parses with ``astropy.io.ascii``."""
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    header = lines[0]
    delimiter = "," if "," in header else None
    names = [h.strip() for h in header.split(delimiter)]
    columns: dict[str, list[str]] = {name: [] for name in names}
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(delimiter)]
        if len(parts) < len(names):
            continue
        for name, value in zip(names, parts, strict=False):
            columns[name].append(value)
    return columns


def _read_whitespace_rows(path: Path, *, skip_header: bool, min_cols: int) -> list[list[str]]:
    rows: list[list[str]] = []
    with path.open(encoding="utf-8") as handle:
        if skip_header:
            handle.readline()
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            columns = line.split()
            if len(columns) < min_cols:
                continue
            rows.append(columns)
    return rows


def read_line_list(label: str) -> list[dict[str, Any]]:
    """Rows ``{wrest, ion, fval[, gamma]}`` of a line list (cached), like rbcodes' reader."""
    if label in _CACHE:
        return _CACHE[label]
    path = line_list_path(label)
    if not path.is_file():
        raise FileNotFoundError(f"Line list file not found: {path}")
    data: list[dict[str, Any]] = []
    if label == "atom":
        for cols in _read_whitespace_rows(path, skip_header=False, min_cols=4):
            wrest = float(cols[1])
            data.append(
                {
                    "wrest": wrest,
                    "ion": f"{cols[0]} {int(wrest)}",
                    "fval": float(cols[2]),
                    "gamma": float(cols[3]),
                }
            )
    elif label in ("LBG", "Gal"):
        table = _read_csv_table(path)
        for w_text, ident, name, transition in zip(
            table["wrest"], table["ID"], table["name"], table["transition"], strict=True
        ):
            data.append(
                {
                    "wrest": float(w_text),
                    "ion": f"{name} {transition}",
                    "fval": float(ident),
                    "gamma": float(ident),
                }
            )
    elif label in ("Eiger_Strong", "Gal_Em", "Gal_Abs", "Gal_long", "AGN"):
        table = _read_csv_table(path)
        for w_text, name in zip(table["wrest"], table["name"], strict=True):
            data.append({"wrest": float(w_text), "ion": name, "fval": 0.0, "gamma": 0.0})
    elif label in ("HI_recomb", "HI_recomb_light"):
        table = _read_csv_table(path)
        for w_text, name in zip(table["wrest"], table["name"], strict=True):
            data.append({"wrest": float(w_text) * 1e4, "ion": name, "fval": 0.0, "gamma": 0.0})
    elif label in ("HI", "EUV", "LLS_EUV"):
        for cols in _read_whitespace_rows(path, skip_header=True, min_cols=4):
            data.append(
                {
                    "wrest": float(cols[0]),
                    "ion": f"{cols[1]} {cols[2]}",
                    "fval": float(cols[3]),
                    "gamma": float(cols[4]) if len(cols) > 4 else 0.0,
                }
            )
    else:
        for cols in _read_whitespace_rows(path, skip_header=True, min_cols=4):
            data.append(
                {"wrest": float(cols[0]), "ion": f"{cols[1]} {cols[2]}", "fval": float(cols[3])}
            )
    _CACHE[label] = data
    return data


def line_list_arrays(
    label: str,
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.str_],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64] | None,
]:
    """``(wrest, name, fval, gamma | None)`` arrays of a line list (gamma only for ``atom``)."""
    rows = read_line_list(label)
    wrest = np.array([float(r["wrest"]) for r in rows], dtype=np.float64)
    name = np.array([str(r["ion"]) for r in rows], dtype=np.str_)
    fval = np.array([float(r["fval"]) for r in rows], dtype=np.float64)
    gamma = (
        np.array([float(r["gamma"]) for r in rows], dtype=np.float64) if label == "atom" else None
    )
    return wrest, name, fval, gamma


def rb_setline(
    lambda_rest: float,
    method: str,
    linelist: str = "atom",
    target_name: str | None = None,
) -> dict[str, Any]:
    """Match a transition by closest wavelength, exact wavelength (1e-3 A) or name.

    Returns ``{'wave', 'fval', 'name'[, 'gamma']}`` with scalars for ``closest`` and arrays for the
    other methods, exactly like rbcodes (empty arrays when nothing matches).
    """
    if method not in ("Exact", "closest", "Name"):
        raise ValueError(f"Method must be one of 'Exact', 'closest', or 'Name', got '{method}'")
    if method == "Name" and target_name is None:
        raise ValueError("target_name must be provided when method='Name'")
    wavelist, name, fval, gamma = line_list_arrays(linelist)
    empty = {"wave": np.array([]), "fval": np.array([]), "name": np.array([])}
    if wavelist.size == 0:
        return empty

    def pack(index: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"wave": wavelist[index], "fval": fval[index], "name": name[index]}
        if gamma is not None:
            out["gamma"] = gamma[index]
        return out

    if method == "Exact":
        q = np.where(np.abs(lambda_rest - wavelist) < 1e-3)
        return pack(q) if len(q[0]) else empty
    if method == "Name":
        q = np.where(name == target_name)
        return pack(q) if len(q[0]) else empty
    idx = int(np.abs(lambda_rest - wavelist).argmin())
    out = pack(idx)
    out["name"] = str(out["name"])
    return out


__all__ = [
    "FILES",
    "LINE_LISTS",
    "LineListName",
    "line_list_arrays",
    "line_list_path",
    "rb_setline",
    "read_line_list",
]
