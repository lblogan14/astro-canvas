# IFU cubes: collapses, apertures and moment maps (phase 08)

The rbcodes pack turns `rb_ifuview` into canvas nodes: a cube becomes images, apertures drawn on
one of those images become spectra, and an emission line becomes moment maps. Everything calls
`rbcodes.GUIs.ifuviewer.processing` when rbcodes is installed and the vendored ports
(`kernels/ifu.py`) otherwise, and `meta["rbcodes"]`/`header["_RBCODES"]` records which backend ran.

## Start from the template

Open the **Workflows** panel, expand **Templates** and press **Use** on *IFU Cube Explorer*. It
loads a bundled synthetic KCWI-style cube — a rotating disc with a ±120 km/s velocity gradient, a
companion clump at +180 km/s and [O III] 5007 on a flat continuum — and wires up every node below.
Details are in `packs/rbcodes/templates/ifu-cube-explorer.md`.

| Node | rbcodes | Notes |
|---|---|---|
| `core.io.load_cube` | `io.auto_cube.load_fits` | `loader = auto` uses this pack's readers (KCWI sidecars, MUSE, MaNGA, generic); `rbcodes` uses rb_ifuview's own instrument dispatch |
| `rbcodes.ifu.whitelight` | `cube_collapse.build_whitelight` | mean/sum/median over the whole cube or a band |
| `rbcodes.ifu.narrowband` | `cube_collapse.build_narrowband` | the same with a required window |
| `rbcodes.ifu.continuum_sub` | `cube_collapse.build_continuum_sub` | on-band minus one or two continuum windows |
| `rbcodes.ifu.subcube` | `IFUCube.crop` | wavelength and spatial cut with `CRPIX` shifted to match |
| `rbcodes.ifu.aperture_extract` | `aperture_extract.*` | interactive: **aperture editor**; outputs the spectra *and* the apertures |
| `rbcodes.ifu.regions_from_ds9` / `regions_to_ds9` | `spatial_mask.parse_ds9_regions` / `regions_to_ds9_text` | image or sky coordinates |
| `rbcodes.ifu.iau_names` | `spatial_mask.iau_name` | `J100024.0+021200` designations per aperture |
| `rbcodes.ifu.moment_maps` | `moment_maps.moment_map` + `compute_snr_map` | M0/M1/M2 and SNR as one `rbcodes.MomentMaps` value |
| `rbcodes.ifu.snr_map` | `moment_maps.compute_snr_map` | the SNR alone, as an image |

## Apertures

`astro.Region2D` holds a list of apertures, each in **pixel** coordinates (0-based) and — once a
node with a WCS has seen them — **sky** coordinates (degrees, sizes in arcseconds):

| Shape | `pixel` | `sky` |
|---|---|---|
| `circle` | `[cx, cy, r]` | `[ra, dec, r″]` |
| `annulus` | `[cx, cy, r_in, r_out]` | `[ra, dec, r_in″, r_out″]` |
| `box` | `[cx, cy, width, height, angle°]` | `[ra, dec, w″, h″, angle°]` |
| `polygon` | `[x1, y1, x2, y2, …]` | `[ra1, dec1, …]` |

Each aperture has a **role**: `source` apertures are extracted, `background` apertures estimate the
level that `aperture_extract`'s `background` parameter (`mean`/`median`) subtracts from every
source spectrum — rb_ifuview's sky annulus, as a first-class field.

Masks follow rbcodes exactly: a pixel belongs to an aperture when its *centre* is inside it, so a
mask built here and one built by `make_circular_mask` agree element for element.

## The aperture editor

`Aperture Extract` declares `editor="aperture-editor"`. Like the multi-spectrum viewer, it is an
*interactive* node: the apertures live in its `regions` parameter, an optional `region_seed` input
fills them in while that parameter is empty, and Apply is a single parameter write.

- The backdrop is the cube's white-light collapse, computed **on the server**; the wavelength
  sliders re-request it for a narrower band, so you can hunt for a feature and still draw on the
  same pixel grid.
- Drag on the image to draw the selected shape; drag an existing aperture near its centre to move
  it, near its edge to resize it. **Draw as background** marks new apertures as background, and
  each row has its own toggle.
- **Import .reg** reads a ds9 file in image coordinates. Sky files need the full WCS, which only
  the server has: use the `Regions from ds9` node with a collapse wired into `reference`.
  **Export .reg** downloads exactly what `regions_to_ds9` would write.
- The panel underneath is the extracted spectrum of the selected aperture. The editor does not
  re-implement extraction: it asks the server to run *this node* with the candidate apertures
  (`preview.compute` with `node_id`), so the preview and the graph agree by construction.

## Moment maps

`Moment Maps` fits and removes a per-spaxel linear continuum through the two continuum windows
(`subtract_linear_continuum`), then integrates over the line window:

- **M0** — integrated line flux,
- **M1** — flux-weighted velocity centroid, km/s relative to `lambda_rest`,
- **M2** — flux-weighted velocity dispersion, km/s,
- **SNR** — M0 over the noise, from the variance cube when the file has one, and from the scatter
  in the continuum windows otherwise.

M1 and M2 are NaN where M0 ≤ 0 and, with `snr_min` set, below that threshold. The `moment-thumbs`
preview draws the maps side by side, velocities on a diverging colour map, each with its own
display limits (an integrated flux and a velocity do not share a range).

On a synthetic cube with a known velocity field the maps reproduce it to well under 1 km/s wherever
the line is bright, and they agree with rbcodes' own `moment_map` to 1e-10.

## Memory

Cubes are big, so they are never copied into the server's heap when they can be referenced instead:

- `astro.Cube3D` writes `flux` and `var` as their own uncompressed `.npy` parts of the packed blob,
  and reading a cached cube back memory-maps those parts straight out of the content-addressed
  store (`PortType.from_blob_file`). The memory cache charges a mapped array the cost of its
  handle, not its size.
- `Cube3D.summary()` never reads the whole array: the white-light thumbnail and the integrated
  spectrum come from an evenly strided sample capped at 32 MB, so previewing a 500 MB cube costs
  the same as previewing a small one.
- `ASTRO_CANVAS_MMAP_MIN_MB` (default 8) is the size above which an array gets its own mappable
  part; `0` disables the split.

See `docs/dev/cube-memory.md` for how the mapping works and what it costs.
