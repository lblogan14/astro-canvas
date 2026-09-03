"""``core.fetch.*`` nodes against recorded (respx) archive responses, cached in the workspace."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
import respx
from astro_canvas_core.fetch import clients
from astro_canvas_core.fetch.clients import FetchCache, FetchError, cache_key
from astro_canvas_core.nodes import fetch as fetch_nodes
from astro_canvas_core.types import Json, Spectrum1D, Table
from astropy.io import fits

from astro_canvas.sdk import NullContext

FIXTURES = Path(__file__).parent / "fixtures"


def _sdss_lite_bytes() -> bytes:
    """A tiny ``spec-lite`` style FITS file (COADD table + SPECOBJ with Z)."""
    n = 32
    coadd = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="flux", format="E", array=np.linspace(1, 2, n)),
            fits.Column(name="loglam", format="E", array=np.linspace(3.58, 3.96, n)),
            fits.Column(name="ivar", format="E", array=np.full(n, 4.0)),
            fits.Column(name="model", format="E", array=np.ones(n)),
        ],
        name="COADD",
    )
    specobj = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="Z", format="D", array=np.array([0.1234])),
            fits.Column(name="Z_ERR", format="D", array=np.array([1e-4])),
            fits.Column(name="CLASS", format="6A", array=np.array(["QSO"])),
        ],
        name="SPECOBJ",
    )
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "SDSS 2.5-M"
    buffer = io.BytesIO()
    fits.HDUList([primary, coadd, specobj]).writeto(buffer)
    return buffer.getvalue()


@pytest.fixture
def ctx(tmp_path: Path) -> NullContext:
    return NullContext(workspace=tmp_path / "ws")


@respx.mock(assert_all_called=True)
def test_sdss_spectrum_by_plate_downloads_once_then_uses_cache(
    respx_mock: respx.MockRouter, ctx: NullContext
) -> None:
    route = respx_mock.get(url__startswith="https://dr17.sdss.org/optical/spectrum/view/data").mock(
        return_value=httpx.Response(200, content=_sdss_lite_bytes())
    )
    spec = fetch_nodes.sdss_spectrum.call(
        params={"plate": 2663, "mjd": 54234, "fiber": 136}, ctx=ctx
    )
    assert isinstance(spec, Spectrum1D) and len(spec) == 32
    assert spec.z == pytest.approx(0.1234) and spec.meta["class"] == "QSO"
    assert spec.meta["plate"] == 2663 and spec.meta["format"] == "sdss"
    assert spec.error is not None and spec.error[0] == pytest.approx(0.5)
    assert route.call_count == 1
    request = route.calls.last.request
    assert request.url.params["plateid"] == "2663" and request.url.params["fiberid"] == "136"

    cached = ctx.workspace / "downloads" / "sdss"
    files = sorted(p.name for p in cached.iterdir())
    assert len(files) == 2 and files[0].endswith(".fits") and files[1].endswith(".meta.json")
    meta = json.loads((cached / files[1]).read_text(encoding="utf-8"))
    assert meta["params"]["plate"] == 2663 and meta["status"] == 200

    again = fetch_nodes.sdss_spectrum.call(
        params={"plate": 2663, "mjd": 54234, "fiber": 136}, ctx=ctx
    )
    assert route.call_count == 1  # served from the workspace cache
    assert again.meta["cached_file"] == files[0]
    assert any("from cache" in message for _, message, _ in ctx.logs)


@respx.mock
def test_sdss_spectrum_by_position_uses_skyserver(
    respx_mock: respx.MockRouter, ctx: NullContext
) -> None:
    respx_mock.get(url__startswith="https://skyserver.sdss.org/dr17/SkyServerWS").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "TableName": "Table1",
                    "Rows": [
                        {"plate": 266, "mjd": 51630, "fiberid": 1, "z": 0.02, "class": "GALAXY"}
                    ],
                }
            ],
        )
    )
    fits_route = respx_mock.get(url__startswith="https://dr17.sdss.org/optical/spectrum").mock(
        return_value=httpx.Response(200, content=_sdss_lite_bytes())
    )
    spec = fetch_nodes.sdss_spectrum.call(params={"ra": 145.0, "dec": 0.5}, ctx=ctx)
    assert spec.meta["plate"] == 266 and spec.meta["mjd"] == 51630 and spec.meta["fiber"] == 1
    assert fits_route.calls.last.request.url.params["plateid"] == "266"
    with pytest.raises(ValueError, match="plate/mjd/fiber or ra/dec"):
        fetch_nodes.sdss_spectrum.call(params={}, ctx=ctx)


@respx.mock
def test_sdss_errors_surface_as_fetch_errors(
    respx_mock: respx.MockRouter, ctx: NullContext
) -> None:
    respx_mock.get(url__startswith="https://skyserver.sdss.org").mock(
        return_value=httpx.Response(200, json=[{"Rows": []}])
    )
    with pytest.raises(FetchError, match="no SDSS spectrum"):
        fetch_nodes.sdss_spectrum.call(params={"ra": 1.0, "dec": 1.0}, ctx=ctx)
    respx_mock.get(url__startswith="https://dr17.sdss.org").mock(return_value=httpx.Response(404))
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_nodes.sdss_spectrum.call(params={"plate": 1, "mjd": 2, "fiber": 3}, ctx=ctx)
    assert not list((ctx.workspace / "downloads" / "sdss").glob("*.fits"))  # nothing cached


@respx.mock
def test_simbad_resolve_from_recorded_tap_response(
    respx_mock: respx.MockRouter, ctx: NullContext
) -> None:
    payload = json.loads((FIXTURES / "simbad_m31.json").read_text(encoding="utf-8"))
    route = respx_mock.post(clients.SIMBAD_TAP_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = fetch_nodes.simbad_resolve.call(params={"name": "M31"}, ctx=ctx)
    assert isinstance(result, Json)
    assert result.value["main_id"] == "M  31" and result.value["otype"] == "AGN"
    assert result.value["ra"] == pytest.approx(10.684708) and result.value["dec"] == pytest.approx(
        41.26875
    )
    body = route.calls.last.request.content.decode()
    assert "ident.id+%3D+%27M31%27" in body or "ident.id = 'M31'" in body.replace("+", " ").replace(
        "%3D", "="
    ).replace("%27", "'")
    respx_mock.post(clients.SIMBAD_TAP_URL).mock(
        return_value=httpx.Response(200, json={"metadata": [], "data": []})
    )
    with pytest.raises(FetchError, match="does not know"):
        fetch_nodes.simbad_resolve.call(params={"name": "Nonexistent Object 42"}, ctx=ctx)
    with pytest.raises(FetchError, match="empty"):
        fetch_nodes.simbad_resolve.call(params={"name": "  "}, ctx=ctx)


@respx.mock
def test_vizier_cone_search_parses_votable(respx_mock: respx.MockRouter, ctx: NullContext) -> None:
    votable = (FIXTURES / "vizier_cone.vot").read_bytes()
    route = respx_mock.get(url__startswith=clients.VIZIER_VOTABLE_URL).mock(
        return_value=httpx.Response(200, content=votable)
    )
    table = fetch_nodes.vizier_query.call(
        params={"catalog": "I/355/gaiadr3", "ra": 10.68, "dec": 41.27, "radius_arcmin": 1.0},
        ctx=ctx,
    )
    assert isinstance(table, Table) and table.n_rows == 3
    assert {"RA_ICRS", "DE_ICRS", "Gmag", "Source"} <= set(table.columns)
    assert table.units["RA_ICRS"] == "deg" and table.meta["catalog"] == "I/355/gaiadr3"
    assert table.columns["Gmag"][0] == pytest.approx(15.1)
    params = route.calls.last.request.url.params
    assert params["-source"] == "I/355/gaiadr3" and params["-c.rm"] == "1.0"
    with pytest.raises(ValueError, match="catalogue"):
        fetch_nodes.vizier_query.call(params={"ra": 1.0, "dec": 1.0}, ctx=ctx)
    with pytest.raises(ValueError, match="ra and dec"):
        fetch_nodes.vizier_query.call(params={"catalog": "x"}, ctx=ctx)


@respx.mock
def test_mast_search_resolves_and_lists_observations(
    respx_mock: respx.MockRouter, ctx: NullContext
) -> None:
    lookup = json.loads((FIXTURES / "mast_lookup.json").read_text(encoding="utf-8"))
    cone = json.loads((FIXTURES / "mast_cone.json").read_text(encoding="utf-8"))

    def reply(request: httpx.Request) -> httpx.Response:
        body = json.loads(httpx.QueryParams(request.content.decode())["request"])
        if body["service"] == "Mast.Name.Lookup":
            return httpx.Response(200, json=lookup)
        assert body["service"] == "Mast.Caom.Filtered.Position"
        assert body["params"]["filters"][0]["values"] == ["HST"]
        return httpx.Response(200, json=cone)

    respx_mock.post(clients.MAST_INVOKE_URL).mock(side_effect=reply)
    table = fetch_nodes.mast_search.call(
        params={"target": "M31", "collection": "HST", "radius_arcmin": 2.0}, ctx=ctx
    )
    assert table.n_rows == 2 and table.columns["obs_collection"].tolist() == ["HST", "HST"]
    assert table.columns["t_exptime"].dtype == np.float64 and np.isnan(
        table.columns["t_exptime"][1]
    )
    assert table.meta["ra"] == pytest.approx(10.684708)
    with pytest.raises(ValueError, match="target name or ra/dec"):
        fetch_nodes.mast_search.call(params={}, ctx=ctx)

    respx_mock.post(clients.MAST_INVOKE_URL).mock(
        return_value=httpx.Response(200, json={"status": "ERROR", "msg": "boom"})
    )
    with pytest.raises(FetchError, match="boom"):
        fetch_nodes.mast_search.call(params={"ra": 1.0, "dec": 2.0}, ctx=ctx)


def test_cache_key_is_stable_and_rows_to_table_types(tmp_path: Path) -> None:
    assert cache_key("s", {"b": 1, "a": 2}) == cache_key("s", {"a": 2, "b": 1})
    assert cache_key("s", {"a": 1}) != cache_key("t", {"a": 1})
    cache = FetchCache(tmp_path)
    assert cache.path_for("sdss", {"plate": 1}, ".fits").parent == tmp_path / "downloads" / "sdss"
    table = fetch_nodes.rows_to_table(
        [{"a": 1, "b": "x", "c": None}, {"a": None, "b": None, "c": None}], ["a", "b", "c", "d"]
    )
    assert table.columns["a"].dtype == np.float64 and np.isnan(table.columns["a"][1])
    assert table.columns["b"].tolist() == ["x", ""] and table.columns["c"].dtype.kind == "U"
    assert table.columns["d"].tolist() == ["", ""]


def test_fetch_nodes_are_expensive_and_pack_needs_network() -> None:
    from astro_canvas.sdk import discover

    for node in (
        fetch_nodes.sdss_spectrum,
        fetch_nodes.simbad_resolve,
        fetch_nodes.vizier_query,
        fetch_nodes.mast_search,
    ):
        assert node.spec.cost == "expensive" and node.spec.category == "Data/Fetch"
    packs = {p.name: p for p in discover().packs}
    assert packs["core"].security == "needs-network" and packs["rbcodes"].security == "standard"
