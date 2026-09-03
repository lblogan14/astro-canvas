# Memory-mapping cubes out of the blob store

*Phase 08.* An IFU cube is the first port value that does not comfortably fit in memory: a 500 MB
KCWI cube would otherwise be copied at least three times — once by the FITS reader, once into the
packed blob, once again on every cache hit. This note describes how the engine avoids the last of
those and how to reason about the rest.

## Mappable blob parts

A packed blob is a **`ZIP_STORED`** zip: a manifest plus named parts, none of them compressed. A
part that holds a single array in `.npy` format therefore sits in the file as a short header
followed by raw, contiguous, correctly aligned bytes — which is exactly what `numpy.memmap` wants.

A port type opts in by listing field names:

```python
@port_type(id="astro.Cube3D", ...)
class Cube3D(PortType):
    __mmap_fields__ = ("flux", "var")
```

`PortType.to_blob` then moves any of those arrays that is at least `mmap_min_bytes()` large out of
the shared `arrays.npz` into its own `<field>.npy` part and records the mapping in the manifest:

```json
{"type": "astro.Cube3D", "data": {...}, "mmap": {"flux": "flux.npy", "var": "var.npy"}}
```

`PortType.from_blob` reads such a blob back the ordinary way (a copy). `PortType.from_blob_file`
takes the *path* instead and, for every mapped part, locates the member's data offset by parsing
the zip local header (`memmap.stored_part_offset`), reads the `.npy` header from there and returns
a read-only `numpy.memmap` over the remaining bytes. Anything it cannot map — a compressed member,
a Fortran-ordered array, a type with no `__mmap_fields__` — falls back to `from_blob`, so the
behaviour is identical and only the memory profile changes.

Both readers of the cache use the file-aware path: `OutputCache.load` (the scheduler) and
`worker.rehydrate` (the process pool).

## Accounting

`value_nbytes` charges a memory-mapped array `MMAP_HANDLE_BYTES` (4 KiB) rather than its size, so
a mapped cube does not evict everything else from the LRU. It is still *in* the LRU: what is kept
is the handle, and the pages behind it are the OS's to reclaim.

`ASTRO_CANVAS_MMAP_MIN_MB` (`Settings.mmap_min_mb`, default 8 MB) sets the threshold. The server
and the headless runner publish it to the SDK as `ASTRO_CANVAS_MMAP_MIN_BYTES`, which worker
processes inherit. Setting it to `0` disables the split entirely, which is what the golden fixtures
and the small-array tests rely on.

## Bounded summaries

Mapping solves the *cache* copy but not the *preview* copy: `np.nansum(flux, axis=(1, 2))` over a
mapped cube still faults in every page. `Cube3D` therefore samples:

- `Cube3D.integrated(max_bytes)` sums in wavelength chunks over spatially strided rows and rescales
  by the stride, so the curve keeps its shape and amplitude.
- `Cube3D.white_light(lo, hi, max_bytes)` strides the *channels* it averages.
- `Cube3D.summary()` passes `SUMMARY_BYTES` (32 MB) to both, so a preview reads a bounded slice
  however large the cube is. `tests/engine/test_cube_memory.py` asserts this with `tracemalloc`,
  which sees numpy's allocations (`np.lib.tracemalloc_domain`) but not mapped pages — precisely the
  quantity the rule is about.

A node that needs the real numbers (a collapse, an extraction, a moment map) does *not* pass
`max_bytes`: it reads what it needs, and reading a mapped array is a page fault, not a copy.

## What is still copied

- **Writing.** `to_blob` builds the `.npy` bytes in memory and `Blob.pack()` copies them again into
  the zip, so caching a cube briefly costs about twice its size. A streaming writer is the obvious
  follow-up (see `handoffs/BACKLOG.md`).
- **Reading FITS.** `astropy.io.fits` is opened with `memmap=False` and the data is cast to float32,
  so loading a cube costs its size once, plus the source dtype's while converting.
- **Process pool.** Only blob *references* cross the boundary, and the worker maps them the same
  way, so an expensive node on a cube does not serialize it.
