# Performance: what is measured, and what it measures

*Phase 13.* The success criteria in the design (§1.6) are numbers, so they are gates in the test
suite rather than claims in a document. Two suites hold them:

| | Command | What it covers |
|---|---|---|
| Browser | `task test:e2e:perf` | frame rate while panning and zooming, the latency of an edit, opening a large document |
| Server | `uv run --directory backend pytest -m perf` | the engine at 500 nodes, the million-point spectrum path, the cube path, a 200-row batch soak |

Both are excluded from the default test run — a wall-clock threshold on a machine that is also
running four browsers is not a unit test — and both run in the nightly workflow
([`nightly.yml`](https://github.com/lblogan14/astro-canvas/blob/main/.github/workflows/nightly.yml)),
which keeps `frontend/perf-report.json` and `backend/perf-report.json` as artefacts. Every gate
prints its number, so a run tells you how much headroom there is and not just pass or fail.

## The numbers

Recorded on the development machine: Windows 11, 24 logical CPUs, Python 3.12.13, headless
Chromium. **These are one machine's figures**, kept here so a change that halves something is
visible; the gates are what CI enforces.

### Canvas

| Measurement | Value | Gate |
|---|---|---|
| Pan and zoom over 500 nodes | **56.2 fps** | ≥ 55 fps (design), ≥ 40 fps (asserted) |
| The same interaction over 20 nodes (the ceiling) | 60.3 fps | — |
| Fraction of the ceiling | 0.93 | ≥ 0.9 |
| Open a 500-node document, cold cache | 1.45 s | < 8 s |
| Fit 500 nodes into the viewport | 0.20 s | — |

Headless Chromium schedules `requestAnimationFrame` against a 60 Hz clock, so **60 fps is the
ceiling** and the design's 55 leaves under two frames of margin — which would make the gate a
coin toss on a throttled runner rather than a statement about the canvas. The same interaction is
therefore measured on a twenty-node document first, and what the test asserts is that the big
graph reaches 90 % of *that*, plus an absolute floor of 40 fps.

Even that turned out to be a statement about the machine: on a shared CI runner (four vCPUs, a
neighbour on the other four) the same interaction measured 0.74, 0.76 and 0.89 of its own ceiling
across three nightlies — 43.8 fps against a 59.6 fps ceiling on the last one — because the
browser rather than the canvas is the bottleneck there. The two gates are therefore much looser
under `CI`, ≥ 0.6 of the ceiling and ≥ 25 fps: at twice the cost the fraction would be around 0.5
and the frame rate around 28, so they still catch the regression they are for, and the number in
`perf-report.json` is what a drift is read from. Run the perf project on a machine you control if
you want the tight figures.

At 500 nodes the canvas drops about one frame in sixteen; the remaining cost is Vue Flow's
transform and the visible nodes' re-render, not the 500 in the document (nodes below zoom 0.4
draw LOD placeholders and only visible ones are mounted at all).

### Editing latency

| Measurement | Value | Gate |
|---|---|---|
| Cheap re-run latency, debounces excluded | **35 ms** | < 300 ms |
| Keystroke to a new value on the canvas | 835 ms | — |
| Engine re-run after a leaf edit, 500 nodes | 70 ms | < 300 ms |
| Engine re-run after a root edit, 500 nodes | 48 ms | < 1000 ms |
| `scheduler.update` (compile + 500 cache keys) | 10 ms | < 400 ms |
| Compile a 500-node document | 4 ms | < 250 ms |
| Status snapshot of 500 nodes | 0.5 ms | < 100 ms |

The design's "< 300 ms cheap re-run" is the engine and the transport, and that is what the gate
measures — on the WebSocket, from the `node.status` that says a node went dirty to the one that
says it is done, minus the scheduler's debounce.

The **end-to-end** number is larger because two debounces sit in front of the run, both of them
deliberate:

1. the store collects a burst of edits for **250 ms** before it PUTs the document (it was 1000 ms
   until phase 13, which made a single edit feel like a second and a half);
2. the scheduler then waits its own **250 ms** (`ASTRO_CANVAS_DEBOUNCE_MS`) before auto-running,
   which is what stops a slider drag from queueing a run per pixel.

So about 500 ms of the 835 is waiting on purpose, and the rest is the round trip plus Playwright's
own polling. Collapsing the two into one window — the client already coalesced, so the server's
need not be a second full one — is the obvious v0.2 improvement and is in the backlog. Setting
`ASTRO_CANVAS_DEBOUNCE_MS=0` removes the server half today.

### A million-point spectrum

| Measurement | Value | Gate |
|---|---|---|
| `summary()` to 4000 points (node thumbnail) | **9.5 ms** | < 120 ms |
| `summary()` to 20000 points (viewer) | 12.8 ms | < 200 ms |
| `summary()` zoomed to 1 % of the range | 4.3 ms | < 200 ms |
| `to_blob` + pack (3 × 1e6 float64) | 55 ms | < 400 ms |
| `from_blob_file` | 45 ms | < 400 ms |
| `output_frame` (the full arrays as one binary frame) | 11 ms | < 300 ms |
| Blob and frame size | 24 MB each | — |

Nothing on this path is linear in the *rendered* points: the preview is a MinMaxLTTB decimation
to a fixed budget (`tsdownsample`), and zooming in costs less than the whole range because fewer
samples reach the picker. The full array never travels as JSON — a binary frame is the raw
buffers plus a msgpack header, so it is exactly as large as the arrays.

### An IFU cube

Measured on a 3800 × 80 × 80 float32 cube: 97 MB of flux and the same again of variance, which is
a KCWI pointing rather than the 900 KB cube the samples ship.

| Measurement | Value | Gate |
|---|---|---|
| White light over every channel | **115 ms** (805 MB/s) | < 2 s |
| `Cube3D.summary` (white light + integrated spectrum, capped) | 88 ms | < 400 ms |
| White light capped to the summary budget | 30 ms | < 300 ms |
| Integrated spectrum capped to the summary budget | 56 ms | < 300 ms |
| `to_blob` + pack (194 MB) | 436 ms (426 MB/s) | < 6 s |
| `from_blob_file`, memory-mapped | 19 ms | < 500 ms |
| `from_blob_file` with mapping disabled | 253 ms | — |

The design's white-light target is two seconds. At 805 MB/s the 500 MB cube of
[cube-memory.md](cube-memory.md) collapses in about 0.6 s, so the gate holds with room; the
sampled preview (`SUMMARY_BYTES`, 32 MB) does not depend on the cube's size at all, which is the
number that must not grow. Reading a cached cube back is 13× cheaper mapped than copied, and the
mapped handle is charged 4 KiB to the memory LRU rather than 194 MB.

### Memory

| Measurement | Value | Gate |
|---|---|---|
| Batch of 200 rows | 1.24 s | < 120 s |
| RSS while holding 200 rows of results | +0.2 MB | — |
| RSS after the batch is dropped | +0.2 MB | < 64 MB |
| RSS for a second open document | +0.0 MB | — |

Two things in the server are unbounded by construction, so they are checked rather than argued
about. `BatchRunner` keeps the last 20 batches' rows in memory: a 200-row batch of scalar results
costs a fraction of a megabyte, and dropping the run gives it back. A second open document adds
nothing measurable, because both schedulers share the process-wide `OutputCache` and executors.

The one that is *not* bounded is `RuntimePool` on a `--auth users` server: it builds an
`EngineRuntime` per account on first request and never evicts it, so a lab server is sized by its
concurrent users (each carries a cache, a thread pool and, once an expensive node has run, a
process pool). An idle timeout is the v0.2 fix; until then,
[`docs/deploy/server.md`](../deploy/server.md) says to size for concurrent users.

## Running them

```sh
task test:e2e:perf                                  # browser gates, alone on the machine
uv run --directory backend pytest -m perf -q --no-cov   # server gates
```

The browser gates need a built SPA (`task test:e2e:perf` builds it). They run with a single
Playwright worker on purpose: a frame-rate measurement taken while three other browsers compete
for the CPU is not a measurement of the canvas.

## Adding a gate

Both suites record through a one-line helper, so a new number shows up in the report and in the
log without any wiring:

```python
# backend/tests/perf/test_something.py
pytestmark = pytest.mark.perf

def test_it_is_quick(perf: Perf) -> None:
    with perf.timed("what this measures", gate=250.0) as t:
        do_the_thing()
    assert t.elapsed < 250.0
```

```ts
// frontend/e2e/perf-something.spec.ts  (the `perf` project matches perf-*.spec.ts)
import { record } from './perf'
record('what this measures', value, 'ms', 300)
```

Prefer a gate with real headroom and a recorded number over a tight gate: the number is what
catches a regression, and a gate that fails on a busy runner gets ignored.
