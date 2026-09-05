# Troubleshooting

Start here:

```sh
astro-canvas doctor
```

Every line below matches a line of that report.

## Installing

??? question "Windows says the installer is unsafe"

    SmartScreen: **More info → Run anyway**. The installer is not code-signed yet, so it has no
    reputation — that is what the warning is about, and it is not a claim that the file is
    broken. The release page publishes SHA-256 checksums if you would rather verify the download
    ([details](install/windows.md#smartscreen)).

??? question "macOS says the app is damaged and can't be opened"

    It is not damaged; it is unsigned and quarantined. **Right-click → Open → Open**, once per
    install. If that dialog has no *Open*:

    ```sh
    xattr -dr com.apple.quarantine "/Applications/Astro Canvas.app"
    ```

    [More](install/macos.md#gatekeeper).

??? question "The AppImage will not start"

    Usually FUSE:

    ```sh
    ./astro-canvas-*.AppImage --appimage-extract-and-run
    ```

    If it is a permissions problem instead, `chmod +x` the file.

??? question "`astro-canvas: command not found` after the one-line install"

    uv's shim directory is not on your `PATH` yet. `uv tool update-shell`, then open a new
    terminal. The desktop shortcut works either way, because it uses the full path.

??? question "The install fails with a path or FileNotFoundError on Windows"

    `MAX_PATH`. Install to the default `%LOCALAPPDATA%\astro-canvas` rather than somewhere deep,
    or enable long paths system-wide ([details](install/windows.md#long-paths)).

??? question "It is downloading hundreds of megabytes"

    Once, on the first launch: a private Python 3.12 plus numpy, scipy, astropy, pyarrow and the
    packs. Nothing after that re-downloads it. A slow or metered link is a real problem here —
    the one-line install on a machine that already has `uv` reuses uv's shared cache.

## Starting

??? question "[warn] port … is in use — Astro Canvas may already be running"

    Something already owns 8765 — very likely Astro Canvas. `astro-canvas open` reuses it, which
    is what the shortcut does. To run a second one deliberately, give it its own port and
    workspace:

    ```sh
    astro-canvas serve --port 8766 --workspace ~/other
    ```

??? question "The browser opens on a blank page"

    Two candidates, and `doctor` tells them apart:

    - `[warn] bundled interface` — this build has no SPA in it (a development checkout without
      `task build`). Use a released wheel, or build the frontend.
    - The page loaded but the API is unauthorised — open the URL the server *printed*, the one
      with `?token=…`. A bare `http://127.0.0.1:8765` has no token.

??? question "`refusing to serve 0.0.0.0:8765`"

    Deliberate. The single-user token is shared by everyone who has the URL, and the pack manager
    installs into the server's own environment. For several people use
    [`--auth users`](deploy/server.md); for yourself over a network, an SSH tunnel
    ([details](install/linux.md#headless-machines-and-ssh)). `--i-know-what-i-am-doing` exists
    for a genuinely private network.

??? question "[FAIL] uv"

    The pack manager could not find or run `uv`. Install it from
    [docs.astral.sh/uv](https://docs.astral.sh/uv/), or point the app at one:

    ```sh
    ASTRO_CANVAS_UV_PATH=/usr/local/bin/uv astro-canvas doctor
    ```

    Everything else works without it; only installing and rolling back packs needs it.

## Running workflows

??? question "A node is stale and will not run"

    It is `expensive`, or an `auto` node that measured itself past two seconds. Press **Run**.
    Everything downstream of an expensive node waits too, on purpose — see
    [cost gating](concepts.md#cheap-expensive-and-auto).

??? question "Nothing recomputes when I change something"

    Check *what* you changed. Titles, positions, sizes and colours are not part of a cache key,
    so they never invalidate anything. If a parameter change does nothing, the node is probably
    not connected the way you think — the Inspector shows the resolved value.

??? question "A node fails with a memory error on a cube"

    Cubes above `mmap_min_mb` (8 MB by default) are memory-mapped rather than copied, but a node
    that materialises one in full still needs the room. Raise the memory cache
    (`ASTRO_CANVAS_CACHE_MEMORY_MB`) or lower the mapping threshold to zero to disable inlining
    entirely. See [memory-mapping cubes](dev/cube-memory.md).

??? question "A run hangs"

    Cancel it: cheap nodes cooperate through `ctx.is_cancelled()`, expensive ones are in a
    separate process and get killed. `ASTRO_CANVAS_RUN_TIMEOUT_S` (default 3600) is the backstop.

??? question "The events badge says disconnected"

    The WebSocket dropped; the client reconnects on its own and re-subscribes. If it stays
    disconnected, something between you and the server is closing idle connections — a reverse
    proxy without WebSocket support is the usual culprit
    ([the Caddyfile](https://github.com/lblogan14/astro-canvas/blob/main/deploy/Caddyfile) shows
    what is needed).

## Packs

??? question "[FAIL] pack … with a traceback"

    The pack imported and raised. `astro-canvas doctor --verbose` prints the full traceback. A
    pack that fails to load is skipped, never fatal — the rest of the app still works.

??? question "An install is blocked by conflicts"

    Working as intended: every resolution pins the app's own distributions, so a pack that would
    downgrade numpy under astropy comes back as an honest "no solution" instead of a broken
    install. The message is uv's own conclusion. Ask the pack's author for a release that fits,
    or install it into a separate workspace.

??? question "New nodes do not appear after an install"

    If the pack's module was already imported, Python will not re-import it, so the app asks for a
    restart rather than pretending. The banner says so; restart and they are there.

??? question "I broke the environment"

    ```sh
    astro-canvas pack snapshot --list
    astro-canvas pack rollback 3
    ```

    Every mutation snapshots `uv pip freeze` first, and a rollback restores that freeze exactly.

## Bundles and code

??? question "An imported workflow says its code nodes are quarantined"

    That is the design: code that arrived from somewhere else does not run until you have read
    it. Open the banner, read each snippet, trust or block it. Editing a trusted snippet changes
    its hash and quarantines it again, by construction. See
    [code nodes](guide/code-nodes.md).

??? question "An imported bundle lists missing inputs"

    The file was too large to embed (over `embed_inputs_max_mb`) or was only referenced. The
    import records the expected blake3 of each one, so putting the file in your workspace and
    pointing the node at it is verified, not assumed.

??? question "An imported bundle lists missing packs"

    It needs a pack you do not have. Install it (Node packs → Registry, or
    `astro-canvas pack install …`); the nodes reappear as soon as it is registered.

## Server

??? question "A user sees another user's workflows"

    They should not — each account has its own engine and its own workspace database. If you can
    reproduce it, that is a bug worth reporting with the output of `astro-canvas doctor` from
    inside the container.

??? question "The login cookie is not sticking"

    Almost always `PUBLIC_URL`. Behind TLS it must be the `https://` URL people actually use;
    that is what puts the `Secure` flag on the cookie and makes the browser keep it.

??? question "An admin cannot see the pack manager"

    `ADMIN_EMAILS` is applied **at registration**. If the address was added afterwards, flip the
    flag directly:

    ```sh
    docker compose -f deploy/compose.yaml exec db \
      psql -U canvas -d canvas -c "update users set is_superuser = true where email = 'pi@lab.example'"
    ```

## Still stuck

Open an issue with the full output of `astro-canvas doctor`, what you did, and what happened:
[github.com/lblogan14/astro-canvas/issues](https://github.com/lblogan14/astro-canvas/issues).
