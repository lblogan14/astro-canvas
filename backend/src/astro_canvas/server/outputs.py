"""``GET /api/outputs/{node_id}/{port}``: full node outputs as msgpack, Arrow, JSON or npz."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import msgpack
import numpy as np
import numpy.typing as npt
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from astro_canvas.sdk import PortType, decimate
from astro_canvas.sdk.blob import encode_npz, split_binary, to_manifest_data
from astro_canvas.server.workflows import get_runtime

router = APIRouter(tags=["outputs"])

Format = Literal["json", "msgpack", "arrow", "npz"]
ARROW_PART = "table.arrow"


def _axis_arrays(dump: Mapping[str, Any]) -> tuple[str | None, dict[str, npt.NDArray[Any]]]:
    """Top-level 1-d arrays sharing the length of the x axis (``wave`` when present)."""
    one_d = {k: v for k, v in dump.items() if isinstance(v, np.ndarray) and v.ndim == 1}
    if not one_d:
        return None, {}
    axis = "wave" if "wave" in one_d else next(iter(one_d))
    n = one_d[axis].shape[0]
    return axis, {k: v for k, v in one_d.items() if v.shape[0] == n}


def apply_view(
    value: PortType, n_out: int | None, view_range: tuple[float, float] | None
) -> PortType:
    """Restrict to ``view_range`` on the x axis and decimate to ``n_out`` points (MinMaxLTTB)."""
    if n_out is None and view_range is None:
        return value
    dump = value.model_dump(mode="python")
    axis, arrays = _axis_arrays(dump)
    if axis is None:
        return value
    x = arrays[axis]
    index = np.arange(x.shape[0])
    if view_range is not None:
        lo, hi = view_range
        index = index[(x >= lo) & (x <= hi)]
    if n_out is not None and index.size > n_out:
        y_name = (
            "flux"
            if "flux" in arrays and axis != "flux"
            else next((k for k in arrays if k != axis), axis)
        )
        xs, _ = decimate(x[index], arrays[y_name][index], n_out=n_out)
        index = index[np.searchsorted(x[index], xs)]
    return value.model_copy(update={k: v[index] for k, v in arrays.items()})


def _parse_range(raw: str | None) -> tuple[float, float] | None:
    if raw is None:
        return None
    try:
        lo_s, hi_s = raw.split(",")
        lo, hi = float(lo_s), float(hi_s)
    except ValueError:
        raise HTTPException(status_code=400, detail="range must be 'lo,hi'") from None
    return (min(lo, hi), max(lo, hi))


def render(value: PortType, fmt: Format) -> Response:
    data, arrays, binaries = split_binary(value.model_dump(mode="python"))
    if fmt == "json":
        body = to_manifest_data(_lists(value.model_dump(mode="python")))
        return JSONResponse({"type_id": value.type_id(), "data": body})
    if fmt == "msgpack":
        payload = {
            "type_id": value.type_id(),
            "data": to_manifest_data(data),
            "arrays": {
                name: {
                    "dtype": np.ascontiguousarray(arr).dtype.str.lstrip("<=|"),
                    "shape": list(arr.shape),
                    "data": np.ascontiguousarray(arr).tobytes(),
                }
                for name, arr in arrays.items()
            },
            "bytes": dict(binaries),
        }
        return Response(msgpack.packb(payload, use_bin_type=True), media_type="application/msgpack")
    if fmt == "npz":
        if not arrays:
            raise HTTPException(status_code=406, detail="value has no arrays")
        return Response(encode_npz(arrays), media_type="application/octet-stream")
    return _arrow(value, arrays)


def _lists(body: Any) -> Any:
    if isinstance(body, np.ndarray):
        return body.tolist()
    if isinstance(body, dict):
        return {k: _lists(v) for k, v in body.items()}
    if isinstance(body, list):
        return [_lists(v) for v in body]
    return body


def _arrow(value: PortType, arrays: Mapping[str, npt.NDArray[Any]]) -> Response:
    import pyarrow as pa  # noqa: PLC0415 - lazy: only for arrow responses

    blob = value.to_blob()
    if ARROW_PART in blob.parts:
        return Response(blob.parts[ARROW_PART], media_type="application/vnd.apache.arrow.stream")
    columns = {k: v for k, v in arrays.items() if v.ndim == 1}
    lengths = {v.shape[0] for v in columns.values()}
    if not columns or len(lengths) != 1:
        raise HTTPException(status_code=406, detail="value is not tabular")
    table = pa.table({name: pa.array(col) for name, col in columns.items()})
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return Response(sink.getvalue().to_pybytes(), media_type="application/vnd.apache.arrow.stream")


@router.get("/outputs/{node_id}/{port}", response_model=None)
async def get_output(  # noqa: PLR0917 - query parameters
    request: Request,
    node_id: str,
    port: str,
    workflow_id: str = Query(description="Workflow the node belongs to."),
    fmt: Format = "json",
    decimate: int | None = Query(default=None, ge=4, alias="decimate"),
    range: str | None = Query(default=None, description="``lo,hi`` on the x axis."),  # noqa: A002
) -> Response:
    """A finished node's output. ``decimate``/``range`` apply to 1-d spectrum-like values."""
    runtime = get_runtime(request)
    scheduler = runtime.schedulers.get(workflow_id)
    value = scheduler.output(node_id, port) if scheduler is not None else None
    if value is None:
        raise HTTPException(status_code=404, detail=f"no output for {node_id}.{port}")
    return render(apply_view(value, decimate, _parse_range(range)), fmt)


__all__ = ["apply_view", "render", "router"]
