# astro-canvas-core

Core node pack for Astro Canvas: file IO, math, plotting, astroquery fetch nodes, and the code node.
Phase 01 ships the `astro.*` port types (`astro_canvas_core.types`) and the first nodes:
`core.math.constant`, `core.math.expr`, `core.spec.crop`, `core.spec.to_rest_frame`, `core.spec.to_velocity`,
`core.list.collect`, `core.note.markdown`. Registered through the `astro_canvas.nodes` entry point `core`.
