"""Port of ``rbcodes.GUIs.zfind.linelists``: the five curated presets of ``rb_zfind``.

Each line carries a vacuum rest wavelength (Angstrom), a label, a relative weight and a type
(``emission`` or ``absorption``). Absorption weights are oscillator strengths from
``atom_full.dat``; emission weights follow rbcodes' empirical 1-3 scale anchored on H-alpha = 3.
rbcodes hands these out as pandas DataFrames; here they are parallel numpy arrays so the pack
does not depend on pandas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

CuratedName = Literal["zfind_em", "zfind_stellar", "zfind_igm", "zfind_galaxy", "zfind_qso"]

LineKind = Literal["emission", "absorption"]

_Row = tuple[float, str, float, str]

# (wave, name, weight, type) exactly as in rbcodes 2.4.0 ``linelists.py``.
_EM_LINES: tuple[_Row, ...] = (
    (1216.00, "Lya 1216", 1.8, "emission"),
    (1908.73, "CIII] 1909", 1.0, "emission"),
    (3727.09, "[OII] 3727", 2.0, "emission"),
    (3729.87, "[OII] 3729", 2.0, "emission"),
    (4341.69, "Hgamma", 0.2, "emission"),
    (4862.68, "Hbeta", 0.5, "emission"),
    (4960.30, "[OIII] 4960", 1.0, "emission"),
    (5008.24, "[OIII] 5007", 3.0, "emission"),
    (6564.61, "Halpha", 3.0, "emission"),
    (6585.28, "[NII] 6583", 1.0, "emission"),
)

_STELLAR_LINES: tuple[_Row, ...] = (
    (2796.35, "MgII 2796", 0.612, "absorption"),
    (2803.53, "MgII 2803", 0.305, "absorption"),
    (3934.78, "CaII K", 0.635, "absorption"),
    (3969.59, "CaII H", 0.315, "absorption"),
    (4305.61, "G-band", 0.300, "absorption"),
    (5175.00, "MgI b", 0.300, "absorption"),
    (5891.58, "NaI D1", 0.631, "absorption"),
    (5897.56, "NaI D2", 0.318, "absorption"),
)

_IGM_LINES: tuple[_Row, ...] = (
    (1031.93, "OVI 1031", 0.133, "absorption"),
    (1037.62, "OVI 1037", 0.066, "absorption"),
    (1215.67, "HI Lya", 0.416, "absorption"),
    (1260.42, "SiII 1260", 1.007, "absorption"),
    (1334.53, "CII 1334", 0.128, "absorption"),
    (1393.76, "SiIV 1393", 0.514, "absorption"),
    (1402.77, "SiIV 1402", 0.255, "absorption"),
    (1548.20, "CIV 1548", 0.191, "absorption"),
    (1550.78, "CIV 1550", 0.095, "absorption"),
    (2796.35, "MgII 2796", 0.612, "absorption"),
    (2803.53, "MgII 2803", 0.305, "absorption"),
)

_GALAXY_LINES: tuple[_Row, ...] = (
    (3727.09, "[OII] 3727", 2.0, "emission"),
    (3729.87, "[OII] 3729", 2.0, "emission"),
    (4341.69, "Hgamma", 0.2, "emission"),
    (4862.68, "Hbeta", 0.5, "emission"),
    (4960.30, "[OIII] 4960", 1.0, "emission"),
    (5008.24, "[OIII] 5007", 3.0, "emission"),
    (6564.61, "Halpha", 3.0, "emission"),
    (6585.28, "[NII] 6583", 1.0, "emission"),
    (3934.78, "CaII K", 0.635, "absorption"),
    (3969.59, "CaII H", 0.315, "absorption"),
    (4305.61, "G-band", 0.300, "absorption"),
    (5175.00, "MgI b", 0.300, "absorption"),
    (5891.58, "NaI D1", 0.631, "absorption"),
    (5897.56, "NaI D2", 0.318, "absorption"),
)

_QSO_LINES: tuple[_Row, ...] = (
    (1216.00, "Lya 1216", 3.0, "emission"),
    (1548.20, "CIV 1548", 3.0, "emission"),
    (1550.78, "CIV 1550", 1.5, "emission"),
    (1908.73, "CIII] 1909", 2.0, "emission"),
    (2799.00, "MgII 2799", 2.0, "emission"),
    (4862.68, "Hbeta", 0.5, "emission"),
    (4960.30, "[OIII] 4960", 0.5, "emission"),
    (5008.24, "[OIII] 5007", 1.5, "emission"),
)

_REGISTRY: dict[str, tuple[_Row, ...]] = {
    "zfind_em": _EM_LINES,
    "zfind_stellar": _STELLAR_LINES,
    "zfind_igm": _IGM_LINES,
    "zfind_galaxy": _GALAXY_LINES,
    "zfind_qso": _QSO_LINES,
}

CURATED_NAMES: tuple[str, ...] = tuple(_REGISTRY)


@dataclass(frozen=True)
class LineTable:
    """A line list as the zfind kernels consume it (rbcodes passes a DataFrame with ``attrs``)."""

    wave: npt.NDArray[np.float64]
    name: npt.NDArray[np.str_]
    weight: npt.NDArray[np.float64]
    kind: npt.NDArray[np.str_]
    label: str = "custom"

    def __post_init__(self) -> None:
        n = self.wave.shape[0]
        if not (self.name.shape[0] == self.weight.shape[0] == self.kind.shape[0] == n):
            raise ValueError("LineTable columns must have the same length")

    def __len__(self) -> int:
        return int(self.wave.shape[0])

    @classmethod
    def build(
        cls,
        wave: npt.ArrayLike,
        name: npt.ArrayLike,
        weight: npt.ArrayLike | None = None,
        kind: npt.ArrayLike | str | None = None,
        label: str = "custom",
    ) -> LineTable:
        """Assemble a table; ``weight`` defaults to 1 and ``kind`` to ``emission`` like rbcodes."""
        w = np.asarray(wave, dtype=np.float64).ravel()
        n = np.asarray(name, dtype=np.str_).ravel()
        wt = np.ones_like(w) if weight is None else np.asarray(weight, dtype=np.float64).ravel()
        if kind is None or isinstance(kind, str):
            # ``np.full(..., dtype=np.str_)`` would allocate one-character strings.
            kd = np.array([kind or "emission"] * w.shape[0], dtype=np.str_)
        else:
            kd = np.asarray(kind, dtype=np.str_).ravel()
        return cls(wave=w, name=n, weight=wt, kind=kd, label=label)


def curated(name: str) -> LineTable:
    """The named preset (``get_curated_df`` in rbcodes)."""
    if name not in _REGISTRY:
        raise KeyError(f"{name!r} is not a curated preset. Available: {list(CURATED_NAMES)}")
    rows = _REGISTRY[name]
    return LineTable(
        wave=np.array([r[0] for r in rows], dtype=np.float64),
        name=np.array([r[1] for r in rows], dtype=np.str_),
        weight=np.array([r[2] for r in rows], dtype=np.float64),
        kind=np.array([r[3] for r in rows], dtype=np.str_),
        label=name,
    )


__all__ = ["CURATED_NAMES", "CuratedName", "LineKind", "LineTable", "curated"]
