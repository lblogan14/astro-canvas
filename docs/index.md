# Astro Canvas

A node-based infinite canvas for exploring astronomical data. Load spectra, images and IFU
cubes, wire analysis nodes together, watch results appear as you edit, and share the whole
thing — data, results and provenance — as one file.

The science comes from **node packs**. The first two are `astro-canvas-core` (loading, maths,
plotting, archive queries, a Python code node) and `astro-canvas-rbcodes`, which rebuilds
[rbcodes](https://github.com/rongmon/rbcodes) — absorption-line measurements, redshift finding,
multi-spectrum viewing, IFU cubes — as headless, web-native nodes.

!!! warning "Pre-alpha"

    Astro Canvas is not released yet. The installers below fetch from
    [TestPyPI](https://test.pypi.org/project/astro-canvas/), formats may still change, and
    nothing here should be pointed at data you cannot reproduce.

## Get it running

<div class="grid cards" markdown>

-   __One line in a terminal__

    ---

    For anyone comfortable with a shell. Installs [uv](https://docs.astral.sh/uv/), the app and
    the rbcodes pack, and makes a desktop shortcut.

    [:octicons-arrow-right-24: Install](install/index.md)

-   __Click to run__

    ---

    A single downloadable launcher per OS. The first launch fetches Python and the science
    packages; later launches start in seconds.

    [:octicons-arrow-right-24: Windows](install/windows.md) ·
    [macOS](install/macos.md) ·
    [Linux](install/linux.md)

-   __A server for the group__

    ---

    Docker Compose: the app behind TLS, accounts in Postgres, one private workspace per person
    and a shared read-only folder.

    [:octicons-arrow-right-24: Server deployment](deploy/server.md)

-   __From a checkout__

    ---

    `git clone`, `uv sync`, `pnpm install`, `task dev`. The frontend is managed only with pnpm
    and the backend only with uv.

    [:octicons-arrow-right-24: CONTRIBUTING.md](https://github.com/lblogan14/astro-canvas/blob/main/CONTRIBUTING.md)

</div>

## Then what

1. [**Quick start**](quickstart.md) — open a template, run it, change a number, watch it
   recompute.
2. [**Concepts**](concepts.md) — nodes, ports, the workspace, cost gating, and why editing a
   title never re-runs anything.
3. [**App modes**](guide/modes.md) — the same document as a form, a wizard, or a dashboard.
4. [**Bundles**](guide/bundles.md) — hand a colleague one `.acw` file and they get the workflow,
   the inputs, the results and the provenance.

## What makes it different

**Reactive, not batch.** Dirtiness comes from content hashes, not from edit events. Change a
parameter and only what actually depends on it re-runs; rename a node and nothing does.
Expensive nodes wait for you to press Run instead of eating your laptop.

**The schema is the contract.** A node is a plain Python function; its annotations become ports,
its parameters become widgets, and its docstring becomes the help text you read in the app. There
is no separate UI to write — see [the node schema](formats/node-schema.md).

**Reproducible by construction.** A bundle carries the document, a dependency lock, the hash of
every input file, the cached results and a per-node provenance record. Importing one tells you
what is missing rather than guessing.

**Packs, not plugins.** Packs are ordinary Python distributions installed with `uv` into one
shared environment. The manager shows you the resolution diff before it touches anything, refuses
a pack whose pins would break the app, and can roll the environment back exactly.
