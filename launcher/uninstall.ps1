<#
.SYNOPSIS
    Remove Astro Canvas from Windows. Your workspace is never touched.

.DESCRIPTION
    Uninstalls the uv tool, deletes the Start-menu and Desktop shortcuts, and removes the
    %LOCALAPPDATA%\astro-canvas install folder. The workspace (<Documents>\AstroCanvas by
    default, or whatever `astro-canvas workspace list` shows) holds your workflows and data and
    is deliberately left alone.

.PARAMETER Purge
    Also remove the config folder (the bearer token, the auth secret and the registry cache).
#>
[CmdletBinding()]
param([switch]$Purge)

$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

$AppName = 'Astro Canvas'
$Root = Join-Path $env:LOCALAPPDATA 'astro-canvas'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

Write-Step 'removing the tool'
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    $env:UV_TOOL_DIR = Join-Path $Root 'tools'
    $env:UV_TOOL_BIN_DIR = Join-Path $Root 'bin'
    & $uv.Source tool uninstall astro-canvas
}
else {
    Write-Host '    uv not found; removing files only' -ForegroundColor DarkGray
}

Write-Step 'removing shortcuts'
@(
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk")
) | ForEach-Object {
    if (Test-Path $_) {
        Remove-Item $_ -Force
        Write-Host "    removed $_" -ForegroundColor DarkGray
    }
}

Write-Step 'removing the install folder'
if (Test-Path $Root) {
    Remove-Item $Root -Recurse -Force
    Write-Host "    removed $Root" -ForegroundColor DarkGray
}

Write-Step 'cleaning up the environment'
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$binDir = Join-Path $Root 'bin'
if ($userPath -and $userPath -like "*$binDir*") {
    $cleaned = ($userPath -split ';' | Where-Object { $_ -and $_ -ne $binDir }) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $cleaned, 'User')
    Write-Host "    removed $binDir from your PATH" -ForegroundColor DarkGray
}
foreach ($name in @('UV_TOOL_DIR', 'UV_TOOL_BIN_DIR')) {
    if ([Environment]::GetEnvironmentVariable($name, 'User')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'User')
    }
}

if ($Purge) {
    Write-Step 'removing the config folder'
    $config = Join-Path $env:LOCALAPPDATA 'AstroCanvas'
    if (Test-Path $config) {
        Remove-Item $config -Recurse -Force
        Write-Host "    removed $config" -ForegroundColor DarkGray
    }
}

Write-Step 'done'
Write-Host 'Your workspace was left in place. Remove it by hand if you want it gone.'
