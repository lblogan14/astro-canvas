# Upgrading and removing

## Upgrading

=== "One-line install"

    ```sh
    uv tool upgrade astro-canvas
    ```

    ```powershell
    uv tool upgrade astro-canvas
    ```

    Re-running the installer works too and does the same thing (`uv tool install --force`).

=== "Click-to-run launcher"

    ```sh
    astro-canvas-launcher self update
    ```

    The launcher replaces its *payload* — the app and the packs — without touching the signed
    binary. That is the point of the PyApp design: a new version needs no re-notarisation on
    macOS and no fresh SmartScreen reputation on Windows.

=== "Docker"

    ```sh
    docker compose -f deploy/compose.yaml pull
    docker compose -f deploy/compose.yaml up -d
    ```

Your workspace survives all of them. Workspace databases are migrated automatically at startup;
so is the accounts database on a server.

## Packs

Packs upgrade separately from the app, because they are separate distributions:

```sh
astro-canvas pack list
astro-canvas pack install astro-canvas-rbcodes --yes
```

or in the app, **Node packs → Installed → Update**. Either way you see the resolution diff before
anything is written, and the environment is snapshotted first, so:

```sh
astro-canvas pack snapshot --list
astro-canvas pack rollback 3
```

puts it back exactly. See [node packs](../guide/packs.md).

## If an upgrade goes wrong

```sh
astro-canvas doctor          # what is actually installed, and what failed to load
```

For a click-to-run install, the launcher can rebuild its environment from scratch without
touching your workspace:

```sh
astro-canvas-launcher self restore
```

For a one-line install, the equivalent is a reinstall — `uv tool install astro-canvas --force`.

## Removing it

=== "macOS and Linux"

    ```sh
    curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/uninstall.sh | sh
    ```

    Add `PURGE=1` to also delete the config folder (the access token, the chosen workspace and
    the registry cache).

=== "Windows"

    Settings → Apps → *Astro Canvas* → Uninstall, or:

    ```powershell
    irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/uninstall.ps1 | iex
    ```

    Add `-Purge` to also delete the config folder.

=== "Docker"

    ```sh
    docker compose -f deploy/compose.yaml down          # keeps the volumes
    docker compose -f deploy/compose.yaml down -v       # deletes /data and the accounts
    ```

**Your workspace is never deleted by an uninstall.** It holds your workflows, your data and your
results, and no uninstaller should be in the business of throwing those away. Delete it yourself
when you mean to:

```sh
astro-canvas workspace list    # where it actually is
```
