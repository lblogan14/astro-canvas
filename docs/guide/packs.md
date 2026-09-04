# Node packs: installing, updating and rolling back (phase 11)

Every node in Astro Canvas comes from a **node pack** — a normal Python distribution that
declares an `astro_canvas.nodes` entry point. `astro-canvas-core` and `astro-canvas-rbcodes`
ship with the app; anything else is installed through **Node packs** (the Share menu, or
`/manager`).

Packs go into the **one environment the app already runs in**, not into a venv each. That is why
installing one is a negotiation rather than a download: a pack whose pins disagree with what
Astro Canvas needs cannot be installed, and you are told so before anything is touched.

## The two steps of every change

Nothing is written to your environment before you have seen what it would do.

1. **Resolve.** Type a source and press *Install*. The manager dry-runs it with the app's own
   distributions pinned, and shows you the diff: what is **added**, **upgraded**, **downgraded**
   and **removed**.
2. **Confirm.** Only then does it snapshot the environment, install, import-test the new pack in
   a separate process, and register its nodes.

A plan that the resolver could not satisfy shows the reason and no confirm button at all:

> you require numpy==1.19.5 and astro-canvas==0.1.0a0, we can conclude that your requirements are
> unsatisfiable.

That is not the manager being cautious — the resolution genuinely has no solution, and forcing it
would break the app. Ask the pack's author for a release compatible with your Astro Canvas
version.

A plan that **downgrades or removes** something is flagged too. It can be confirmed, but other
packs may depend on what it takes away; take a snapshot first (see below).

## What you can install

| Source | Example |
|---|---|
| A package name | `astro-canvas-rbcodes` |
| A name with a version range | `astro-canvas-rbcodes>=0.1,<0.2` |
| A git repository | `git+https://github.com/org/pack@v1.2` |
| A wheel URL | `https://…/pack-1.0-py3-none-any.whl` |
| A local checkout | `./packs/my-pack` |

Which of those are allowed is the **security level** (Manager ▸ Settings):

| Level | Allows |
|---|---|
| **Strict** | Only packs listed in the registry index |
| **Standard** (default) | Registry packs, plus any package name from PyPI |
| **Permissive** | Any source at all — git URLs, wheel URLs, local paths |

Permissive also lifts the [code node](code-nodes.md)'s import restrictions, so treat it as
"I trust everything I install and everything I run".

## The registry

The **Registry** tab lists packs from a git-backed `index.json` — no service, no account. It is
fetched at most once an hour, revalidated with an `ETag`, and cached on disk, so the tab still
works offline (it says so when what you are seeing is a cached copy). Packs you already have are
marked *Installed* rather than offered again.

To get a pack listed, open a pull request against the registry repository; see
[publishing a pack](../packs/publishing.md).

## Enable, disable, update, uninstall

- **Disable** keeps the pack installed but unregisters its nodes: the library loses them, and
  workflows using them report `unknown_node` until you enable it again. Both directions take
  effect immediately — no restart. The choice is per workspace and survives restarts.
- **Update** re-resolves the pack with `--upgrade`. New code cannot replace code Python has
  already imported, so an update always ends with *restart Astro Canvas to finish loading*.
- **Uninstall** removes the distribution and its nodes.

A pack that fails to *load* (a missing optional dependency, say) never takes the server down: it
appears in the list marked **Failed to load**, with a **Traceback** button showing exactly what
went wrong.

## Snapshots and rollback

A snapshot records `uv pip freeze` — the exact contents of the environment. One is taken
automatically **before every install**, and you can take one yourself before an experiment.

**Roll back** restores a snapshot: the manager compares the recorded freeze with what is
installed now and touches only what differs. Afterwards `uv pip freeze` matches the snapshot line
for line. A rollback replaces loaded code, so it ends with the restart banner.

## Where things live

| | |
|---|---|
| Installed packs, snapshots, security level, trust decisions | `<workspace>/.astro-canvas/app.db` |
| Registry cache | the per-user config folder, next to the auth token |
| The environment itself | wherever the app's Python lives (Manager ▸ Settings shows both paths) |

## uv

Every environment change goes through [uv](https://docs.astral.sh/uv/) — never `pip`, never a
new venv. The manager finds it next to the launcher, then on `PATH`; Manager ▸ Settings shows
which binary and which interpreter it is using, and lets you point at a different `uv`.

If uv is missing, the Manager says so and every install is refused until it is installed or its
path is set (`ASTRO_CANVAS_UV_PATH` also works).

## Settings you can preset

| Environment variable | Effect |
|---|---|
| `ASTRO_CANVAS_PACK_SECURITY` | Default security level (`strict`, `standard`, `permissive`) |
| `ASTRO_CANVAS_UV_PATH` | The uv binary to use |
| `ASTRO_CANVAS_REGISTRY_URL` | The registry `index.json` |
| `ASTRO_CANVAS_MANAGER=false` | Serve without `/api/manager` at all (a locked-down deployment) |

What you choose in Manager ▸ Settings is stored per workspace and wins over these.
