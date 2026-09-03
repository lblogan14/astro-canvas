"""Behaviour of the first ``core.*`` nodes and the rbcodes pack stub."""

from __future__ import annotations

import os

import numpy as np
import pytest
from astro_canvas_core.nodes import list as list_nodes
from astro_canvas_core.nodes import math as math_nodes
from astro_canvas_core.nodes import note, spec
from astro_canvas_core.nodes._expr import ExpressionError
from astro_canvas_core.types import Spectrum1D

from astro_canvas.sdk import NullContext


def _spec() -> Spectrum1D:
    wave = np.linspace(1200.0, 1300.0, 11)
    return Spectrum1D(wave=wave, flux=np.arange(11.0), error=np.ones(11), meta={"src": "t"})


def test_constant_and_expr() -> None:
    assert math_nodes.constant(2.5) == 2.5
    assert math_nodes.constant.call(params={"value": 3}) == 3.0
    assert math_nodes.expr("sqrt(x**2 + y**2)", x=3, y=4) == 5.0
    assert math_nodes.expr("-x + pi * 0 + max(y, z) // 2 % 5", x=1, y=7, z=2) == 2.0
    assert math_nodes.expr("") == 0.0
    for bad in ("__import__('os')", "x.real", "foo(1)", "1 if x else 2", "q", "True", "1 +"):
        with pytest.raises(ExpressionError):
            math_nodes.expr(bad, x=1)


def test_crop_keeps_all_arrays_and_meta() -> None:
    out = spec.crop(_spec(), 1250.0, 1210.0)  # bounds may be swapped
    assert out.wave.tolist() == [1210.0, 1220.0, 1230.0, 1240.0, 1250.0]
    assert out.flux.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert out.error is not None and out.error.shape == (5,)
    assert out.meta == {"src": "t"} and out.frame == "observed"
    assert len(spec.crop(_spec(), 0.0, 1.0)) == 0


def test_to_rest_frame() -> None:
    rest = spec.to_rest_frame(_spec(), z=1.0)
    assert rest.frame == "rest" and rest.z == 1.0
    np.testing.assert_allclose(rest.wave, _spec().wave / 2.0)
    with pytest.raises(ValueError, match="observed-frame"):
        spec.to_rest_frame(rest, z=1.0)


def test_to_velocity_observed_and_rest() -> None:
    s = _spec()
    vel = spec.to_velocity(s, wrest=625.0, z=1.0)  # 625 * 2 = 1250 is the window centre
    assert vel.frame == "velocity" and vel.wave_unit == "km / s" and vel.v0_wrest == 625.0
    assert vel.z == 1.0
    assert abs(vel.wave[5]) < 1e-9
    assert vel.wave[0] < 0 < vel.wave[-1]
    np.testing.assert_allclose(vel.wave[-1], spec.C_KMS * (1300.0 / 1250.0 - 1.0))

    rest = spec.to_rest_frame(s, z=1.0)
    vel_rest = spec.to_velocity(rest, wrest=625.0, z=5.0)  # z ignored for rest-frame input
    np.testing.assert_allclose(vel_rest.wave, vel.wave)
    assert vel_rest.z == 1.0
    with pytest.raises(ValueError, match="already"):
        spec.to_velocity(vel, wrest=625.0)


def test_collect_skips_missing_inputs() -> None:
    s = _spec()
    coll = list_nodes.collect(s, None, s)
    assert len(coll) == 2
    assert list_nodes.collect.spec.inputs[1].required is False
    via_call = list_nodes.collect.call(inputs={"a": s}, ctx=NullContext())
    assert len(via_call) == 1


def test_markdown_note_has_no_ports() -> None:
    assert note.markdown("# hi") is None
    assert note.markdown.spec.outputs == [] and note.markdown.spec.inputs == []
    assert note.markdown.spec.params[0].widget == "markdown"


def test_rbcodes_pack_registers_nodes_and_guards_qt() -> None:
    import sys

    import astro_canvas_rbcodes

    from astro_canvas.sdk import NodeRegistry

    # Only *new* rbcodes imports matter: on Python 3.10 an earlier test may already have
    # imported it deliberately (the parity tests do).
    before = {m for m in sys.modules if m == "rbcodes" or m.startswith("rbcodes.")}
    reg = NodeRegistry()
    astro_canvas_rbcodes.register(reg.for_pack("rbcodes"))
    assert len(reg) == 38 and all(i.startswith("rbcodes.") for i in reg.ids())
    assert "rbcodes" in reg.sample_dirs and "rbcodes" in reg.template_dirs
    assert reg.security["rbcodes"] == "standard"
    assert os.environ["MPLBACKEND"] == "Agg"
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
    after = {m for m in sys.modules if m == "rbcodes" or m.startswith("rbcodes.")}
    assert after == before
