# astro-canvas-core

Core node pack for Astro Canvas: file IO, math, plotting, astroquery fetch nodes, and the code node.
Phase 01 ships the `astro.*` port types (`astro_canvas_core.types`) and the first nodes:
`core.math.constant`, `core.math.expr`, `core.spec.crop`, `core.spec.to_rest_frame`, `core.spec.to_velocity`,
`core.list.collect`, `core.note.markdown`. Registered through the `astro_canvas.nodes` entry point `core`.

Phase 04 adds the data layer: `core.io.load_spectrum` (astropy parsers for FITS tables, multi-extension and header-axis
files, SDSS/DESI/HSLA products, ASCII/ECSV, rb_spec JSON; rbcodes' `rb_spectrum` readers when that distribution is installed),
`core.io.load_table`, `core.io.load_image`, `core.io.load_cube` (KCWI/MUSE/MaNGA conventions), `core.io.save_spectrum`,
`core.io.save_table`, `core.io.save_json`; `core.spec.rebin`, `core.spec.smooth`, `core.spec.air_to_vac`,
`core.spec.normalize`, `core.spec.snr`; `core.plot.spectrum`, `core.plot.image`, `core.plot.table`, `core.plot.figure_export`;
and the archive nodes `core.fetch.sdss_spectrum`, `core.fetch.simbad_resolve`, `core.fetch.vizier_query`,
`core.fetch.mast_search` (httpx clients cached in `<workspace>/downloads/`, recorded with `respx` in tests). The pack manifest
declares `security = "needs-network"` because of the fetch nodes. Port types gained viewport-aware summaries
(`Spectrum1D.summary(viewport)`, `Image2D`/`Cube3D` tiles with zscale limits, `Table` heads as Arrow).
