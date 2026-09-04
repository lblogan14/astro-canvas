<#
.SYNOPSIS
    Astro Canvas one-line installer for Windows (design 4.3 tier 1).

.DESCRIPTION
    Installs uv if it is missing, installs astro-canvas as a uv tool on Python 3.12, creates a
    Start-menu and Desktop shortcut that runs `astro-canvas open`, and opens the browser.

    The tool environment goes under %LOCALAPPDATA%\astro-canvas: a deep path plus a venv full of
    numpy/astropy DLLs runs into the 260-character MAX_PATH limit, and that folder is short
    (see docs/install/windows.md for enabling long paths system-wide).

    Nothing here calls pip: uv owns the environment (CONTRIBUTING, tooling rule).

.EXAMPLE
    irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.ps1 | iex

.PARAMETER Version
    Version to install, e.g. 0.1.0a1. Default: the latest release.

.PARAMETER Index
    Package index URL. Point it at TestPyPI to install a pre-release.

.PARAMETER Packs
    Extra packs to install alongside. Default: astro-canvas-rbcodes.

.PARAMETER NoShortcut
    Skip the Start-menu and Desktop shortcuts.

.PARAMETER NoOpen
    Do not start the app at the end.
#>
[CmdletBinding()]
param(
    [string]$Version = $env:ASTRO_CANVAS_VERSION,
    [string]$Index = $env:ASTRO_CANVAS_INDEX,
    [string[]]$Packs = @($(if ($env:ASTRO_CANVAS_PACKS) { $env:ASTRO_CANVAS_PACKS } else { 'astro-canvas-rbcodes' })),
    [string]$Python = '3.12',
    [switch]$NoShortcut,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$AppName = 'Astro Canvas'
$Root = Join-Path $env:LOCALAPPDATA 'astro-canvas'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Note([string]$Text) {
    Write-Host "    $Text" -ForegroundColor DarkGray
}

function Find-Uv {
    $candidates = @(
        (Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'),
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return $null
}

# --- uv ----------------------------------------------------------------------------------------

$uv = Find-Uv
if (-not $uv) {
    Write-Step 'installing uv'
    # Astral's own installer; it places uv in %USERPROFILE%\.local\bin and updates PATH.
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    $uv = Find-Uv
    if (-not $uv) {
        throw 'uv was installed but could not be found; open a new PowerShell window and re-run this script.'
    }
}
Write-Note "uv: $uv ($(& $uv --version))"

# --- the tool ----------------------------------------------------------------------------------

Write-Step "installing astro-canvas (Python $Python)"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
# Short install path: a venv of compiled scientific wheels blows past MAX_PATH otherwise.
$env:UV_TOOL_DIR = Join-Path $Root 'tools'
$env:UV_TOOL_BIN_DIR = Join-Path $Root 'bin'
$env:UV_CACHE_DIR = Join-Path $Root 'cache'

$requirement = if ($Version) { "astro-canvas==$Version" } else { 'astro-canvas' }
$arguments = @('tool', 'install', $requirement, '--python', $Python, '--force')
# `powershell -File script.ps1 -Packs a,b` hands the whole list over as one string, and so does
# `$env:ASTRO_CANVAS_PACKS`; split it so both spellings mean the same thing.
$wanted = $Packs | ForEach-Object { $_ -split '[,\s]+' } | Where-Object { $_ }
foreach ($pack in $wanted) { $arguments += @('--with', $pack) }
if ($Index) {
    # A pre-release lives on TestPyPI, whose mirror of the dependency tree is incomplete, so
    # PyPI stays in the list as a fallback index.
    $arguments += @('--index', $Index, '--index-strategy', 'unsafe-best-match')
}
& $uv @arguments
if ($LASTEXITCODE -ne 0) { throw "uv tool install failed with exit code $LASTEXITCODE" }

# uv writes `astro-canvas.exe`; accept the other shim shapes rather than assuming one.
$exe = $null
foreach ($name in 'astro-canvas.exe', 'astro-canvas.cmd', 'astro-canvas.bat', 'astro-canvas') {
    $candidate = Join-Path $env:UV_TOOL_BIN_DIR $name
    if (Test-Path $candidate) { $exe = $candidate; break }
}
if (-not $exe) {
    throw "astro-canvas was installed but no shim appeared in $env:UV_TOOL_BIN_DIR."
}
Write-Note "installed: $(& $exe version)"

# Put the shim directory on the user's PATH so `astro-canvas` works in a new terminal.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$env:UV_TOOL_BIN_DIR*") {
    [Environment]::SetEnvironmentVariable('Path', "$userPath;$env:UV_TOOL_BIN_DIR", 'User')
    Write-Note "added $env:UV_TOOL_BIN_DIR to your PATH (new terminals only)"
}
# uv reads these from the environment, so a later `uv tool upgrade` has to find the same dirs.
foreach ($pair in @(
        @{ Name = 'UV_TOOL_DIR'; Value = $env:UV_TOOL_DIR },
        @{ Name = 'UV_TOOL_BIN_DIR'; Value = $env:UV_TOOL_BIN_DIR })) {
    [Environment]::SetEnvironmentVariable($pair.Name, $pair.Value, 'User')
}

# --- shortcuts ---------------------------------------------------------------------------------

function New-Shortcut([string]$Path, [string]$Target) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.Arguments = 'open'
    $link.WorkingDirectory = Split-Path $Target -Parent
    $link.Description = 'Node-based canvas for astronomical data'
    $link.IconLocation = "$Target,0"
    $link.Save()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
}

if (-not $NoShortcut) {
    Write-Step 'creating shortcuts'
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
    $links = @(
        (Join-Path $startMenu "$AppName.lnk"),
        (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk")
    )
    foreach ($link in $links) {
        New-Shortcut -Path $link -Target $exe
        Write-Note $link
    }
}

# --- first run ---------------------------------------------------------------------------------

Write-Step 'checking the installation'
& $exe doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'doctor reported a problem above; the app may still work.'
}

if (-not $NoOpen) {
    Write-Step 'starting Astro Canvas'
    Write-Note 'Close this window to stop the server; use the Start-menu shortcut to start it again.'
    & $exe open
}
else {
    Write-Host ''
    Write-Host "Done. Run 'astro-canvas open' or use the $AppName shortcut." -ForegroundColor Green
}
