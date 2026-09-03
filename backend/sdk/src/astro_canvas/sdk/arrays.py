"""NumPy arrays as pydantic fields, plus the decimation helper used by previews."""

from __future__ import annotations

from typing import Annotated, Any

import numpy as np
import numpy.typing as npt
from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

_JSON_TYPES: dict[str, str] = {"f": "number", "i": "integer", "u": "integer", "b": "boolean"}


def _json_item_type(dtype: np.dtype[Any] | None) -> str:
    if dtype is None:
        return "number"
    return _JSON_TYPES.get(dtype.kind, "string")


class NDArrayAnnotation:
    """``Annotated`` metadata that validates values into ``numpy.ndarray``.

    Lists, tuples, scalars, and arrays are accepted and coerced with ``np.asarray``; ``dtype`` and
    ``ndim`` are enforced when given. JSON mode serializes to nested lists and the JSON Schema
    carries an ``x-ndarray`` block describing dtype and rank.
    """

    def __init__(self, dtype: npt.DTypeLike | None = None, ndim: int | None = None) -> None:
        self.dtype: np.dtype[Any] | None = np.dtype(dtype) if dtype is not None else None
        self.ndim = ndim

    def validate(self, value: Any) -> npt.NDArray[Any]:
        if isinstance(value, np.ndarray) and (self.dtype is None or value.dtype == self.dtype):
            array = value
        else:
            try:
                array = np.asarray(value, dtype=self.dtype)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"cannot convert value to ndarray: {exc}") from exc
        if array.dtype == object:
            raise ValueError("object arrays are not supported")
        if self.ndim is not None and array.ndim != self.ndim:
            raise ValueError(f"expected a {self.ndim}-d array, got shape {array.shape}")
        return array

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            self.validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda a: a.tolist(), when_used="json"
            ),
        )

    def __get_pydantic_json_schema__(
        self, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        meta: dict[str, Any] = {"ndim": self.ndim}
        if self.dtype is not None:
            meta["dtype"] = self.dtype.name
        item: JsonSchemaValue = {"type": _json_item_type(self.dtype)}
        out: JsonSchemaValue = {"type": "array", "items": item, "x-ndarray": meta}
        return out

    def __repr__(self) -> str:
        return f"NDArrayAnnotation(dtype={self.dtype}, ndim={self.ndim})"


NDArray = Annotated[npt.NDArray[Any], NDArrayAnnotation()]
"""Any dtype, any rank."""

FloatArray = Annotated[npt.NDArray[np.float64], NDArrayAnnotation(np.float64)]
"""float64, any rank."""

Float1D = Annotated[npt.NDArray[np.float64], NDArrayAnnotation(np.float64, ndim=1)]
Float2D = Annotated[npt.NDArray[np.float64], NDArrayAnnotation(np.float64, ndim=2)]
Float3D = Annotated[npt.NDArray[np.float64], NDArrayAnnotation(np.float64, ndim=3)]
Float32_2D = Annotated[npt.NDArray[np.float32], NDArrayAnnotation(np.float32, ndim=2)]
Float32_3D = Annotated[npt.NDArray[np.float32], NDArrayAnnotation(np.float32, ndim=3)]
StrArray = Annotated[npt.NDArray[np.str_], NDArrayAnnotation(np.str_, ndim=1)]


def arrays_equal(a: npt.ArrayLike, b: npt.ArrayLike) -> bool:
    """Shape/dtype-aware equality that treats NaN as equal to NaN."""
    x, y = np.asarray(a), np.asarray(b)
    if x.shape != y.shape or x.dtype != y.dtype:
        return False
    if x.dtype.kind in "fc":
        return bool(np.array_equal(x, y, equal_nan=True))
    return bool(np.array_equal(x, y))


def decimate(
    x: npt.ArrayLike, y: npt.ArrayLike, n_out: int = 4000
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Downsample ``(x, y)`` to at most ``n_out`` points with MinMaxLTTB, preserving extrema.

    ``x`` must be one-dimensional and monotonically increasing; NaNs in ``y`` are kept as gaps.
    """
    # Lazy: keeps `import astro_canvas.sdk` fast; tsdownsample is only needed for previews.
    from tsdownsample import (  # noqa: PLC0415
        MinMaxLTTBDownsampler,
        NaNMinMaxLTTBDownsampler,
    )

    xs = np.asarray(x, dtype=np.float64)
    ys = np.asarray(y, dtype=np.float64)
    if xs.ndim != 1 or ys.shape != xs.shape:
        raise ValueError("decimate expects two 1-d arrays of equal length")
    if xs.size <= n_out or n_out < 4:
        return xs, ys
    sampler = NaNMinMaxLTTBDownsampler() if np.isnan(ys).any() else MinMaxLTTBDownsampler()
    idx = sampler.downsample(xs, ys, n_out=n_out)
    return xs[idx], ys[idx]
