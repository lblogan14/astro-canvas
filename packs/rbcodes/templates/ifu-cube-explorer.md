# IFU Cube Explorer

The rbcodes `rb_ifuview` flows as an Astro Canvas workflow: collapse a cube into images, draw
apertures on one of them and extract spectra, and measure the kinematics of an emission line as
moment maps — with every step a node you can re-run, re-wire and cache.

The bundled cube is synthetic (`sample_data/make_cube.py`, seed 1908): 160 × 40 × 36 spaxels of a
rotating disc with a **linear ±120 km/s velocity gradient** across the field, a companion clump
offset to **+180 km/s**, [O III] 5007 at 1 Å per channel on a flat continuum, and a variance
sidecar following the KCWI `_vcubes` naming. Because its velocity field is analytic, the moment
maps have something to be right about.

| Step | Node | What it gives you |
|---|---|---|
| Load | `core.io.load_cube` | KCWI / MUSE / MaNGA / generic FITS; `loader = rbcodes` uses rb_ifuview's own dispatch |
| Collapse | `rbcodes.ifu.whitelight`, `narrowband`, `continuum_sub` | images with the cube's spatial WCS |
| Extract | `rbcodes.ifu.aperture_extract` | one spectrum per aperture — **aperture editor** |
| Name | `rbcodes.ifu.iau_names` | `J100024.0+021200` designations from the aperture centres |
| Export | `rbcodes.ifu.regions_to_ds9` | a ds9 `.reg` file in image or sky coordinates |
| Measure | `rbcodes.ifu.moment_maps`, `snr_map` | M0 / M1 / M2 in km/s plus the per-spaxel SNR |
| Cut | `rbcodes.ifu.subcube` | a smaller cube (wavelength and spatial box) with its WCS shifted |

## The aperture editor

`Aperture Extract` is an *interactive* node, like the multi-spectrum viewer: the apertures live in
its `regions` parameter, so what you draw is what the graph runs, and they leave again as a
`Region2D` output that the naming and export nodes consume.

- Pick a shape — **circle**, **box**, **annulus** or **polygon** — and drag on the image.
- Drag an existing aperture near its centre to **move** it, near its edge to **resize** it.
- Tick **Draw as background** before drawing (or the checkbox on a row afterwards) to mark an
  aperture as background: those are not extracted, they estimate the level the `background`
  parameter subtracts from every source spectrum.
- The wavelength sliders re-collapse the backdrop on the server, so you can hunt for a feature in
  a narrow band and still draw on the same pixels.
- **Import .reg** reads a ds9 file in image coordinates; sky-coordinate files need the WCS, so use
  the `Regions from ds9` node with a collapse wired into its `reference` input.
- The panel underneath shows the spectrum of the selected aperture, extracted by the node itself
  (the editor asks the server to run it with the candidate apertures), so what you see while
  dragging is what the graph will produce.

Apply writes the apertures back to the node; the node fills in each one's sky coordinates from the
cube's WCS, so a `.reg` export in `fk5`/`icrs` works even though you drew in pixels.

## Moment maps

`Moment Maps` computes, over the line window and after removing a per-spaxel linear continuum
fitted through the two continuum windows:

- **M0** — integrated line flux (flux × Å),
- **M1** — flux-weighted velocity centroid in km/s relative to `lambda_rest`,
- **M2** — flux-weighted velocity dispersion in km/s,
- **SNR** — M0 divided by the noise, from the variance cube when there is one and from the scatter
  in the continuum windows otherwise.

M1 and M2 are blanked where M0 ≤ 0 and, with `snr_min` set, below that signal-to-noise; the preview
draws the three maps side by side with velocities on a diverging colour map. On this cube M1
recovers the input gradient to well under a km/s wherever the line is bright.

## Memory

Cubes are not copied into the server's heap: a cached cube is memory-mapped straight out of the
content-addressed blob store, and previewing one reads only a strided sample of it. A 500 MB cube
costs page cache, not RSS — see `docs/dev/cube-memory.md`.
