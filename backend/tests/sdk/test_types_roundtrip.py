"""Port type blobs round-trip; summaries decimate; compatibility rules hold."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core import types as T

from astro_canvas.sdk import (
    Blob,
    BlobError,
    DuplicateNodeError,
    Float32_3D,
    NodeDefinitionError,
    PortType,
    TypeRegistry,
    arrays_equal,
    decimate,
    is_compatible,
    port_type,
)
from astro_canvas.sdk.porttype import summarize_arrays

WAVE = np.linspace(1000.0, 2000.0, 50)


def _samples() -> list[PortType]:
    spec = T.Spectrum1D(
        wave=WAVE,
        flux=np.sin(WAVE),
        error=np.full(50, 0.1),
        wave_unit="nm",
        frame="rest",
        z=0.5,
        meta={"object": "J1234", "exptime": 1200.0, "nested": {"a": [1, 2]}},
    )
    return [
        T.Float(value=1.5),
        T.Int(value=-3),
        T.Str(value="hé"),
        T.Bool(value=True),
        T.Json(value={"a": [1, "x", None], "b": 2.5}),
        T.File(path="data/spec.fits", blake3="ab" * 32, size=12, mime="image/fits"),
        spec,
        T.SpectrumCollection(items=[spec, spec.model_copy(update={"z": None})], labels=["a", "b"]),
        T.Table(
            columns={
                "wrest": np.array([1215.67, 1025.72]),
                "name": np.array(["HI 1215", "HI 1025"]),
                "n": np.array([1, 2], dtype=np.int32),
                "ok": np.array([True, False]),
            },
            units={"wrest": "Angstrom"},
            meta={"source": "test"},
        ),
        T.Image2D(data=np.arange(6, dtype=np.float32).reshape(2, 3), header={"BUNIT": "x"}),
        T.Cube3D(
            flux=np.zeros((2, 2, 2), np.float32), wave=np.array([1.0, 2.0]), instrument="MUSE"
        ),
        T.Transition(name="HI 1215", wrest=1215.67, fval=0.4164, gamma=6.265e8),
        T.LineList(
            wrest=np.array([1.0, 2.0]), name=np.array(["a", "b"]), fval=np.array([0.1, 0.2])
        ),
        T.Redshift(z=2.1, z_err=1e-4, method="zfind", source="test"),
        T.Continuum(cont=np.ones(50), masks=[(1.0, 2.0)], method="legendre", order=3, bic=12.5),
        T.RangeMask(ranges=[(-200.0, 200.0)], frame="velocity", unit="km / s"),
        T.Region2D(regions=[T.Region(shape="circle", pixel=[10, 10, 3], sky=[1.0, 2.0])]),
        T.EWMeasurement(W=0.5, W_e=0.05, logN=14.2, saturated=False, flag=1),
        T.Figure(kind="png", png=b"\x89PNG\r\n\x1a\n\x00"),
        T.Figure(kind="plotly", plotly={"data": [], "layout": {"title": "t"}}),
    ]


def _assert_equal(a: object, b: object) -> None:
    if isinstance(a, np.ndarray):
        assert isinstance(b, np.ndarray) and arrays_equal(a, b), (a, b)
    elif isinstance(a, PortType):
        assert type(a) is type(b)
        for name in type(a).model_fields:
            _assert_equal(getattr(a, name), getattr(b, name))
    elif isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys()
        for k in a:
            _assert_equal(a[k], b[k])
    elif isinstance(a, list | tuple):
        assert isinstance(b, list | tuple) and len(a) == len(b)
        for x, y in zip(a, b, strict=True):
            _assert_equal(x, y)
    else:
        assert a == b


@pytest.mark.parametrize("value", _samples(), ids=lambda v: f"{v.type_id()}:{v.__class__.__name__}")
def test_blob_roundtrip(value: PortType) -> None:
    blob = value.to_blob()
    assert blob.manifest["type"] == value.type_id()
    packed = blob.pack()
    assert packed == value.to_blob().pack(), "packing must be deterministic"
    restored = type(value).from_blob(Blob.unpack(packed))
    _assert_equal(value, restored)
    assert blob.size == sum(len(p) for p in blob.parts.values())


def test_any_is_never_serialized() -> None:
    value = T.Any(value=object())
    with pytest.raises(BlobError, match="in-process"):
        value.to_blob()
    assert value.summary() == {"type": "astro.Any", "python_type": "object"}


def test_blob_type_mismatch_and_corruption() -> None:
    blob = T.Float(value=1.0).to_blob()
    with pytest.raises(BlobError, match="expected 'astro.Int'"):
        T.Int.from_blob(blob)
    with pytest.raises(BlobError, match="not an astro.Table"):
        T.Table.from_blob(blob)
    with pytest.raises(BlobError, match="not a packed blob"):
        Blob.unpack(b"garbage")
    with pytest.raises(BlobError, match="object array"), pytest.warns(UserWarning):
        T.Json(value=1).model_copy(update={"value": np.array([object()])}).to_blob()


def test_spectrum_summary_decimates_a_million_points_fast() -> None:
    n = 1_000_000
    spec = T.Spectrum1D(wave=np.linspace(3000, 9000, n), flux=np.random.default_rng(0).random(n))
    decimate(WAVE, WAVE, 10)  # warm up the tsdownsample import
    start = time.perf_counter()
    summary = spec.summary()
    elapsed = time.perf_counter() - start
    assert summary["n"] == n and len(summary["wave"]) <= 4000 and len(summary["flux"]) <= 4000
    assert summary["wave"][0] == 3000.0 and summary["wave"][-1] == 9000.0
    assert elapsed < 0.05, f"summary took {elapsed * 1000:.1f} ms"
    windowed = spec.summary({"lo": 4000, "hi": 4010, "n_out": 100})
    assert len(windowed["wave"]) <= 100 and min(windowed["wave"]) >= 4000
    short = T.Spectrum1D(wave=WAVE, flux=WAVE).summary()
    assert short["wave"] == WAVE.tolist()


def test_decimate_handles_nans_and_bad_input() -> None:
    x = np.arange(10_000.0)
    y = np.sin(x)
    y[::7] = np.nan
    dx, dy = decimate(x, y, 500)
    assert len(dx) == len(dy) <= 500 and np.isnan(dy).any()
    with pytest.raises(ValueError, match="equal length"):
        decimate(x, y[:-1])


def test_default_summary_and_collection_summary() -> None:
    samples = _samples()
    table = samples[8]
    summary = table.summary({"rows": 1})
    assert summary["n_rows"] == 2 and summary["head"]["name"] == ["HI 1215"]
    image = samples[9].summary()
    assert image["shape"] == [2, 3] and image["tile"]["minmax"] == [0.0, 5.0]
    assert image["tile"]["width"] == 3 and image["tile"]["height"] == 2
    assert summarize_arrays({"b": b"12", "l": (np.array([np.nan]),)}) == {
        "b": {"$bytes": 2},
        "l": [{"$ndarray": {"shape": [1], "dtype": "float64"}}],
    }
    coll = samples[7].summary()
    assert coll["count"] == 2 and [len(i["wave"]) for i in coll["items"]] == [50, 50]
    assert samples[-2].summary()["kind"] == "png"


def test_model_validators_reject_inconsistent_shapes() -> None:
    with pytest.raises(ValueError, match="flux has 2 points"):
        T.Spectrum1D(wave=np.zeros(3), flux=np.zeros(2))
    with pytest.raises(ValueError, match="different lengths"):
        T.Table(columns={"a": np.zeros(2), "b": np.zeros(3)})
    with pytest.raises(ValueError, match="wave length"):
        T.Cube3D(flux=np.zeros((2, 1, 1), np.float32), wave=np.zeros(3))
    with pytest.raises(ValueError, match="labels"):
        T.SpectrumCollection(items=[], labels=["x"])
    with pytest.raises(ValueError, match="payload"):
        T.Figure(kind="png", plotly={})
    with pytest.raises(ValueError, match="1-d array"):
        T.LineList(wrest=np.zeros((2, 2)), name=np.array(["a"]), fval=np.zeros(1))


def test_compatibility_rules() -> None:
    reg = TypeRegistry()
    for cls in T.ALL_TYPES:
        reg.add(cls, pack="core")
    assert reg.is_compatible("astro.Spectrum1D", "astro.Spectrum1D")
    assert reg.is_compatible("astro.Spectrum1D", "astro.SpectrumCollection")
    assert not reg.is_compatible("astro.SpectrumCollection", "astro.Spectrum1D")
    assert reg.is_compatible("astro.Table", "astro.Any")
    assert is_compatible("astro.Float", "astro.Json")
    assert not is_compatible("astro.Table", "astro.Json")
    assert not is_compatible("astro.Float", "astro.Int")
    assert not is_compatible("x.Unknown", "astro.Float", reg)
    assert len(reg) == 20 and reg.ids()[0] == "astro.Any"
    assert reg.spec("astro.Spectrum1D").description.startswith("A one-dimensional spectrum")
    assert reg.remove_pack("core") == 20 and len(reg) == 0


def test_port_type_decorator_validation() -> None:
    with pytest.raises(NodeDefinitionError, match="invalid port type id"):
        port_type(id="nodots")
    with pytest.raises(NodeDefinitionError, match="PortType subclass"):
        port_type(id="x.Y")(dict)  # type: ignore[type-var]

    class Undecorated(PortType):
        x: int = 0

    with pytest.raises(NodeDefinitionError, match="not decorated"):
        Undecorated.type_id()
    reg = TypeRegistry()
    with pytest.raises(NodeDefinitionError):
        reg.add(Undecorated)

    @port_type(id="astro.Float", color="#000")
    class Impostor(PortType):
        value: float

    reg.add(T.Float)
    reg.add(T.Float)  # idempotent
    with pytest.raises(DuplicateNodeError):
        reg.add(Impostor)


def test_mappable_parts_roundtrip_through_every_reader(tmp_path: Path) -> None:
    """``__mmap_fields__`` splits big arrays out; all three readers return the same values."""
    from astro_canvas.sdk import is_memmapped
    from astro_canvas.sdk.memmap import MMAP_MIN_BYTES_ENV, memmap_part

    @port_type(id="test.Big")
    class Big(PortType):
        __mmap_fields__ = ("data", "missing")

        data: Float32_3D
        label: str = "x"

    array = np.arange(4 * 8 * 8, dtype=np.float32).reshape(4, 8, 8)
    value = Big(data=array)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(MMAP_MIN_BYTES_ENV, "128")
        blob = value.to_blob()
        assert blob.manifest["mmap"] == {"data": "data.npy"}
        path = tmp_path / "big.blob"
        path.write_bytes(blob.pack())
        assert np.array_equal(Big.from_blob(blob).data, array)
        mapped = Big.from_blob_file(path)
    assert is_memmapped(mapped.data) and np.array_equal(mapped.data, array)
    assert memmap_part(path, "nope.npy") is None
    with pytest.raises(BlobError, match="missing array part"):
        Big.from_blob(Blob(manifest=blob.manifest, parts={}))
