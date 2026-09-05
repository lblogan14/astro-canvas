# Linux

A glibc-based x86-64 distribution from roughly 2020 onwards (Ubuntu 20.04, Debian 11, RHEL 9,
Fedora 34 and newer). No root is needed.

## Click to run

```sh
chmod +x astro-canvas-0.1.0a1-x86_64.AppImage
./astro-canvas-0.1.0a1-x86_64.AppImage
```

Download it from the [latest release](https://github.com/lblogan14/astro-canvas/releases). An
AppImage is one self-contained file: no package manager, no root, and deleting the file removes
the app. It is *not* sandboxed — it runs with your permissions, like anything else you download.

On a system without FUSE (many containers and some hardened distributions):

```sh
./astro-canvas-0.1.0a1-x86_64.AppImage --appimage-extract-and-run
```

To get a menu entry, either use [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher)
or take the one-line route below, which writes a `.desktop` file for you.

## One line

```sh
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh | sh
```

For the pre-alpha packages on TestPyPI:

```sh
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh \
  | ASTRO_CANVAS_INDEX=https://test.pypi.org/simple/ sh
```

The script installs `uv` if it is missing, installs the app and the rbcodes pack into a private
environment, writes `~/.local/share/applications/astro-canvas.desktop`, and opens your browser.
It never touches the system Python, so nothing conflicts with your distribution's packages.

If `astro-canvas` is not found in a new shell, uv's shim directory is not on your `PATH`:

```sh
uv tool update-shell     # then open a new terminal
```

## Headless machines and SSH

There is no display requirement: the app is a web server plus a browser tab. On a remote machine,
run it there and forward the port.

```sh
# on the remote host
astro-canvas serve --port 8765

# on your laptop
ssh -N -L 8765:127.0.0.1:8765 you@remote
```

Then open the URL the server printed — the one with `?token=…`, which is what authenticates you.

!!! danger "Do not bind 0.0.0.0 to share it"

    `astro-canvas serve --host 0.0.0.0` refuses to start unless you also pass `--auth users`.
    The single-user token is shared by everyone who has the URL, and the pack manager installs
    into the *server's* environment, so anyone who reaches it changes what everybody runs. For a
    shared machine use [the server deployment](../deploy/server.md); for one person over a
    network, the SSH tunnel above is the right tool.

## Matplotlib and Qt

Set nothing: the app sets `MPLBACKEND=Agg` and `QT_QPA_PLATFORM=offscreen` for its own workers,
and no code path imports a Qt binding at module level. `astro-canvas doctor` verifies that.

## Where things live

| | |
|---|---|
| Application | `uv tool dir` (usually `~/.local/share/uv/tools/astro-canvas`) |
| Shims | `~/.local/bin` |
| Config (token, chosen workspace, registry cache) | `~/.config/AstroCanvas` |
| Workspace | `~/Documents/AstroCanvas`, or `$XDG_DOCUMENTS_DIR/AstroCanvas` |
| Menu entry | `~/.local/share/applications/astro-canvas.desktop` |

## Removing it

```sh
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/uninstall.sh | sh
```

Your workspace is never removed. See [upgrading and removing](upgrading.md).
