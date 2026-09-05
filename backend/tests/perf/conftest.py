"""Measurement recording for the performance gates.

Every gate reports its number as well as passing or failing, and the session writes them to
``backend/perf-report.json`` — the nightly workflow keeps that as an artefact and
``docs/dev/performance.md`` quotes the figures. Run them with ``pytest -m perf``; the default
suite excludes them, because a wall-clock threshold on a shared runner is not a unit test.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# The engine gates want the same scheduler harness the engine tests use; re-exporting the
# fixture is how pytest shares one across directories.
from tests.engine.conftest import harness  # noqa: F401

REPORT = Path(__file__).resolve().parents[2] / "perf-report.json"


@dataclass
class Perf:
    """Collects ``(name, value, unit, gate)`` rows for one session."""

    rows: list[dict[str, object]] = field(default_factory=list)

    def record(
        self, name: str, value: float, unit: str, *, gate: float | None = None, note: str = ""
    ) -> float:
        row: dict[str, object] = {"name": name, "value": round(value, 3), "unit": unit}
        if gate is not None:
            row["gate"] = gate
        if note:
            row["note"] = note
        self.rows.append(row)
        print(f"PERF {name}: {value:.3f} {unit}" + (f" (gate {gate} {unit})" if gate else ""))
        return value

    def timed(self, name: str, unit: str = "ms", *, gate: float | None = None) -> _Timer:
        return _Timer(self, name, unit, gate)


class _Timer:
    def __init__(self, perf: Perf, name: str, unit: str, gate: float | None) -> None:
        self.perf, self.name, self.unit, self.gate = perf, name, unit, gate
        self.elapsed = 0.0

    def __enter__(self) -> _Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = (time.perf_counter() - self._start) * 1000
        if exc[0] is None:
            self.perf.record(self.name, self.elapsed, self.unit, gate=self.gate)


@pytest.fixture(scope="session")
def perf() -> Iterator[Perf]:
    collector = Perf()
    yield collector
    REPORT.write_text(
        json.dumps(
            {
                "recorded": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "platform": f"{platform.system()} {platform.machine()}",
                "python": sys.version.split()[0],
                "cpus": os.cpu_count(),
                "measurements": collector.rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nperf report written to {REPORT}")
