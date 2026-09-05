# Windows

Windows 10 or 11, 64-bit. No administrator rights are needed for any route here.

## Click to run

1. Download `astro-canvas-<version>-setup.exe` from the
   [latest release](https://github.com/lblogan14/astro-canvas/releases).
2. Run it. **SmartScreen will warn you** — see below.
3. Pick a folder (the default, `%LOCALAPPDATA%\astro-canvas`, is the right one) and install.
4. Finish with *Start Astro Canvas*, or use the Start-menu shortcut later.

The first launch downloads Python 3.12 and the science packages. A progress page opens in your
browser and swaps itself for the app when the server is ready; the console window behind it shows
the download. Expect several minutes on a first run and a few seconds afterwards.

### SmartScreen

The installer is not signed with a code-signing certificate yet, so Windows shows
**"Windows protected your PC"**. To install anyway: **More info** → **Run anyway**.

That warning is about reputation, not about the file being broken — an unsigned executable simply
has none, and buying it back is not free (an OV certificate is €150–300 a year, and EV
certificates no longer bypass SmartScreen). The release page publishes SHA-256 checksums for
every artefact if you would like to verify the download instead:

```powershell
Get-FileHash .\astro-canvas-0.1.0a1-setup.exe -Algorithm SHA256
```

## One line

```powershell
irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.ps1 | iex
```

For the pre-alpha packages on TestPyPI, run the script with arguments instead of piping it:

```powershell
$installer = "$env:TEMP\astro-canvas-install.ps1"
irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.ps1 -OutFile $installer
& $installer -Index 'https://test.pypi.org/simple/'
```

If PowerShell refuses to run the file, it is the execution policy, not the script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $installer -Index 'https://test.pypi.org/simple/'
```

## Long paths

Astro Canvas installs into `%LOCALAPPDATA%\astro-canvas` on purpose. A virtual environment full
of compiled scientific wheels nests deeply, and Windows still truncates paths at 260 characters
in many APIs — under a long path, installs fail with `FileNotFoundError` on a file that is
plainly there.

The short install path avoids it. If you hit the limit anyway (a workspace deep inside OneDrive,
say), turn on long-path support once, as administrator:

```powershell
New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
  -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
```

Then sign out and back in.

## Windows Defender

Defender scans every DLL in a fresh install the first time it is loaded, which can make the first
launch noticeably slower than the second. It is not a hang. If your machine is managed and
scanning is aggressive, ask for an exclusion on the install folder:

```powershell
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\astro-canvas"
```

(That needs administrator rights, and it is a trade-off — decide it with whoever manages the
machine.)

## Where things live

| | |
|---|---|
| Application | `%LOCALAPPDATA%\astro-canvas` |
| Config (token, chosen workspace, registry cache) | `%LOCALAPPDATA%\AstroCanvas` |
| Workspace | `%USERPROFILE%\Documents\AstroCanvas` |
| Shortcuts | Start menu and Desktop, both running `astro-canvas open` |

## Removing it

Settings → Apps → *Astro Canvas* → Uninstall, or:

```powershell
irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/uninstall.ps1 | iex
```

Your workspace is never removed. See [upgrading and removing](upgrading.md).
