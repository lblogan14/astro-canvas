"""``core.fetch.*`` nodes: download spectra and catalogues from public archives (cached)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import numpy.typing as npt
from astropy.table import Table as AstroTable

from astro_canvas.sdk import NodeContext, Param, node
from astro_canvas_core.fetch import clients
from astro_canvas_core.fetch.clients import FetchCache
from astro_canvas_core.io.spectrum import read_spectrum
from astro_canvas_core.io.table import from_astropy
from astro_canvas_core.types import Json, Spectrum1D, Table

RaParam = Annotated[float | None, Param(unit="deg", min=0.0, max=360.0, label="RA")]
DecParam = Annotated[float | None, Param(unit="deg", min=-90.0, max=90.0, label="Dec")]


def _cache(ctx: NodeContext | None) -> FetchCache:
    root = Path(ctx.workspace) if ctx is not None else Path(tempfile.gettempdir()) / "astro-canvas"
    return FetchCache(root)


def rows_to_table(rows: list[dict[str, Any]], fields: list[str] | None = None) -> Table:
    """JSON rows (list of dicts, ``None`` allowed) into an ``astro.Table``."""
    names = list(fields) if fields else []
    for row in rows:
        for key in row:
            if key not in names:
                names.append(str(key))
    columns: dict[str, npt.NDArray[Any]] = {}
    for name in names:
        values = [row.get(name) for row in rows]
        numeric = all(v is None or isinstance(v, int | float) for v in values)
        if numeric and any(v is not None for v in values):
            columns[name] = np.asarray(
                [np.nan if v is None else float(v) for v in values], dtype=np.float64
            )
        else:
            columns[name] = np.asarray(["" if v is None else str(v) for v in values], dtype=np.str_)
    return Table(columns=columns, meta={"n_rows": len(rows)})


@node(
    id="core.fetch.sdss_spectrum",
    name="Fetch SDSS Spectrum",
    category="Data/Fetch",
    icon="cloud-download",
    cost="expensive",
)
def sdss_spectrum(
    plate: Annotated[int, Param(min=0, label="Plate")] = 0,
    mjd: Annotated[int, Param(min=0, label="MJD")] = 0,
    fiber: Annotated[int, Param(min=0, label="Fiber")] = 0,
    ra: RaParam = None,
    dec: DecParam = None,
    radius_arcmin: Annotated[float, Param(unit="arcmin", min=0.01, max=30.0)] = 0.5,
    release: Annotated[str, Param(choices=["dr17", "dr16", "dr12"], advanced=True)] = "dr17",
    ctx: NodeContext | None = None,
) -> Spectrum1D:
    """Download an SDSS/BOSS spectrum by ``plate/mjd/fiber`` or by the nearest object to ``ra/dec``.

    Files land in ``<workspace>/downloads/sdss/`` and are reused on the next run.

    Args:
        plate: Plate number (with ``mjd`` and ``fiber``); leave 0 to search by position.
        mjd: Modified Julian Date of the plate.
        fiber: Fiber id.
        ra: Right ascension for a positional search (degrees).
        dec: Declination for a positional search (degrees).
        radius_arcmin: Search radius for the positional lookup.
        release: SDSS data release to query.

    Returns:
        The spectrum (vacuum wavelengths in Angstrom, flux in 1e-17 erg/s/cm2/A).
    """
    cache = _cache(ctx)
    if not (plate and mjd and fiber):
        if ra is None or dec is None:
            raise ValueError("give plate/mjd/fiber or ra/dec")
        match = clients.sdss_nearest_specobj(cache, ra, dec, radius_arcmin, release=release)
        plate, mjd, fiber = int(match["plate"]), int(match["mjd"]), int(match["fiberid"])
        if ctx is not None:
            ctx.log("info", f"nearest SDSS spectrum: plate {plate} mjd {mjd} fiber {fiber}")
    fetched = clients.sdss_spectrum(cache, plate, mjd, fiber, release=release)
    if ctx is not None:
        ctx.log("info", "sdss spectrum " + ("from cache" if fetched.cached else "downloaded"))
    spec = read_spectrum(fetched.path, "sdss", use_rbcodes=False)
    spec.meta.update(
        {
            "plate": plate,
            "mjd": mjd,
            "fiber": fiber,
            "release": release,
            "url": fetched.url,
            "cached_file": fetched.path.name,
        }
    )
    return spec


@node(
    id="core.fetch.simbad_resolve",
    name="Resolve Name (SIMBAD)",
    category="Data/Fetch",
    icon="search",
    cost="expensive",
)
def simbad_resolve(
    name: Annotated[str, Param(label="Object name")] = "", ctx: NodeContext | None = None
) -> Json:
    """Resolve an object name to coordinates with SIMBAD.

    Args:
        name: Any identifier SIMBAD knows (``M31``, ``3C 273``, ``NGC 4151``).

    Returns:
        ``{main_id, ra, dec, otype}`` with coordinates in degrees (ICRS).
    """
    return Json(value=clients.simbad_resolve(_cache(ctx), name))


@node(
    id="core.fetch.vizier_query",
    name="VizieR Cone Search",
    category="Data/Fetch",
    icon="database",
    cost="expensive",
)
def vizier_query(
    catalog: Annotated[
        str, Param(label="Catalogue", help="VizieR table id, e.g. I/355/gaiadr3")
    ] = "",
    ra: RaParam = None,
    dec: DecParam = None,
    radius_arcmin: Annotated[float, Param(unit="arcmin", min=0.01, max=60.0)] = 2.0,
    max_rows: Annotated[int, Param(min=1, max=100000)] = 1000,
    ctx: NodeContext | None = None,
) -> Table:
    """Cone search of a VizieR catalogue around a position.

    Args:
        catalog: VizieR catalogue or table identifier.
        ra: Centre right ascension (degrees).
        dec: Centre declination (degrees).
        radius_arcmin: Cone radius.
        max_rows: Row limit.

    Returns:
        The matching rows as a table (units from the VOTable).
    """
    if not catalog:
        raise ValueError("choose a VizieR catalogue")
    if ra is None or dec is None:
        raise ValueError("ra and dec are required")
    fetched = clients.vizier_cone(_cache(ctx), catalog, ra, dec, radius_arcmin, max_rows=max_rows)
    from astropy.io.votable import parse  # noqa: PLC0415 - lazy astropy import

    votable = parse(str(fetched.path), verify="ignore")
    tables = [t for t in votable.iter_tables() if t.array is not None and len(t.array)]
    if not tables:
        return Table(columns={}, meta={"catalog": catalog, "n_rows": 0})
    table = from_astropy(AstroTable(tables[0].to_table()))
    table.meta.update({"catalog": catalog, "url": fetched.url})
    return table


@node(
    id="core.fetch.mast_search",
    name="MAST Observation Search",
    category="Data/Fetch",
    icon="telescope",
    cost="expensive",
)
def mast_search(
    target: Annotated[
        str, Param(label="Target name", help="Resolved by MAST when ra/dec are empty")
    ] = "",
    ra: RaParam = None,
    dec: DecParam = None,
    radius_arcmin: Annotated[float, Param(unit="arcmin", min=0.01, max=60.0)] = 3.0,
    collection: Annotated[
        str, Param(label="Collection", help="e.g. HST, JWST, TESS; empty = all")
    ] = "",
    max_rows: Annotated[int, Param(min=1, max=5000)] = 500,
    ctx: NodeContext | None = None,
) -> Table:
    """Search MAST (CAOM) observations around a target or position.

    Args:
        target: Object name to resolve when coordinates are not given.
        ra: Right ascension (degrees).
        dec: Declination (degrees).
        radius_arcmin: Search radius.
        collection: Restrict to one mission/collection.
        max_rows: Row limit.

    Returns:
        A table of observations (``obs_id``, ``obs_collection``, ``target_name``, ``dataURL`` ...).
    """
    cache = _cache(ctx)
    if ra is None or dec is None:
        if not target:
            raise ValueError("give a target name or ra/dec")
        ra, dec = clients.mast_resolve(cache, target)
    fields, rows = clients.mast_cone(
        cache, ra, dec, radius_arcmin, collection=collection, max_rows=max_rows
    )
    table = rows_to_table(rows, [str(f.get("name")) for f in fields if f.get("name")])
    table.meta.update({"ra": ra, "dec": dec, "radius_arcmin": radius_arcmin, "target": target})
    return table
