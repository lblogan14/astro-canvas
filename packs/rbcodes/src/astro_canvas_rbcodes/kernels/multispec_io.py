"""Port of ``rbcodes.GUIs.multispecviewer.io_manager`` (and ``utils.reconcile_linelists``).

The upstream ``IOManager`` is a Qt-aware singleton built on pandas; this module is the same file
formats as plain functions over lists of dictionaries, so the pack keeps its small dependency
set and the nodes stay pure. Written files are byte-for-byte what ``IOManager`` writes, and
``tests/packs/rbcodes/test_multispec_io.py`` reads them back with the upstream reader where
rbcodes is installed.

Three line-list formats (R1 section 4.6):

* ``txt`` - fixed width ``Name`` (30) ``Wave_obs`` (15) ``Zabs`` (10) with a two-line header,
* ``csv`` - ``Name,Wave_obs,Zabs`` (plus any extra columns) as pandas writes it,
* ``json`` - the combined document ``{line_list, absorbers, spectrum_files, metadata}`` whose
  ``metadata.application_name`` is ``MultispecViewer``.
"""

from __future__ import annotations

import csv
import datetime
import getpass
import io
import json
import math
import platform
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

LineRow = dict[str, Any]
"""One identified line: ``Name``, ``Wave_obs``, ``Zabs`` (plus whatever else was stored)."""

AbsorberRow = dict[str, Any]
"""One absorber system: ``Zabs``, ``LineList``, ``Color``, ``Visible``."""

LineFormat = Literal["txt", "csv", "json"]

APPLICATION_NAME = "MultispecViewer"
"""``metadata.application_name`` of the combined JSON document."""

FORMAT_VERSION = "1.5.0"
"""``rb_multispec.__version__`` at the vendored commit; written as ``metadata.version``."""

LINE_COLUMNS = ("Name", "Wave_obs", "Zabs")
ABSORBER_COLUMNS = ("Zabs", "LineList", "Color", "Visible")

C_KMS = 299792.458
"""``scipy.constants.c / 1000``, the speed of light ``reconcile_linelists`` uses."""

ABSORBER_COLORS: tuple[str, ...] = (
    "sky_blue",
    "orange",
    "light_lime_green",
    "vermillion",
    "reddish_purple",
    "cyan",
    "gold",
    "coral",
    "lavender",
    "mint",
    "slate_gray",
    "rose",
    "blue2",
    "bluish_green",
    "yellow",
    "dark_orange",
    "purple_wordle",
    "light_purple",
    "orange2",
    "light_orange",
    "teal",
    "pale_red",
    "pale_cyan",
    "pale_lime_green",
    "dark_red",
    "dark_green",
    "dark_blue",
    "gray",
    "red",
    "green",
    "blue",
)
"""``rb_utility.rb_set_color()`` in order, minus black/white/cream/light_gray (what
``reconcile_linelists`` cycles through when it names absorber colours)."""

LINE_LIST_OPTIONS: tuple[str, ...] = (
    "None",
    "LLS",
    "LLS Small",
    "DLA",
    "LBG",
    "Gal",
    "Eiger_Strong",
    "AGN",
    "Gal_Abs",
    "Gal_Em",
    "Gal_long",
    "HI_recomb_light",
    "HI_recomb",
    "HI",
    "EUV",
    "LLS_EUV",
    "atom",
)
"""``multispecviewer/line_options.conf``: what the absorber manager offers per system."""


# --- writing -----------------------------------------------------------------------------------


def format_line_list_txt(rows: Sequence[Mapping[str, Any]]) -> str:
    """The fixed-width text format of ``IOManager.save_line_list(format='txt')``."""
    out = io.StringIO()
    out.write(f"{'Name':<30} {'Wave_obs':<15} {'Zabs':<10}\n")
    out.write("-" * 55 + "\n")
    for row in rows:
        name = str(row.get("Name", ""))
        wave = f"{float(row.get('Wave_obs', 0.0)):.4f}"
        zabs = f"{float(row.get('Zabs', 0.0)):.6f}"
        out.write(f"{name:<30} {wave:<15} {zabs:<10}\n")
    return out.getvalue()


def format_line_list_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    """``DataFrame.to_csv(index=False)`` for the line list (``\\n`` line endings, no quoting)."""
    return _to_csv(rows, LINE_COLUMNS)


def format_absorbers_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    """``IOManager.save_absorbers(format='csv')``: ``Zabs,LineList,Color`` when all are present."""
    required = ("Zabs", "LineList", "Color")
    if rows and all(all(col in row for col in required) for row in rows):
        return _to_csv([{col: row[col] for col in required} for row in rows], required)
    return _to_csv(rows, ABSORBER_COLUMNS)


def _to_csv(rows: Sequence[Mapping[str, Any]], preferred: Sequence[str]) -> str:
    columns = [c for c in preferred if any(c in row for row in rows)]
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns:
        columns = list(preferred)
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n", restval="")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: _csv_value(row.get(c)) for c in columns})
    return out.getvalue()


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def combined_document(
    lines: Sequence[Mapping[str, Any]],
    absorbers: Sequence[Mapping[str, Any]] = (),
    spectrum_files: Sequence[str] = (),
    *,
    user_comment: str = "",
    metadata: Mapping[str, Any] | None = None,
    creation_date: str | None = None,
    version: str = FORMAT_VERSION,
    system_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``IOManager.save_combined_data``'s document (line list, absorbers, files, metadata)."""
    document: dict[str, Any] = {
        "line_list": [dict(row) for row in lines],
        "absorbers": [dict(row) for row in absorbers],
        "spectrum_files": list(spectrum_files),
        "metadata": {
            "creation_date": creation_date or datetime.datetime.now().isoformat(),
            "version": version,
            "application_name": APPLICATION_NAME,
            "user_comment": user_comment,
            "system_info": dict(system_info) if system_info is not None else _system_info(),
        },
    }
    if metadata:
        document["metadata"].update(metadata)
    return document


def _system_info() -> dict[str, Any]:
    try:
        username = getpass.getuser()
    except Exception:  # noqa: BLE001 - getuser() raises when no account name is set
        username = ""
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "username": username,
    }


def format_line_list(
    rows: Sequence[Mapping[str, Any]],
    fmt: LineFormat,
    *,
    absorbers: Sequence[Mapping[str, Any]] = (),
    spectrum_files: Sequence[str] = (),
    user_comment: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Serialise an identified-line table in one of the three multispec formats."""
    if fmt == "txt":
        return format_line_list_txt(rows)
    if fmt == "csv":
        return format_line_list_csv(rows)
    if fmt == "json":
        document = combined_document(
            rows,
            absorbers,
            spectrum_files,
            user_comment=user_comment,
            metadata=metadata,
        )
        return json.dumps(document, indent=2)
    raise ValueError(f"unknown line-list format {fmt!r} (txt, csv or json)")


# --- reading -----------------------------------------------------------------------------------


def parse_line_list_txt(text: str) -> list[LineRow]:
    """``IOManager.load_line_list`` for ``.txt``: skip two header lines, last two fields win."""
    lines = text.splitlines()
    data_lines = lines[2:] if len(lines) > 2 else lines
    rows: list[LineRow] = []
    for raw in data_lines:
        if not raw.strip():
            continue
        parts = raw.strip().split()
        if len(parts) >= 3:
            try:
                wave = float(parts[-2])
                zabs = float(parts[-1])
            except ValueError:
                rows.extend(_parse_wide_columns(raw))
                continue
            rows.append({"Name": " ".join(parts[:-2]), "Wave_obs": wave, "Zabs": zabs})
    return rows


def _parse_wide_columns(raw: str) -> list[LineRow]:
    """Upstream's fallback: split on runs of two or more spaces."""
    columns = re.split(r"\s{2,}", raw.strip())
    if len(columns) < 3:
        return []
    try:
        return [
            {
                "Name": columns[0].strip(),
                "Wave_obs": float(columns[1].strip()),
                "Zabs": float(columns[2].strip()),
            }
        ]
    except ValueError:
        return []


def parse_csv(text: str) -> list[dict[str, Any]]:
    """CSV rows with numbers and booleans converted the way ``pandas.read_csv`` would."""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        row: dict[str, Any] = {}
        for key, value in raw.items():
            if key is None:
                continue
            row[key] = _coerce(value)
        rows.append(row)
    return rows


_BOOLEANS = {"True": True, "true": True, "False": False, "false": False}


def _coerce(value: str | None) -> Any:
    text = "" if value is None else value.strip()
    if text == "":
        return None
    if text in _BOOLEANS:
        return _BOOLEANS[text]
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    return value


def load_line_list(path: str | Path) -> list[LineRow]:
    """Read an identified-line table written by multispec (``.txt``, ``.csv`` or ``.json``)."""
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in (".json", ".csv", ".txt"):
        raise ValueError(f"Unsupported file extension: {suffix}")
    text = target.read_text(encoding="utf-8")
    if suffix == ".json":
        payload = json.loads(text)
        return _rows_from_json(payload, "line_list")
    if suffix == ".csv":
        rows = parse_csv(text)
        missing = [c for c in LINE_COLUMNS if rows and c not in rows[0]]
        if missing:
            raise ValueError(f"CSV file missing required columns: {', '.join(missing)}")
        return rows
    return parse_line_list_txt(text)


def load_absorbers(path: str | Path) -> list[AbsorberRow]:
    """Read an absorber catalogue (``.csv`` or ``.json``), mapping the legacy column names."""
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in (".json", ".csv"):
        raise ValueError(f"Unsupported file extension: {suffix}")
    text = target.read_text(encoding="utf-8")
    if suffix == ".json":
        payload = json.loads(text)
        return _rows_from_json(payload, "absorbers")
    rows = [_rename_legacy(row) for row in parse_csv(text)]
    missing = [c for c in ("Zabs", "LineList", "Color") if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"CSV file missing required columns: {', '.join(missing)}")
    return rows


def _rename_legacy(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if "list" in out and "LineList" not in out:
        out["LineList"] = out.pop("list")
    if "color" in out and "Color" not in out:
        out["Color"] = out.pop("color")
    return out


def _rows_from_json(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and key in payload:
        rows = payload[key]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError(f"Invalid JSON format: missing {key!r} key")
    return [dict(row) for row in rows if isinstance(row, dict)]


def load_combined_data(
    path: str | Path,
) -> tuple[list[LineRow], list[AbsorberRow], list[str], dict[str, Any]]:
    """``IOManager.load_combined_data``: lines, absorbers, spectrum files and metadata."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("not a MultispecViewer document (expected a JSON object)")
    lines = [dict(r) for r in payload.get("line_list", []) if isinstance(r, dict)]
    absorbers = [dict(r) for r in payload.get("absorbers", []) if isinstance(r, dict)]
    files = [str(f) for f in payload.get("spectrum_files", [])]
    metadata = dict(payload.get("metadata", {}))
    return lines, absorbers, files, metadata


def load_any(path: str | Path) -> tuple[list[LineRow], list[AbsorberRow]]:
    """Lines and absorbers from any of the formats (``.json`` may carry both)."""
    target = Path(path)
    if target.suffix.lower() == ".json":
        lines, absorbers, _files, _meta = load_combined_data(target)
        return lines, absorbers
    return load_line_list(target), []


# --- reconciliation ------------------------------------------------------------------------------


def _base_name(name: str) -> str:
    """Transition name without the ``[b]``/``[p]`` annotation markers."""
    return str(name).split("[")[0].strip()


def _is_line_row(row: Mapping[str, Any]) -> bool:
    if not all(col in row for col in LINE_COLUMNS):
        return False
    try:
        float(row["Wave_obs"]), float(row["Zabs"])  # noqa: B018 - validation only
    except (TypeError, ValueError):
        return False
    return True


def _read_csv(target: Path) -> list[dict[str, Any]]:
    return parse_csv(target.read_text(encoding="utf-8"))


def _read_lines(target: Path) -> list[dict[str, Any]]:
    return load_any(target)[0]


def _safe(load: Callable[[Path], list[dict[str, Any]]], target: Path) -> list[dict[str, Any]]:
    """``[]`` instead of an exception: unreadable inputs are skipped, as IOManager does."""
    try:
        return load(target)
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def reconcile_linelists(
    input_files: Iterable[str | Path],
    velocity_threshold: float = 20.0,
    *,
    create_absorbers: bool = True,
) -> tuple[list[LineRow], list[AbsorberRow], dict[str, Any]]:
    """Merge identified-line files, clustering same-transition entries by velocity separation.

    Port of ``multispecviewer.utils.reconcile_linelists``: lines are grouped by transition base
    name and, inside a group, clustered while the rest-frame velocity offset from the cluster
    anchor stays within ``velocity_threshold``; each cluster becomes one row at the mean rest
    wavelength and mean redshift. Unique redshifts then become absorber systems with cycling
    colours.

    Args:
        input_files: Line-list files (``.txt``, ``.csv`` or ``.json``) to merge.
        velocity_threshold: Maximum velocity separation (km/s) of lines considered duplicates.
        create_absorbers: Also derive the absorber catalogue from the unique redshifts.

    Returns:
        ``(reconciled_lines, absorbers, info)``; ``info`` records the counts and the files read.
    """
    master: list[LineRow] = []
    read_files: list[str] = []
    absorber_hints: list[AbsorberRow] = []
    for file_path in input_files:
        target = Path(file_path)
        if not target.exists():
            continue
        if target.suffix.lower() == ".csv":
            # Upstream also scans any input CSV for absorber systems (Zabs + LineList/list).
            absorber_hints.extend(
                _rename_legacy(row)
                for row in _safe(_read_csv, target)
                if "Zabs" in row and ("LineList" in row or "list" in row)
            )
        # A file the reader rejects is skipped, exactly as IOManager's error path does.
        rows = [row for row in _safe(_read_lines, target) if _is_line_row(row)]
        if not rows:
            continue
        master.extend(rows)
        read_files.append(target.name)

    info: dict[str, Any] = {
        "velocity_threshold": velocity_threshold,
        "input_files": read_files,
        "original_line_count": len(master),
        "reconciled_line_count": 0,
    }
    if not master:
        return [], [], info

    for row in master:
        row["Wave_rest"] = float(row["Wave_obs"]) / (1.0 + float(row["Zabs"]))
        row["BaseName"] = _base_name(row["Name"])

    reconciled: list[LineRow] = []
    for name in sorted({str(r["BaseName"]) for r in master}):
        group = sorted(
            (r for r in master if r["BaseName"] == name), key=lambda r: float(r["Wave_rest"])
        )
        for cluster in _cluster(group, velocity_threshold):
            reconciled.append(_merge_cluster(name, cluster))
    info["reconciled_line_count"] = len(reconciled)

    absorbers: list[AbsorberRow] = []
    if create_absorbers:
        absorbers = _absorbers_from(reconciled, velocity_threshold, absorber_hints)
    return reconciled, absorbers, info


def _cluster(group: Sequence[LineRow], velocity_threshold: float) -> list[list[LineRow]]:
    """Split a same-transition group into velocity clusters around each cluster's anchor."""
    clusters: list[list[LineRow]] = []
    current: list[LineRow] = []
    for row in group:
        if not current:
            current = [row]
            continue
        anchor = float(current[0]["Wave_rest"])
        v_diff = C_KMS * (float(row["Wave_rest"]) - anchor) / anchor
        if abs(v_diff) <= velocity_threshold:
            current.append(row)
        else:
            clusters.append(current)
            current = [row]
    if current:
        clusters.append(current)
    return clusters


def _merge_cluster(name: str, cluster: Sequence[LineRow]) -> LineRow:
    if len(cluster) == 1:
        row = cluster[0]
        return {
            "Name": str(row["Name"]),
            "Wave_obs": round(float(row["Wave_obs"]), 4),
            "Zabs": round(float(row["Zabs"]), 6),
        }
    mean_z = sum(float(r["Zabs"]) for r in cluster) / len(cluster)
    mean_rest = sum(float(r["Wave_rest"]) for r in cluster) / len(cluster)
    return {
        "Name": name,
        "Wave_obs": round(mean_rest * (1.0 + mean_z), 4),
        "Zabs": round(mean_z, 6),
        "MergedCount": len(cluster),
    }


def _absorbers_from(
    lines: Sequence[LineRow], velocity_threshold: float, hints: Sequence[AbsorberRow]
) -> list[AbsorberRow]:
    """Unique redshifts of the reconciled lines as absorber systems (upstream's grouping)."""
    redshifts = sorted(float(r["Zabs"]) for r in lines)
    if not redshifts:
        return []
    unique: list[float] = []
    group = [redshifts[0]]
    for z in redshifts[1:]:
        previous = group[-1]
        if abs(C_KMS * (z - previous) / (1.0 + previous)) <= velocity_threshold:
            group.append(z)
        else:
            unique.append(round(sum(group) / len(group), 6))
            group = [z]
    unique.append(round(sum(group) / len(group), 6))

    absorbers: list[AbsorberRow] = []
    for i, z in enumerate(unique):
        absorbers.append(
            {
                "Zabs": z,
                "LineList": _hinted_list(z, velocity_threshold, hints),
                "Visible": False,
                "Color": ABSORBER_COLORS[i % len(ABSORBER_COLORS)],
            }
        )
    return absorbers


def _hinted_list(z: float, velocity_threshold: float, hints: Sequence[AbsorberRow]) -> str:
    """``LLS`` unless a CSV in the inputs carried a line list for a redshift this close."""
    best: AbsorberRow | None = None
    for hint in hints:
        try:
            hint_z = float(hint["Zabs"])
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or abs(hint_z - z) < abs(float(best["Zabs"]) - z):
            best = hint
    if best is None:
        return "LLS"
    if abs(C_KMS * (float(best["Zabs"]) - z) / (1.0 + z)) <= velocity_threshold:
        return str(best.get("LineList", "LLS"))
    return "LLS"


__all__ = [
    "ABSORBER_COLORS",
    "ABSORBER_COLUMNS",
    "APPLICATION_NAME",
    "C_KMS",
    "FORMAT_VERSION",
    "LINE_COLUMNS",
    "LINE_LIST_OPTIONS",
    "AbsorberRow",
    "LineFormat",
    "LineRow",
    "combined_document",
    "format_absorbers_csv",
    "format_line_list",
    "format_line_list_csv",
    "format_line_list_txt",
    "load_absorbers",
    "load_any",
    "load_combined_data",
    "load_line_list",
    "parse_csv",
    "parse_line_list_txt",
    "reconcile_linelists",
]
