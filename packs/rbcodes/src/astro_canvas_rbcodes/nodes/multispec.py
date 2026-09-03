"""``rbcodes.multispec.*`` nodes: ``rb_multispec`` as a canvas experience.

``view`` is the interactive node behind the **multispec-viewer** editor: it stacks a spectrum
collection, overlays line lists at a redshift and holds the absorber catalogue and the
identified-line list in its parameters, so the edited catalogues are its outputs and travel down
the graph. Around it are the file nodes (``export_linelist`` / ``import_linelist`` in
rb_multispec's fixed-width, CSV and JSON formats, ``reconcile_linelists``), the absorber catalogue
adapter and the quick Gaussian / centre-of-mass fitter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
import numpy.typing as npt
from astro_canvas_core.io.paths import describe_file, file_fingerprint, resolve_in_workspace
from astro_canvas_core.types import (
    File,
    LineList,
    Redshift,
    Spectrum1D,
    SpectrumCollection,
    Table,
)
from pydantic import BaseModel, ConfigDict

from astro_canvas.sdk import NodeContext, Param, node
from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.kernels import line_fit as F
from astro_canvas_rbcodes.kernels import multispec_io as M
from astro_canvas_rbcodes.nodes import _multispec_backend as B
from astro_canvas_rbcodes.nodes._common import C_KMS
from astro_canvas_rbcodes.types import AbsorberSystem, IdentifiedLine, MultispecView

CATEGORY = "rbcodes/Multispec"

MultispecListName = Literal[
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
]
"""``multispecviewer/line_options.conf``: the per-absorber list choices of rb_multispec."""


class MultispecDisplay(BaseModel):
    """How the stack is drawn (the editor's view settings, persisted with the node)."""

    model_config = ConfigDict(extra="forbid")

    wave_min: float | None = None
    wave_max: float | None = None
    smooth_pixels: int = 1
    show_error: bool = True
    show_labels: bool = True


ZParam = Annotated[
    float,
    Param(widget="redshift", min=-0.1, max=20.0, step=1e-4, label="Redshift"),
]
ListNameParam = Annotated[
    MultispecListName,
    Param(label="Overlay line list", help="Which atomic list is drawn at the current redshift."),
]
CatalogParam = Annotated[
    list[AbsorberSystem],
    Param(
        widget="json",
        label="Absorber catalogue",
        help="Edited in the viewer; overrides the absorbers input when it has rows.",
    ),
]
IdentificationsParam = Annotated[
    list[IdentifiedLine],
    Param(
        widget="json",
        label="Identified lines",
        help="Edited in the viewer; overrides the identified lines input when it has rows.",
    ),
]
DisplayParam = Annotated[MultispecDisplay, Param(widget="json", label="Display")]
DEFAULT_DISPLAY = MultispecDisplay()
"""Module-level default so the node signature has no call in it (the node never mutates it)."""
FitKindParam = Annotated[
    F.FitKind,
    Param(label="Method", help="gaussian: least-squares Gaussian; com: flux-weighted centroid."),
]
VelocityLimitParam = Annotated[float, Param(unit="km/s", min=-100000.0, max=100000.0)]


# --- table conversion ----------------------------------------------------------------------------


def _column(table: Table, *names: str) -> npt.NDArray[Any] | None:
    """The first column present under any of ``names`` (case-insensitive)."""
    lookup = {key.lower(): key for key in table.columns}
    for name in names:
        key = lookup.get(name.lower())
        if key is not None:
            return table.columns[key]
    return None


def absorbers_from_table(table: Table | None) -> list[AbsorberSystem]:
    """Absorber systems from any catalogue shape (``Zabs``/``zabs``, ``LineList``/``name``).

    Accepts rb_multispec's own ``Zabs``/``LineList``/``Color``/``Visible`` columns and the
    ``zabs``/``name``/``label`` catalogue ``rbcodes.zfind.absorbers_to_catalog`` produces.
    """
    if table is None or table.n_rows == 0:
        return []
    zabs = _column(table, "zabs")
    if zabs is None:
        raise ValueError("an absorber catalogue needs a 'Zabs' column")
    lists = _column(table, "linelist", "list", "name")
    colors = _column(table, "color")
    visible = _column(table, "visible")
    labels = _column(table, "label")
    rows: list[AbsorberSystem] = []
    for i in range(len(zabs)):
        rows.append(
            AbsorberSystem(
                zabs=float(zabs[i]),
                linelist=_list_name(lists[i]) if lists is not None else "LLS",
                color=str(colors[i]) if colors is not None else _color_at(i),
                visible=bool(visible[i]) if visible is not None else True,
                label=str(labels[i]) if labels is not None else "",
            )
        )
    return rows


def _list_name(value: Any) -> str:
    """A catalogue's list column as one of rb_multispec's options (``LLS`` when unknown)."""
    text = str(value)
    return text if text in M.LINE_LIST_OPTIONS else "LLS"


def _color_at(index: int) -> str:
    return M.ABSORBER_COLORS[index % len(M.ABSORBER_COLORS)]


def identified_from_table(table: Table | None) -> list[IdentifiedLine]:
    """Identified lines from a table with ``Name``/``Wave_obs``/``Zabs`` columns."""
    if table is None or table.n_rows == 0:
        return []
    name = _column(table, "name", "transition")
    wave = _column(table, "wave_obs", "wave", "wrest_obs")
    zabs = _column(table, "zabs", "z")
    if name is None or wave is None or zabs is None:
        raise ValueError("an identified-line table needs 'Name', 'Wave_obs' and 'Zabs' columns")
    rest = _column(table, "wave_rest", "wrest")
    spectrum = _column(table, "spectrum", "file")
    rows: list[IdentifiedLine] = []
    for i in range(len(name)):
        rows.append(
            IdentifiedLine(
                name=str(name[i]),
                wave_obs=float(wave[i]),
                zabs=float(zabs[i]),
                wave_rest=float(rest[i]) if rest is not None else None,
                spectrum=str(spectrum[i]) if spectrum is not None else "",
            )
        )
    return rows


def absorbers_table(rows: list[AbsorberSystem], **meta: Any) -> Table:
    """rb_multispec's absorber catalogue as a ``Table`` (``Zabs``/``LineList``/``Color``...)."""
    return Table(
        columns={
            "Zabs": np.array([r.zabs for r in rows], dtype=np.float64),
            "LineList": np.array([r.linelist for r in rows], dtype=np.str_),
            "Color": np.array([r.color for r in rows], dtype=np.str_),
            "Visible": np.array([r.visible for r in rows], dtype=np.bool_),
            "Label": np.array([r.label for r in rows], dtype=np.str_),
        },
        meta={"rbcodes": _rb.provenance(), "format": "multispec.absorbers", **meta},
    )


def identified_table(rows: list[IdentifiedLine], **meta: Any) -> Table:
    """The identified-line list as a ``Table`` (``Name``/``Wave_obs``/``Zabs``/...)."""
    return Table(
        columns={
            "Name": np.array([r.name for r in rows], dtype=np.str_),
            "Wave_obs": np.array([r.wave_obs for r in rows], dtype=np.float64),
            "Zabs": np.array([r.zabs for r in rows], dtype=np.float64),
            "Wave_rest": np.array([r.rest() for r in rows], dtype=np.float64),
            "Spectrum": np.array([r.spectrum for r in rows], dtype=np.str_),
        },
        units={"Wave_obs": "Angstrom", "Wave_rest": "Angstrom"},
        meta={"rbcodes": _rb.provenance(), "format": "multispec.line_list", **meta},
    )


def line_rows(table: Table) -> list[M.LineRow]:
    """A table of identified lines as the dictionaries the multispec writers consume."""
    return [
        {
            "Name": line.name,
            "Wave_obs": float(line.wave_obs),
            "Zabs": float(line.zabs),
            "Wave_rest": round(line.rest(), 4),
            "Spectrum": line.spectrum,
        }
        for line in identified_from_table(table)
    ]


def absorber_rows(table: Table | None) -> list[M.AbsorberRow]:
    """An absorber catalogue as the dictionaries the multispec writers consume."""
    return [
        {
            "Zabs": float(a.zabs),
            "LineList": a.linelist,
            "Color": a.color,
            "Visible": bool(a.visible),
        }
        for a in absorbers_from_table(table)
    ]


# --- the viewer node -----------------------------------------------------------------------------


def _label_of(spec: Spectrum1D, index: int, labels: list[str]) -> str:
    if index < len(labels) and labels[index]:
        return labels[index]
    source = spec.meta.get("source")
    return str(source) if source else f"Spectrum {index + 1}"


def _displayed(spec: Spectrum1D, display: MultispecDisplay) -> Spectrum1D:
    """The panel as drawn: cropped to the wavelength window, boxcar-smoothed."""
    wave = np.asarray(spec.wave, dtype=np.float64)
    keep = np.ones(wave.shape, dtype=bool)
    if display.wave_min is not None:
        keep &= wave >= display.wave_min
    if display.wave_max is not None:
        keep &= wave <= display.wave_max
    if not np.any(keep):
        raise ValueError(
            f"the display window [{display.wave_min}, {display.wave_max}] excludes every pixel"
        )
    update: dict[str, Any] = {"wave": wave[keep], "flux": np.asarray(spec.flux)[keep]}
    for name in ("error", "continuum"):
        values = getattr(spec, name)
        if values is not None:
            update[name] = np.asarray(values)[keep]
    width = max(1, int(display.smooth_pixels))
    if width > 1:
        from astropy.convolution import Box1DKernel, convolve  # noqa: PLC0415 - lazy astropy

        kernel = Box1DKernel(width)
        for name in ("flux", "error", "continuum"):
            if name in update:
                update[name] = np.asarray(convolve(update[name], kernel), dtype=np.float64)
    return spec.model_copy(update=update)


@node(
    id="rbcodes.multispec.view",
    name="Multi-Spectrum Viewer",
    category=CATEGORY,
    icon="layers",
    editor="multispec-viewer",
    outputs=("absorbers", "identified_lines", "view"),
)
def view(
    spectra: SpectrumCollection,
    absorber_seed: Table | None = None,
    line_seed: Table | None = None,
    extra_lines: LineList | None = None,
    extra_lines_2: LineList | None = None,
    redshift: Redshift | None = None,
    z: ZParam = 0.0,
    linelist: ListNameParam = "LLS",
    catalog: CatalogParam = [],  # noqa: B006 - pydantic copies the default
    identifications: IdentificationsParam = [],  # noqa: B006 - pydantic copies the default
    display: DisplayParam = DEFAULT_DISPLAY,
) -> tuple[Table, Table, MultispecView]:
    """Stack spectra, overlay line lists at a redshift and keep the catalogues you build.

    This is ``rb_multispec`` as one node: open the **multispec-viewer** editor to pan the stack,
    toggle line lists, add absorber systems at a redshift, click features to identify them and
    run quick Gaussian / centre-of-mass fits. Apply writes the catalogues back into the node's
    ``catalog`` and ``identifications`` parameters, and they leave as the two table outputs
    (feed them to ``Export Line List`` or any table node).

    The seeds are what the editor starts from when a catalogue parameter is still empty, so a
    catalogue from ``rbcodes.zfind.absorbers_to_catalog`` or ``Import Line List`` flows straight
    in. A connected ``redshift`` overrides the ``z`` parameter, exactly as in ``Set Redshift``.

    Args:
        spectra: The spectra to stack, one panel each (``Collect Spectra``).
        absorber_seed: Absorber catalogue to start from (``Zabs``/``LineList``/``Color`` or the
            ``zabs``/``name``/``label`` shape of the zfind adapter).
        line_seed: Identified lines to start from (``Name``/``Wave_obs``/``Zabs``).
        extra_lines: An extra line list to offer in the overlay menu.
        extra_lines_2: A second extra line list.
        redshift: Redshift from another node; overrides ``z`` when connected.
        z: Redshift the overlaid lines are drawn at.
        linelist: Which of rb_multispec's atomic lists is overlaid.
        catalog: The absorber systems held by this node (edited in the viewer).
        identifications: The identified lines held by this node (edited in the viewer).
        display: Wavelength window, smoothing and what the panels show.

    Returns:
        The absorber catalogue, the identified-line list and the view itself (the panels as
        drawn, for the inline preview and dashboards).
    """
    if len(spectra) == 0:
        raise ValueError("connect at least one spectrum (Collect Spectra)")
    current_z = float(redshift.z) if redshift is not None else float(z)
    systems = list(catalog) if catalog else absorbers_from_table(absorber_seed)
    lines = list(identifications) if identifications else identified_from_table(line_seed)
    labels = [_label_of(spec, i, list(spectra.labels)) for i, spec in enumerate(spectra.items)]
    panels = [_displayed(spec, display) for spec in spectra.items]
    extra = [ll.source or "custom" for ll in (extra_lines, extra_lines_2) if ll is not None]
    view_port = MultispecView(
        spectra=panels,
        labels=labels,
        absorbers=systems,
        identified=lines,
        z=current_z,
        linelist=linelist,
        meta={
            "rbcodes": _rb.provenance(),
            "display": display.model_dump(),
            "extra_linelists": extra,
            "source": "rbcodes.multispec.view",
        },
    )
    source = {"source": "rbcodes.multispec.view", "z": current_z}
    return (
        absorbers_table(systems, **source),
        identified_table(lines, **source),
        view_port,
    )


@node(
    id="rbcodes.multispec.absorber_catalog",
    name="Absorber Catalog",
    category=CATEGORY,
    icon="table-2",
)
def absorber_catalog(
    absorbers: Table,
    linelist: ListNameParam = "LLS",
    visible: Annotated[bool, Param(label="Visible by default")] = True,
) -> Table:
    """Normalise any absorber catalogue into rb_multispec's absorber-manager table.

    Accepts the ``zabs``/``name``/``label`` shape of ``rbcodes.zfind.absorbers_to_catalog`` as
    well as tables already in rb_multispec's form, and fills the missing ``Color`` (cycling
    through ``rb_utility.rb_set_color``) and ``Visible`` columns.

    Args:
        absorbers: Catalogue to normalise.
        linelist: Line list assigned to systems whose own list is unknown.
        visible: Whether the systems start plotted.

    Returns:
        ``Zabs``/``LineList``/``Color``/``Visible``/``Label``, one row per system.
    """
    rows = absorbers_from_table(absorbers)
    for i, row in enumerate(rows):
        if row.linelist == "LLS" and linelist != "LLS":
            row.linelist = linelist
        row.color = row.color or _color_at(i)
        row.visible = visible
    return absorbers_table(rows, source="rbcodes.multispec.absorber_catalog")


# --- file formats --------------------------------------------------------------------------------


def _workspace(ctx: NodeContext | None) -> Path:
    return Path(ctx.workspace) if ctx is not None else Path.cwd()


@node(
    id="rbcodes.multispec.export_linelist",
    name="Export Line List",
    category=CATEGORY,
    icon="file-down",
)
def export_linelist(
    identified_lines: Table,
    absorbers: Table | None = None,
    path: Annotated[str, Param(label="Output path")] = "outputs/line_list.json",
    format: Annotated[  # noqa: A002 - the parameter is named after the file format
        M.LineFormat, Param(label="Format")
    ] = "json",
    comment: Annotated[str, Param(label="Comment", help="Stored as metadata.user_comment")] = "",
    ctx: NodeContext | None = None,
) -> File:
    """Write the identified lines in one of rb_multispec's three formats.

    ``txt`` is the fixed-width ``Name``/``Wave_obs``/``Zabs`` table, ``csv`` the same columns as
    comma-separated values, and ``json`` the combined document (line list, absorbers, spectrum
    files and ``metadata.application_name = "MultispecViewer"``) that rb_multispec's *Load* reads
    back. Files written here open in ``multispecviewer.io_manager`` unchanged.

    Args:
        identified_lines: The line list (``Multi-Spectrum Viewer`` -> ``identified_lines``).
        absorbers: Absorber systems to store alongside them (JSON only).
        path: Workspace-relative output path.
        format: ``txt``, ``csv`` or ``json``.
        comment: Free-text note stored in the JSON metadata.

    Returns:
        The written file.
    """
    root = _workspace(ctx)
    target = resolve_in_workspace(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = line_rows(identified_lines)
    files = sorted({str(r["Spectrum"]) for r in rows if r.get("Spectrum")})
    text = M.format_line_list(
        rows,
        format,
        absorbers=absorber_rows(absorbers),
        spectrum_files=files,
        user_comment=comment,
        metadata={"astro_canvas": _rb.provenance()},
    )
    target.write_text(text, encoding="utf-8")
    return describe_file(root, target)


@node(
    id="rbcodes.multispec.import_linelist",
    name="Import Line List",
    category=CATEGORY,
    icon="file-up",
    fingerprint=file_fingerprint,
    outputs=("identified_lines", "absorbers"),
)
def import_linelist(
    path: Annotated[str, Param(widget="file", label="File")] = "",
    ctx: NodeContext | None = None,
) -> tuple[Table, Table]:
    """Read an rb_multispec line list (``.txt``, ``.csv`` or ``.json``) back into tables.

    The combined JSON document also carries the absorber systems; the text and CSV formats do
    not, so the second output is empty for them.

    Args:
        path: Workspace-relative path of a file rb_multispec (or ``Export Line List``) wrote.

    Returns:
        The identified lines and the absorber systems stored in the file.
    """
    if not path:
        raise ValueError("choose a file to load")
    target = resolve_in_workspace(_workspace(ctx), path)
    rows, absorbers = M.load_any(target)
    lines = [
        IdentifiedLine(
            name=str(row.get("Name", "")),
            wave_obs=float(row["Wave_obs"]),
            zabs=float(row["Zabs"]),
            wave_rest=float(row["Wave_rest"]) if row.get("Wave_rest") is not None else None,
            spectrum=str(row.get("Spectrum", "")),
        )
        for row in rows
        if "Wave_obs" in row and "Zabs" in row
    ]
    systems = [
        AbsorberSystem(
            zabs=float(row["Zabs"]),
            linelist=_list_name(row.get("LineList", "LLS")),
            color=str(row.get("Color", "sky_blue")),
            visible=bool(row.get("Visible", True)),
        )
        for row in absorbers
        if "Zabs" in row
    ]
    source = {"source": "rbcodes.multispec.import_linelist", "file": target.name}
    return identified_table(lines, **source), absorbers_table(systems, **source)


def paths_fingerprint(
    paths: list[str] | None = None, *, workspace: Path | None = None, **_: object
) -> str:
    """``mtime_ns:size`` of every path parameter, so editing a merged file re-runs the node."""
    return "|".join(file_fingerprint(p, workspace=workspace) for p in (paths or []))


@node(
    id="rbcodes.multispec.reconcile_linelists",
    name="Reconcile Line Lists",
    category=CATEGORY,
    icon="merge",
    fingerprint=paths_fingerprint,
    outputs=("identified_lines", "absorbers"),
)
def reconcile_linelists(
    file: File | None = None,
    file_2: File | None = None,
    paths: Annotated[
        list[str],
        Param(label="Files", help="Workspace-relative line-list files, added to the inputs."),
    ] = [],  # noqa: B006 - pydantic copies the default
    velocity_threshold: Annotated[
        float,
        Param(unit="km/s", min=0.0, max=5000.0, label="Velocity threshold"),
    ] = 20.0,
    ctx: NodeContext | None = None,
) -> tuple[Table, Table]:
    """Merge several identified-line files, collapsing duplicates within a velocity separation.

    ``multispecviewer.utils.reconcile_linelists``: entries of the same transition whose rest
    wavelengths lie within ``velocity_threshold`` of each other become one line at the mean rest
    wavelength and mean redshift; the unique redshifts that remain become absorber systems with
    cycling colours.

    Args:
        file: A line-list file (typically ``Export Line List``'s output).
        file_2: A second line-list file.
        paths: Further workspace-relative files to merge.
        velocity_threshold: Maximum velocity separation (km/s) of lines treated as duplicates.

    Returns:
        The reconciled line list (with a ``MergedCount`` column where entries were merged) and
        the absorber systems derived from it.
    """
    root = _workspace(ctx)
    targets = [resolve_in_workspace(root, f.path) for f in (file, file_2) if f is not None]
    targets += [resolve_in_workspace(root, p) for p in paths if p]
    if not targets:
        raise ValueError("connect a line-list file or add a path")
    rows, absorbers, info = B.reconcile(targets, velocity_threshold)
    lines = [
        IdentifiedLine(
            name=str(row.get("Name", "")),
            wave_obs=float(row["Wave_obs"]),
            zabs=float(row["Zabs"]),
        )
        for row in rows
    ]
    merged = np.array([int(row.get("MergedCount", 1)) for row in rows], dtype=np.int64)
    systems = [
        AbsorberSystem(
            zabs=float(row["Zabs"]),
            linelist=_list_name(row.get("LineList", "LLS")),
            color=str(row.get("Color", "sky_blue")),
            visible=bool(row.get("Visible", False)),
        )
        for row in absorbers
    ]
    source = {"source": "rbcodes.multispec.reconcile_linelists", "reconciliation": info}
    table = identified_table(lines, **source)
    table.columns["MergedCount"] = merged
    return table, absorbers_table(systems, **source)


# --- quick fits and velocity stacks -------------------------------------------------------------


@node(id="rbcodes.multispec.quick_fit", name="Quick Line Fit", category=CATEGORY, icon="activity")
def quick_fit(
    spec: Spectrum1D,
    x1: Annotated[float, Param(widget="wavelength", label="Left anchor")] = 0.0,
    y1: Annotated[float, Param(label="Left flux")] = 0.0,
    x2: Annotated[float, Param(widget="wavelength", label="Right anchor")] = 0.0,
    y2: Annotated[float, Param(label="Right flux")] = 0.0,
    kind: FitKindParam = "gaussian",
) -> Table:
    """Fit one feature between two anchor points (``multispecviewer.LineFitter``).

    The anchors set both the fit window and a straight continuum through ``(x1, y1)`` and
    ``(x2, y2)``, so a tilted continuum and a half-profile both work; emission or absorption is
    decided by the sign of the integrated residual. This is the node behind the viewer's
    ``g``/``c`` quick fits.

    Args:
        spec: The spectrum to fit (observed frame).
        x1: Wavelength of the left anchor (Angstrom).
        y1: Flux at the left anchor - the left end of the continuum.
        x2: Wavelength of the right anchor.
        y2: Flux at the right anchor.
        kind: ``gaussian`` least-squares fit or ``com`` centre-of-mass centroid.

    Returns:
        One row: centroid, FWHM (A and km/s), amplitude, direction and the pixel count.
    """
    if x1 == x2:
        raise ValueError("the two anchors must have different wavelengths")
    if spec.frame == "velocity":
        raise ValueError("the quick fit needs a wavelength spectrum, not a velocity slice")
    fit = B.fit_line(np.asarray(spec.wave), np.asarray(spec.flux), x1, y1, x2, y2, kind)
    return Table(
        columns={
            "kind": np.array([fit.kind], dtype=np.str_),
            "centroid": np.array([fit.centroid], dtype=np.float64),
            "fwhm_ang": np.array([fit.fwhm_ang], dtype=np.float64),
            "fwhm_kms": np.array([fit.fwhm_kms], dtype=np.float64),
            "sigma_ang": np.array([fit.sigma_ang], dtype=np.float64),
            "amplitude": np.array([fit.amplitude], dtype=np.float64),
            "direction": np.array([fit.direction], dtype=np.int64),
            "asymmetric": np.array([fit.asymmetric], dtype=np.bool_),
            "n_pixels": np.array([fit.n_pixels], dtype=np.int64),
        },
        units={"centroid": "Angstrom", "fwhm_ang": "Angstrom", "fwhm_kms": "km / s"},
        meta={
            "rbcodes": _rb.provenance(),
            "source": "rbcodes.multispec.quick_fit",
            "window": list(fit.window),
            "continuum": list(fit.continuum),
        },
    )


@node(id="rbcodes.multispec.vstack", name="Velocity Stack", category=CATEGORY, icon="rows-3")
def vstack(
    spec: Spectrum1D,
    linelist: LineList,
    redshift: Redshift | None = None,
    z: ZParam = 0.0,
    vmin: VelocityLimitParam = -1000.0,
    vmax: VelocityLimitParam = 1000.0,
    max_panels: Annotated[int, Param(min=1, max=64, label="Maximum panels")] = 24,
) -> SpectrumCollection:
    """One velocity panel per transition of the list that falls inside the spectrum (``vStack``).

    The velocity-stack view of rb_multispec without its Qt dialog: every line of the list whose
    observed wavelength at ``z`` lies inside the spectrum becomes a panel on a common velocity
    axis (rbcodes' ``c = 2.9979e5`` km/s), ordered by rest wavelength and labelled with the
    transition.

    Args:
        spec: The spectrum to slice.
        linelist: Transitions to stack (``Line List`` or ``Curated Line List``).
        redshift: Redshift from another node; overrides ``z`` when connected.
        z: Absorber redshift.
        vmin: Lower velocity limit of each panel (km/s).
        vmax: Upper velocity limit.
        max_panels: Stop after this many transitions.

    Returns:
        A collection of velocity-frame spectra, one per transition.
    """
    if vmin >= vmax:
        raise ValueError("vmin must be smaller than vmax")
    if spec.frame == "velocity":
        raise ValueError("the velocity stack needs a wavelength spectrum, not a velocity slice")
    zabs = float(redshift.z) if redshift is not None else float(z)
    wave = np.asarray(spec.wave, dtype=np.float64)
    if spec.frame == "rest":
        wave = wave * (1.0 + (spec.z or 0.0))
    flux = np.asarray(spec.flux, dtype=np.float64)
    error = np.asarray(spec.error, dtype=np.float64) if spec.error is not None else None
    lo, hi = float(np.min(wave)), float(np.max(wave))
    order = np.argsort(np.asarray(linelist.wrest, dtype=np.float64))
    items: list[Spectrum1D] = []
    labels: list[str] = []
    for index in order:
        wrest = float(linelist.wrest[index])
        center = wrest * (1.0 + zabs)
        if not lo < center < hi:
            continue
        velocity = (wave - center) / center * C_KMS
        keep = (velocity >= vmin) & (velocity <= vmax)
        if np.count_nonzero(keep) < 2:
            continue
        name = str(linelist.name[index])
        items.append(
            Spectrum1D(
                wave=velocity[keep],
                flux=flux[keep],
                error=error[keep] if error is not None else None,
                wave_unit="km / s",
                flux_unit=spec.flux_unit,
                frame="velocity",
                z=zabs,
                v0_wrest=wrest,
                meta={
                    "rbcodes": _rb.provenance(),
                    "source": "rbcodes.multispec.vstack",
                    "transition": name,
                    "transition_wrest": wrest,
                },
            )
        )
        labels.append(f"{name} {wrest:.1f}")
        if len(items) >= max_panels:
            break
    if not items:
        raise ValueError(
            f"no transition of {linelist.source or 'the list'} falls inside the spectrum at "
            f"z = {zabs:.5f}"
        )
    return SpectrumCollection(items=items, labels=labels)


__all__ = [
    "MultispecDisplay",
    "MultispecListName",
    "absorber_catalog",
    "absorbers_from_table",
    "absorbers_table",
    "export_linelist",
    "identified_from_table",
    "identified_table",
    "import_linelist",
    "quick_fit",
    "reconcile_linelists",
    "view",
    "vstack",
]
