# Command line

`astro-canvas` is the whole app: the desktop shortcut runs `astro-canvas open`, the Docker image
runs `astro-canvas serve`, and everything the Manager does has a subcommand here.

```console
$ astro-canvas --help
 Usage: astro-canvas [OPTIONS] COMMAND [ARGS]...

 Node-based canvas for exploring astronomical data.

 serve       Run the Astro Canvas server.
 open        Open Astro Canvas: reuse the server that is already running, or start one.
 run         Execute a workflow headlessly and print a per-node summary.
 doctor      Check this installation and print a report.
 workspace   Choose which folder Astro Canvas opens.
 pack        Install, remove and roll back node packs.
 bundle      Export and import .acw bundles.
 version     Print the installed version.
```

## `open`

```sh
astro-canvas open [--port 8765] [--workspace PATH] [--first-run]
```

What a shortcut should run. It probes `/api/health` first: if a server is already up it just
opens the browser at it, so clicking the icon twice does not start a second server on a port that
is already taken. `--first-run` opens a progress page immediately instead of waiting — the
click-to-run launcher passes it, because a cold start has to import astropy and both packs before
it can answer anything.

## `serve`

```sh
astro-canvas serve [--host 127.0.0.1] [--port 8765] [--workspace PATH]
                   [--auth none|token|users] [--token TOKEN] [--open]
```

| `--auth` | Who can use it |
|---|---|
| `token` (default) | One bearer token, generated at startup and printed in the URL |
| `none` | Nobody is checked — only sane on loopback, in a container, or in a test |
| `users` | Login accounts, one workspace each ([server deployment](deploy/server.md)) |

Binding a non-loopback address needs `--auth users`, or an explicit
`--i-know-what-i-am-doing`:

```console
$ astro-canvas serve --host 0.0.0.0
refusing to serve 0.0.0.0:8765 with --auth token: the one token is shared by everyone who
reaches it, and the pack manager installs into this server's own environment. Use --auth users
for a shared server, keep --host 127.0.0.1 for yourself, or pass --i-know-what-i-am-doing
(env ASTRO_CANVAS_ALLOW_PUBLIC_BIND=1) if this port really is private.
```

That is not paternalism about ports: the pack manager installs into the *server's* environment,
so anyone who reaches `/api/manager` changes what everybody else runs.

## `run`

```sh
astro-canvas run workflow.json [--workspace PATH] [--target NODE]... [--json] [--no-processes]
```

Executes a document to completion and prints a per-node summary, without a browser. This is the
cluster and cron-job entry point.

```console
$ astro-canvas run absorption.json --workspace ~/papers/lya
run 4f0a2c: done
  load                     done          412 ms  out:astro.Spectrum1D
  continuum                done         1834 ms  out:astro.Spectrum1D
  ew                       done           88 ms cached  out:astro.Table
```

`--target` runs only what is needed for those nodes. `--json` prints the same thing as JSON, for
a pipeline that wants to check states or elapsed times. The exit code is 1 if any node failed or
the graph did not validate.

## `doctor`

```sh
astro-canvas doctor [--workspace PATH] [--verbose]
```

Version, interpreter, whether the SPA is bundled, which `uv` the manager will use, the workspace,
free disk, every pack with its node counts (or its load error), whether Qt got imported, and
whether the port is free. Exits non-zero if anything failed. `--verbose` adds the full traceback
of any pack that would not load.

Paste the output into a bug report and most questions are already answered.

## `workspace`

```sh
astro-canvas workspace list
astro-canvas workspace use ~/papers/lya [--create]
astro-canvas workspace new ~/papers/lya [--no-use]
```

`use` records the choice in the config folder, so the app opens there next time; `new` creates
the folder, initialises its database and selects it. Only an explicit choice moves the default —
`astro-canvas run --workspace /tmp/scratch` does not.

## `pack`

```sh
astro-canvas pack list
astro-canvas pack install astro-canvas-rbcodes [--dry-run] [--yes]
astro-canvas pack remove rbcodes [--yes]
astro-canvas pack snapshot [--label "before the fit rewrite"] [--list]
astro-canvas pack rollback 3 [--yes]
```

The same `PackManager` the Manager page drives, so the two cannot drift — including the
plan-then-confirm shape:

```console
$ astro-canvas pack install astro-canvas-rbcodes
plan for astro-canvas-rbcodes:
  add       astro-canvas-rbcodes         - -> 0.1.0a1
  add       linetools                    - -> 0.3.2
  upgrade   scipy                        1.14.1 -> 1.18.1
install? [y/N]:
```

A plan with conflicts is printed and refused; nothing is installed without a clean resolution.
`--dry-run` stops after the plan, `--yes` skips the prompt (for CI).

Every mutation snapshots `uv pip freeze` first, which is what makes `rollback` exact. See
[node packs](guide/packs.md).

## `bundle`

```sh
astro-canvas bundle export <workflow-id> [--out share.acw] [--outputs leaves|all|none] [--no-figures]
astro-canvas bundle import share.acw [--restore-into imports]
```

The same functions the Share menu calls, so a bundle written here is byte-for-byte the one the
app writes. Import reports missing packs, missing input files and whether the code nodes came in
quarantined, and stores the workflow either way so you can look at it. See
[bundles](guide/bundles.md).

## Environment variables

Every setting is an `ASTRO_CANVAS_*` variable, which is how the Docker image is configured. The
common ones:

| Variable | Default | |
|---|---|---|
| `ASTRO_CANVAS_WORKSPACE` | `<Documents>/AstroCanvas` | The workspace folder |
| `ASTRO_CANVAS_HOST` / `_PORT` | `127.0.0.1` / `8765` | Where to listen |
| `ASTRO_CANVAS_AUTH` | `token` | `none`, `token` or `users` |
| `ASTRO_CANVAS_TOKEN` | generated | The bearer token |
| `ASTRO_CANVAS_CONFIG_DIR` | platform config dir | Token, chosen workspace, registry cache |
| `ASTRO_CANVAS_PACK_SECURITY` | `standard` | `strict`, `standard` or `permissive` |
| `ASTRO_CANVAS_UV_PATH` | discovered | The `uv` the manager should use |
| `ASTRO_CANVAS_MANAGER` | `true` | Set `false` to serve without `/api/manager` at all |
| `ASTRO_CANVAS_CACHE_MEMORY_MB` | `2048` | Memory cache ceiling |
| `ASTRO_CANVAS_CACHE_DISK_GB` | `20` | Blob store ceiling |
| `ASTRO_CANVAS_MAX_WORKERS` | CPU count | Thread and process pool size |
| `ASTRO_CANVAS_RUN_TIMEOUT_S` | `3600` | Per-run wall clock limit |

The server-only ones (`DATABASE_URL`, `ADMIN_EMAILS`, `PUBLIC_URL`, `SHARED_DIR`, …) are in
[server deployment](deploy/server.md).
