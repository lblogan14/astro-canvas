# Migrating from `rb_ifuview`

`rb_ifuview` gives you a cube, an image panel of a collapse, a channel slider, an aperture you
draw with the mouse, and a spectrum panel showing what is inside it. The pieces became nodes; the
drawing became the **aperture editor**, which is the same image panel with the same behaviour.

Open **Workflows ▸ Templates ▸ IFU Cube Explorer ▸ Use**. It loads a synthetic KCWI cube,
collapses it three ways, extracts three apertures and makes moment maps.

## Where each part went

| `rb_ifuview` | Node | Notes |
|---|---|---|
| `io.auto_cube.load_fits` | `core.io.load_cube` | `loader = auto` uses this pack's readers (KCWI sidecars, MUSE, MaNGA, generic); `loader = rbcodes` uses rb_ifuview's own instrument dispatch |
| `cube_collapse.build_whitelight` | `rbcodes.ifu.whitelight` | mean, sum or median over the whole cube or a band |
| `cube_collapse.build_narrowband` | `rbcodes.ifu.narrowband` | the same with a required window |
| `cube_collapse.build_continuum_sub` | `rbcodes.ifu.continuum_sub` | on-band minus one or two continuum windows |
| `IFUCube.crop` | `rbcodes.ifu.subcube` | wavelength and spatial cut, with `CRPIX` shifted to match |
| `aperture_extract.*` and the image panel | `rbcodes.ifu.aperture_extract` + the **aperture editor** | outputs the spectra *and* the apertures |
| `spatial_mask.parse_ds9_regions` / `regions_to_ds9_text` | `rbcodes.ifu.regions_from_ds9` / `regions_to_ds9` | image or sky coordinates |
| `spatial_mask.iau_name` | `rbcodes.ifu.iau_names` | `J100024.0+021200` designations per aperture |
| `moment_maps.moment_map` + `compute_snr_map` | `rbcodes.ifu.moment_maps` | M0/M1/M2 and SNR as one value |
| `moment_maps.compute_snr_map` | `rbcodes.ifu.snr_map` | the SNR alone, as an image |
| the channel slider | the editor's wavelength sliders, and `narrowband`'s window | see below |

## Drawing apertures

The **aperture editor** opens from the pencil-ruler button on an **Aperture Extract** node, and it
is the panel you know:

- the backdrop is the cube's white-light collapse, computed **on the server**; the wavelength
  sliders re-request a narrower band, which is the channel slider's job — hunt for the feature,
  then draw on the same pixel grid;
- drag to draw the selected shape; drag near an aperture's centre to move it, near its edge to
  resize it;
- the panel underneath is the extracted spectrum of the selected aperture, and it is *the node's
  own extraction* rather than a re-implementation — the editor asks the server to run this node
  with the candidate apertures, so the preview and the graph agree by construction.

**The sky annulus is a role, not a convention.** Every aperture is `source` or `background`;
`aperture_extract`'s `background` parameter (`mean`/`median`) subtracts the background apertures'
level from every source spectrum. Tick **Draw as background** or use a row's own toggle. In
`rb_ifuview` the annulus was the sky by agreement; here it says so.

**Masks are identical.** A pixel belongs to an aperture when its *centre* is inside it, so a mask
built here and one built by `make_circular_mask` agree element for element. Circles, annuli, boxes
and polygons all round the same way.

## Your `.reg` files still work

**Import .reg** in the editor reads a ds9 file in image coordinates. Sky files need the full WCS,
which only the server has — for those, use the **Regions from ds9** node with a collapse wired
into its `reference` input. **Export .reg** writes exactly what `regions_to_ds9` writes, in image
or sky frame, and the editor's own export downloads the same bytes.

## Moment maps

Same computation, one node: a per-spaxel linear continuum through the two continuum windows is
fitted and removed, then the line window is integrated into **M0** (flux), **M1** (velocity
centroid, km/s from `lambda_rest`), **M2** (dispersion, km/s) and **SNR**. They agree with
rbcodes' `moment_map` to 1e-10, and on a synthetic cube with a known velocity field the maps
recover it to well under 1 km/s wherever the line is bright.

M1 and M2 are NaN where M0 ≤ 0, and below `snr_min` where you set one. The four maps draw side by
side with velocities on a diverging colour map, each with its own limits — an integrated flux and
a velocity do not share a range.

## Cubes stay on disk

This is the part `rb_ifuview` could not do. A cached cube is **memory-mapped** out of the
content-addressed store rather than copied into the heap: `flux` and `var` are their own
uncompressed `.npy` parts inside the packed blob, and reading one back maps those parts. On a
97 MB cube that is 19 ms instead of 253 ms, and the memory cache is charged 4 KiB for the handle
instead of 194 MB for the arrays.

Previews are bounded the same way: a thumbnail reads a strided sample capped at 32 MB, so
collapsing a 500 MB cube for the inline preview costs what collapsing a 50 MB one costs. Details
in [memory-mapping cubes](../dev/cube-memory.md) and the measured numbers in
[performance](../dev/performance.md#an-ifu-cube).

## What you gain

**The analysis is a document.** Which cube, which windows, which apertures, which moment
parameters: one `workflow.json`. Re-open it and it re-runs; export the `.acw` and it carries the
cube's hash.

**Twelve cubes.** Promote the cube path and switch to Batch mode: one row per pointing, the
apertures' fluxes as collected columns. `astro-canvas run` does it headless on a cluster node.

**The spectra are data.** `aperture_extract` outputs a `SpectrumCollection`, so extracted spectra
go straight into the absorption-line measurement or the multi-spectrum viewer. In `rb_ifuview`
they were a panel.

## What is different

**No pyds9 bridge.** Region files work in both directions; the live ds9 connection did not make
v0.1. SAMP (TOPCAT/Aladin) is on the v0.2 list.

**No alignment dialog.** `rb_ifuview`'s WCS alignment of two cubes is v0.2, along with `rb_align`.

**The aperture editor does not pan or zoom its image.** The SVG overlay owns the pointer so that
dragging draws rather than pans. Use the wavelength sliders to change what you are looking at, or
the full-size viewer (read-only) to inspect the collapse. This is a known rough edge, on the v0.2
list.

**A node with a file side effect does not rewrite its file on a cache hit.** If you delete
`outputs/apertures.reg` and re-run without changing anything, the export node is a cache hit and
does not write it again. Change a parameter, or delete the node's cached output, to force it.
