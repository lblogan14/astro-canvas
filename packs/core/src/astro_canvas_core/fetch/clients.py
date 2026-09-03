"""Small ``httpx``-based clients for public archives, cached in ``<workspace>/downloads``.

Every request is keyed by a blake3 hash of ``(service, params)`` so a repeated query is served
from disk (and tests can pre-seed the cache). The archives' own REST/TAP endpoints are used
directly, which keeps the dependency footprint small and lets ``respx`` record/replay them.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from blake3 import blake3

USER_AGENT = "astro-canvas/0.1 (+https://github.com/bkoservices/astro-canvas)"
DEFAULT_TIMEOUT = 60.0

SDSS_SPECTRUM_URL = "https://{release}.sdss.org/optical/spectrum/view/data/format=fits/spec=lite"
SKYSERVER_SQL_URL = "https://skyserver.sdss.org/{release}/SkyServerWS/SearchTools/SqlSearch"
SIMBAD_TAP_URL = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
VIZIER_VOTABLE_URL = "https://vizier.cds.unistra.fr/viz-bin/votable"
MAST_INVOKE_URL = "https://mast.stsci.edu/api/v0/invoke"


class FetchError(RuntimeError):
    """The archive returned an error or an unexpected payload."""


def canonical(params: Any) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)


def cache_key(service: str, params: Any) -> str:
    return str(blake3(f"{service}|{canonical(params)}".encode()).hexdigest())[:24]


@dataclass(frozen=True)
class Fetched:
    """A downloaded (or cached) payload on disk."""

    path: Path
    cached: bool
    url: str


class FetchCache:
    """``<root>/downloads/<service>/<key><suffix>`` files with ``.meta.json`` sidecars."""

    def __init__(self, workspace: Path, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.root = Path(workspace) / "downloads"
        self.timeout = timeout

    def path_for(self, service: str, params: Any, suffix: str) -> Path:
        return self.root / service / f"{cache_key(service, params)}{suffix}"

    def fetch(
        self,
        service: str,
        params: Any,
        suffix: str,
        url: str,
        *,
        method: str = "GET",
        query: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        refresh: bool = False,
    ) -> Fetched:
        """Return the cached file for ``(service, params)`` or download it from ``url``."""
        target = self.path_for(service, params, suffix)
        if target.is_file() and not refresh:
            return Fetched(path=target, cached=True, url=url)
        target.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(
            timeout=self.timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = client.request(method, url, params=query, data=data)
        if response.status_code >= 400:
            raise FetchError(f"{service}: HTTP {response.status_code} from {response.url}")
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(response.content)
        os.replace(tmp, target)
        target.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "service": service,
                    "params": params,
                    "url": str(response.url),
                    "status": response.status_code,
                    "fetched": time.time(),
                    "bytes": len(response.content),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return Fetched(path=target, cached=False, url=str(response.url))


# --- SDSS -----------------------------------------------------------------------------------------


def sdss_spectrum(
    cache: FetchCache, plate: int, mjd: int, fiber: int, *, release: str = "dr17"
) -> Fetched:
    """Download the ``spec-lite`` FITS file of one SDSS/BOSS spectrum."""
    params = {"plate": int(plate), "mjd": int(mjd), "fiber": int(fiber), "release": release}
    return cache.fetch(
        "sdss",
        params,
        ".fits",
        SDSS_SPECTRUM_URL.format(release=release),
        query={"plateid": int(plate), "mjd": int(mjd), "fiberid": int(fiber)},
    )


def sdss_nearest_specobj(
    cache: FetchCache, ra: float, dec: float, radius_arcmin: float, *, release: str = "dr17"
) -> dict[str, Any]:
    """Nearest ``SpecObj`` row (``plate, mjd, fiberid, z, class``) via SkyServer SQL."""
    radius_deg = float(radius_arcmin) / 60.0
    sql = (
        "SELECT TOP 1 plate, mjd, fiberid, z, class, ra, dec, "
        f"dbo.fDistanceEq({ra:.7f},{dec:.7f},ra,dec) AS dist FROM SpecObj "
        f"WHERE ra BETWEEN {ra - radius_deg:.7f} AND {ra + radius_deg:.7f} "
        f"AND dec BETWEEN {dec - radius_deg:.7f} AND {dec + radius_deg:.7f} ORDER BY dist"
    )
    params = {"ra": round(float(ra), 6), "dec": round(float(dec), 6), "r": radius_arcmin}
    fetched = cache.fetch(
        "sdss-search",
        params,
        ".json",
        SKYSERVER_SQL_URL.format(release=release),
        query={"cmd": sql, "format": "json"},
    )
    payload = json.loads(fetched.path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for block in payload:
            if isinstance(block, dict) and isinstance(block.get("Rows"), list):
                rows.extend(r for r in block["Rows"] if isinstance(r, dict))
    if not rows:
        raise FetchError(f"no SDSS spectrum within {radius_arcmin}' of ({ra}, {dec})")
    return rows[0]


# --- SIMBAD ---------------------------------------------------------------------------------------


def simbad_resolve(cache: FetchCache, name: str) -> dict[str, Any]:
    """Resolve an object name through SIMBAD TAP: ``{main_id, ra, dec, otype}`` (degrees)."""
    clean = name.strip()
    if not clean:
        raise FetchError("object name is empty")
    escaped = clean.replace("'", "''")
    adql = (
        "SELECT TOP 1 basic.main_id, basic.ra, basic.dec, basic.otype_txt FROM basic "
        f"JOIN ident ON ident.oidref = basic.oid WHERE ident.id = '{escaped}'"
    )
    fetched = cache.fetch(
        "simbad",
        {"name": clean.lower()},
        ".json",
        SIMBAD_TAP_URL,
        method="POST",
        data={"request": "doQuery", "lang": "adql", "format": "json", "query": adql},
    )
    payload = json.loads(fetched.path.read_text(encoding="utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        raise FetchError(f"SIMBAD does not know {clean!r}")
    columns = [str(c.get("name", "")).lower() for c in payload.get("metadata", [])]
    row = dict(zip(columns, data[0], strict=False))
    return {
        "main_id": str(row.get("main_id", "")).strip(),
        "ra": float(row["ra"]),
        "dec": float(row["dec"]),
        "otype": str(row.get("otype_txt", "")).strip(),
        "source": "SIMBAD",
        "query": clean,
    }


# --- VizieR ---------------------------------------------------------------------------------------


def vizier_cone(
    cache: FetchCache,
    catalog: str,
    ra: float,
    dec: float,
    radius_arcmin: float,
    *,
    max_rows: int = 1000,
) -> Fetched:
    """Cone search of a VizieR catalogue as a VOTable file."""
    params = {
        "catalog": catalog,
        "ra": round(float(ra), 6),
        "dec": round(float(dec), 6),
        "r": float(radius_arcmin),
        "max": int(max_rows),
    }
    return cache.fetch(
        "vizier",
        params,
        ".vot",
        VIZIER_VOTABLE_URL,
        query={
            "-source": catalog,
            "-c": f"{ra:.7f} {dec:+.7f}",
            "-c.rm": float(radius_arcmin),
            "-out.max": int(max_rows),
            "-out.all": "",
        },
    )


# --- MAST -----------------------------------------------------------------------------------------


def _mast_invoke(cache: FetchCache, service: str, params: dict[str, Any], key: str) -> Any:
    request = {"service": service, "params": params, "format": "json", "pagesize": 5000, "page": 1}
    fetched = cache.fetch(
        "mast",
        {"service": service, "key": key},
        ".json",
        MAST_INVOKE_URL,
        method="POST",
        data={"request": json.dumps(request)},
    )
    payload = json.loads(fetched.path.read_text(encoding="utf-8"))
    status = payload.get("status") if isinstance(payload, dict) else None
    if status and status != "COMPLETE":
        raise FetchError(f"MAST {service}: {payload.get('msg') or status}")
    return payload


def mast_resolve(cache: FetchCache, target: str) -> tuple[float, float]:
    """Resolve a target name through MAST's name lookup: ``(ra, dec)`` in degrees."""
    payload = _mast_invoke(
        cache, "Mast.Name.Lookup", {"input": target, "format": "json"}, target.strip().lower()
    )
    coords = payload.get("resolvedCoordinate") if isinstance(payload, dict) else None
    if not coords:
        raise FetchError(f"MAST could not resolve {target!r}")
    return float(coords[0]["ra"]), float(coords[0]["decl"])


def mast_cone(
    cache: FetchCache,
    ra: float,
    dec: float,
    radius_arcmin: float,
    *,
    collection: str = "",
    max_rows: int = 500,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Observations around a position (``fields``, ``rows``) from the CAOM cone service."""
    radius_deg = float(radius_arcmin) / 60.0
    key = canonical(
        {
            "ra": round(float(ra), 6),
            "dec": round(float(dec), 6),
            "r": radius_deg,
            "c": collection,
            "n": int(max_rows),
        }
    )
    if collection:
        payload = _mast_invoke(
            cache,
            "Mast.Caom.Filtered.Position",
            {
                "columns": "*",
                "filters": [{"paramName": "obs_collection", "values": [collection]}],
                "position": f"{ra:.7f}, {dec:.7f}, {radius_deg:.7f}",
            },
            key,
        )
    else:
        payload = _mast_invoke(
            cache, "Mast.Caom.Cone", {"ra": float(ra), "dec": float(dec), "radius": radius_deg}, key
        )
    if not isinstance(payload, dict):
        raise FetchError("MAST returned an unexpected payload")
    fields = [f for f in payload.get("fields", []) if isinstance(f, dict)]
    rows = [r for r in payload.get("data", []) if isinstance(r, dict)][: int(max_rows)]
    return fields, rows


__all__ = [
    "MAST_INVOKE_URL",
    "SDSS_SPECTRUM_URL",
    "SIMBAD_TAP_URL",
    "SKYSERVER_SQL_URL",
    "VIZIER_VOTABLE_URL",
    "FetchCache",
    "FetchError",
    "Fetched",
    "cache_key",
    "mast_cone",
    "mast_resolve",
    "sdss_nearest_specobj",
    "sdss_spectrum",
    "simbad_resolve",
    "vizier_cone",
]
