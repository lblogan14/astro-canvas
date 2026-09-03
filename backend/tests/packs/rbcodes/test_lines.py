"""``rbcodes.lines.*``: the 16 bundled line lists and transition lookup."""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_rbcodes.kernels.setline import LINE_LISTS, line_list_path, rb_setline
from astro_canvas_rbcodes.nodes import lines

EXPECTED_COUNTS = {
    "atom": 317,
    "LLS": 109,
    "LLS Small": 19,
    "DLA": 564,
    "LBG": 25,
    "Gal": 95,
    "Eiger_Strong": 24,
    "Gal_Em": 49,
    "Gal_Abs": 10,
    "Gal_long": 57,
    "AGN": 33,
    "HI_recomb": 76,
    "HI_recomb_light": 61,
    "HI": 30,
    "EUV": 816,
    "LLS_EUV": 567,
}


@pytest.mark.parametrize("name", LINE_LISTS)
def test_every_line_list_loads_with_the_expected_row_count(name: str) -> None:
    assert line_list_path(name).is_file()
    out = lines.line_list(name=name)  # type: ignore[arg-type]
    assert len(out) == EXPECTED_COUNTS[name] and out.source == name
    assert np.all(np.isfinite(out.wrest)) and out.wrest.min() > 0
    assert (out.gamma is not None) == (name == "atom")
    assert all(isinstance(str(n), str) and str(n).strip() for n in out.name)


def test_atom_list_carries_oscillator_strengths_and_gammas() -> None:
    atom = lines.line_list(name="atom")
    tr = lines.find_transition(atom, wrest=1215.6701, method="Exact")
    assert tr.name == "HI 1215" and tr.fval == pytest.approx(0.4164) and tr.gamma == 6.265e8
    by_name = lines.find_transition(atom, method="Name", name="MgII 2796")
    assert by_name.wrest == pytest.approx(2796.352) and by_name.fval == pytest.approx(0.6123)
    closest = lines.find_transition(atom, wrest=2800.0, method="closest")
    assert closest.name in ("MgII 2796", "MgII 2803")
    with pytest.raises(ValueError, match="0.001"):
        lines.find_transition(atom, wrest=2800.0, method="Exact")
    with pytest.raises(ValueError, match="no line named"):
        lines.find_transition(atom, method="Name", name="XX 1")
    with pytest.raises(ValueError, match="needs a species name"):
        lines.find_transition(atom, method="Name", name="  ")


def test_recombination_lists_are_converted_to_angstrom() -> None:
    recomb = lines.line_list(name="HI_recomb")
    assert recomb.wrest.min() > 3000  # stored in microns, served in Angstrom
    paschen = lines.find_transition(recomb, wrest=18756.0, method="closest")
    assert "Paschen" in paschen.name


def test_vendored_rb_setline_matches_rbcodes_calling_convention() -> None:
    closest = rb_setline(2796.3, "closest")
    assert closest["name"] == "MgII 2796" and float(closest["wave"]) == pytest.approx(2796.352)
    exact = rb_setline(1215.67, "Exact")
    assert list(exact["name"]) == ["HI 1215"] and exact["wave"].shape == (1,)
    named = rb_setline(0.0, "Name", target_name="HI 1215")
    assert named["wave"][0] == pytest.approx(1215.6701)
    assert rb_setline(1e6, "Exact")["wave"].size == 0
    assert rb_setline(0.0, "Name", target_name="nope")["wave"].size == 0
    lls = rb_setline(1215.67, "closest", linelist="LLS")
    assert "gamma" not in lls and lls["name"].startswith("HI")
    with pytest.raises(ValueError, match="Method must be"):
        rb_setline(1.0, "fuzzy")
    with pytest.raises(ValueError, match="target_name"):
        rb_setline(1.0, "Name")
    with pytest.raises(ValueError, match="Invalid line list"):
        rb_setline(1.0, "closest", linelist="missing")


def test_lookup_helper_resolves_through_setline() -> None:
    tr = lines.lookup(2803.5, "closest", "atom")
    assert tr.name == "MgII 2803" and tr.gamma is not None
