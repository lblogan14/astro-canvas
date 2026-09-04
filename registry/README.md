# Registry seed

`index.json` is the seed for the git-backed node-pack registry (design 9): a single JSON file, no
service, no accounts. The Manager fetches it over HTTPS, caches it for an hour and revalidates
with an `ETag`; publishing a pack is a pull request against it.

The file is duplicated into the wheel as
`backend/src/astro_canvas/manager/builtin_index.json` so the Registry tab is useful on a machine
that has never reached the network. **The two must stay identical** -- a test in
`backend/tests/manager/test_registry_index.py` enforces it, so copy the file when you change it:

```sh
cp registry/index.json backend/src/astro_canvas/manager/builtin_index.json
```

When the registry moves to its own repository (`astro-canvas-registry`), this file becomes its
initial commit and `ASTRO_CANVAS_REGISTRY_URL` (or Manager > Settings) points at the raw URL.

Entry shape and what a reviewer checks: [docs/packs/publishing.md](../docs/packs/publishing.md).
