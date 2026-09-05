# astro-canvas-snr (example pack)

The smallest complete Astro Canvas node pack: one node that wraps
`rbcodes.utils.compute_SNR_1d.estimate_snr`.

It exists so that the code in [the pack authoring tutorial](../../packs/tutorial.md) is *tested*
rather than transcribed — `backend/tests/packs/test_example_pack.py` runs the same assertions as
`tests/test_snr_node.py` on every commit. It is not shipped with the app and it is not a uv
workspace member; copy the folder to start your own pack.

```
snr-pack/
├── pyproject.toml                 # the entry point, the dependencies, the manifest
├── src/astro_canvas_snr/
│   ├── __init__.py                # register(registry)
│   └── nodes.py                   # @node
└── tests/test_snr_node.py         # the schema, and the numbers against rbcodes
```

```sh
uv run --with ./docs/examples/snr-pack astro-canvas serve   # try it without installing it
```
