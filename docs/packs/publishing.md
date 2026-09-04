# Publishing a node pack

A node pack is an ordinary Python distribution. Publishing one is two independent steps: put the
distribution somewhere installable, and (optionally) list it in the registry so it shows up in
**Manager ▸ Registry** with an install button.

Nothing about Astro Canvas requires the second step — a user with the `standard` security level
can install any PyPI name, and one with `permissive` can install a git URL. The registry is for
discovery.

## 1. The distribution

The contract is [the node schema](../formats/node-schema.md); the manifest looks like this:

```toml
# pyproject.toml
[project]
name = "astro-canvas-yourpack"
version = "0.1.0"
requires-python = ">=3.10,<3.14"
dependencies = ["astro-canvas-sdk>=0.1,<0.2", "numpy>=1.26", "astropy>=6"]

[project.entry-points."astro_canvas.nodes"]
yourpack = "astro_canvas_yourpack:register"     # def register(registry) -> None

[tool.astro-canvas]
display_name = "Your pack — what it is for"
publisher = "your-github-handle"
requires_astro_canvas = ">=0.1,<0.2"
categories = ["Spectra", "Photometry"]
templates_dir = "templates"                      # optional: shipped .acw templates
sample_data_dir = "sample_data"                  # optional: copied into <workspace>/samples/
security = "standard"                            # standard | needs-network | runs-subprocess
```

Three rules that matter more than they look:

- **Depend on `astro-canvas-sdk`, never on `astro-canvas`.** The SDK is deliberately tiny
  (pydantic, numpy, griffe, tsdownsample). A pack that depends on the app cannot be installed
  into the app.
- **Pin loosely.** A pack pinning `numpy==1.19.5` is a pack nobody can install: the manager
  resolves every install with the app's own distributions pinned, and an exact pin that
  disagrees with them comes back as an unsatisfiable conflict. Prefer `>=`/`<` ranges.
- **Keep `import astro_canvas_yourpack` cheap.** Import astropy and friends *inside*
  `register()` or inside the node functions, so discovering packs at start-up stays fast and a
  heavy optional dependency does not fail the whole pack.

Publish it wherever your users can reach it: PyPI, a git repository, or an internal index.

Check it installs the way the manager will:

```sh
uv pip install --dry-run --python <the app's python> astro-canvas-yourpack \
    astro-canvas==<version> astro-canvas-sdk==<version>
```

If that reports a conflict, so will the Manager.

## 2. The registry entry

The registry is a single `index.json` in a git repository, served over HTTPS. Publishing is a
pull request against it; this repository carries the seed at
[`registry/index.json`](https://github.com/lblogan14/astro-canvas/blob/main/registry/index.json).

Add one object to the list:

```jsonc
{
  "name": "astro-canvas-yourpack",             // the distribution name
  "display_name": "Your pack — what it is for",
  "publisher": "your-github-handle",
  "description": "One or two sentences. This is the card text.",
  "source": "astro-canvas-yourpack",           // what the manager installs
  "latest": "0.1.0",
  "requires": { "astro-canvas": ">=0.1,<0.2", "python": ">=3.10,<3.14" },
  "categories": ["Spectra", "Photometry"],
  "security": "standard",
  "homepage": "https://github.com/you/yourpack",
  "templates": [
    {
      "id": "yourpack.quick-look",
      "name": "Quick look",
      "description": "What the template does.",
      "tags": ["spectra"],
      "layouts": ["app", "wizard"],
      "default_layout": "wizard"
    }
  ]
}
```

`source` is the string handed to `uv pip install`, so it may carry a version range
(`astro-canvas-yourpack>=0.1,<0.2`) or be a git URL — though a git URL is only installable by
users on the `permissive` level, so prefer a published name.

Entries that fail validation are skipped with a warning rather than breaking the index for
everyone, but that also means a malformed entry silently never appears. Check yours:

```sh
uv run --directory backend python -c "
import json, pathlib
from astro_canvas.manager.registry import parse_index
index = parse_index(json.loads(pathlib.Path('registry/index.json').read_text()))
print([e.name for e in index.entries])"
```

### What the reviewer looks at

Registry curation is the v0.1 substitute for scanning (design §9, §11), so a pull request is
reviewed for:

- the distribution installs cleanly against the current Astro Canvas, on all three OSes;
- `register()` succeeds and the nodes carry real docstrings (they *are* the UI's help text);
- the declared `security` class is honest — say `needs-network` if a node fetches, and
  `runs-subprocess` if one shells out;
- no node writes outside `ctx.scratch_dir` or the workspace;
- templates listed here exist in the pack and open.

## 3. Templates and sample data

A template is a workflow document (or a full `.acw` bundle) under `templates_dir`. Ship
`<stem>.md` beside it for the README the gallery shows, and `<stem>.png` for the card image —
exporting a bundle with *Render preview images* produces exactly such a PNG as
`figures/card.png`.

Sample data under `sample_data_dir` is copied into `<workspace>/samples/<pack>/` on first use, so
a template can point at `samples/<pack>/example.fits` and work in a fresh workspace with no
setup. Keep it small; it ships in the wheel.

## Versioning

Bump the node `version=` in `@node(...)` when a node's *contract* changes — its ports, its
parameters or its numerical meaning. The version is part of every cache key, so bumping it
invalidates cached results, which is exactly what you want when the answer would now be
different. Renaming a node id breaks existing documents; deprecate instead
(`@node(deprecated=True)` keeps it loadable and hides it from the menu).
