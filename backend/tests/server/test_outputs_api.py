"""``GET /api/outputs/{node}/{port}``: formats, decimation, ranges and the 1e6-point budget."""

from __future__ import annotations

import io
import time
from collections.abc import Iterator

import msgpack
import numpy as np
import pytest
from fastapi.testclient import TestClient

from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client
from tests.server.test_workflows_api import wait_status

BIG = {
    "id": "outputs-big",
    "nodes": {"src": {"type": "test.spec.make", "params": {"n": 1_000_000}}},
}


@pytest.fixture
def api(settings: Settings, test_discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, test_discovery)) as client:
        assert client.post("/api/workflows", json=BIG).status_code == 201
        wait_status(client, "outputs-big", timeout=30)
        yield client


def test_decimated_json_is_small_and_fast(api: TestClient) -> None:
    params = {"workflow_id": "outputs-big", "decimate": 4000}
    api.get("/api/outputs/src/out", params=params)  # warm up (imports, caches)
    started = time.perf_counter()
    response = api.get("/api/outputs/src/out", params=params)
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    body = response.json()
    assert body["type_id"] == "astro.Spectrum1D"
    assert 4 <= len(body["data"]["wave"]) <= 4000 and len(body["data"]["flux"]) == len(
        body["data"]["wave"]
    )
    assert body["data"]["wave"][0] == 1000.0 and body["data"]["wave"][-1] == 2000.0  # extremes kept
    assert elapsed < 0.1, f"decimated fetch took {elapsed * 1000:.0f} ms"


def test_range_and_decimate_combine(api: TestClient) -> None:
    body = api.get(
        "/api/outputs/src/out",
        params={"workflow_id": "outputs-big", "range": "1500,1510", "decimate": 100},
    ).json()
    wave = body["data"]["wave"]
    assert len(wave) <= 100 and min(wave) >= 1500 and max(wave) <= 1510
    assert (
        api.get(
            "/api/outputs/src/out", params={"workflow_id": "outputs-big", "range": "bad"}
        ).status_code
        == 400
    )
    assert (
        api.get(
            "/api/outputs/src/out", params={"workflow_id": "outputs-big", "decimate": 2}
        ).status_code
        == 422
    )


def test_binary_formats(api: TestClient) -> None:
    base = {"workflow_id": "outputs-big", "decimate": 1000}
    packed = api.get("/api/outputs/src/out", params={**base, "fmt": "msgpack"})
    assert packed.headers["content-type"].startswith("application/msgpack")
    payload = msgpack.unpackb(packed.content, raw=False)
    assert payload["type_id"] == "astro.Spectrum1D" and payload["data"]["frame"] == "observed"
    wave = np.frombuffer(
        payload["arrays"]["wave"]["data"], dtype=payload["arrays"]["wave"]["dtype"]
    )
    assert wave.shape[0] == payload["arrays"]["wave"]["shape"][0] <= 1000

    npz = api.get("/api/outputs/src/out", params={**base, "fmt": "npz"})
    with np.load(io.BytesIO(npz.content), allow_pickle=False) as arrays:
        assert set(arrays.files) == {"wave", "flux"} and arrays["wave"].shape[0] <= 1000

    arrow = api.get("/api/outputs/src/out", params={**base, "fmt": "arrow"})
    assert arrow.headers["content-type"].startswith("application/vnd.apache.arrow.stream")
    import pyarrow as pa

    table = pa.ipc.open_stream(pa.py_buffer(arrow.content)).read_all()
    assert table.column_names == ["wave", "flux"] and table.num_rows <= 1000


def test_full_output_and_missing(api: TestClient) -> None:
    full = api.get("/api/outputs/src/out", params={"workflow_id": "outputs-big", "fmt": "npz"})
    with np.load(io.BytesIO(full.content), allow_pickle=False) as arrays:
        assert arrays["wave"].shape == (1_000_000,)
    assert (
        api.get("/api/outputs/src/nope", params={"workflow_id": "outputs-big"}).status_code == 404
    )
    assert api.get("/api/outputs/src/out", params={"workflow_id": "unknown"}).status_code == 404
    assert api.get("/api/outputs/src/out").status_code == 422  # workflow_id is required


def test_scalar_formats(api: TestClient) -> None:
    doc = {
        "id": "outputs-scalar",
        "nodes": {"c": {"type": "core.math.constant", "params": {"value": 1.5}}},
    }
    api.post("/api/workflows", json=doc)
    wait_status(api, "outputs-scalar")
    params = {"workflow_id": "outputs-scalar"}
    assert api.get("/api/outputs/c/out", params=params).json() == {
        "type_id": "astro.Float",
        "data": {"value": 1.5},
    }
    assert api.get("/api/outputs/c/out", params={**params, "fmt": "npz"}).status_code == 406
    assert api.get("/api/outputs/c/out", params={**params, "fmt": "arrow"}).status_code == 406
    packed = msgpack.unpackb(
        api.get("/api/outputs/c/out", params={**params, "fmt": "msgpack"}).content, raw=False
    )
    assert packed == {"type_id": "astro.Float", "data": {"value": 1.5}, "arrays": {}, "bytes": {}}
