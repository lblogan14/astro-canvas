<#
.SYNOPSIS
    Smoke test for launcher\install.ps1 without installing anything from the network.

.DESCRIPTION
    A stub `uv.cmd` on PATH records the arguments it was called with, so the assertions are about
    the requirement, the interpreter, the packs, the short install path and the shortcuts - the
    parts that break silently. The real network install is what the fresh-VM job in CI does
    (.github\workflows\release.yml).

        pwsh -File launcher\tests\install-smoke.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Script = Join-Path $Root 'launcher\install.ps1'
$Stage = Join-Path ([IO.Path]::GetTempPath()) ("astro-canvas-smoke-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Pass = 0
$script:Fail = 0

function Assert-Contains([string]$What, [string]$Haystack, [string]$Needle) {
    if ($Haystack -like "*$Needle*") {
        Write-Host "  ok   $What"
        $script:Pass++
    }
    else {
        Write-Host "  FAIL $What" -ForegroundColor Red
        Write-Host "       expected: $Needle" -ForegroundColor DarkGray
        Write-Host "       in: $Haystack" -ForegroundColor DarkGray
        $script:Fail++
    }
}

function Assert-True([string]$What, [bool]$Condition) {
    if ($Condition) {
        Write-Host "  ok   $What"
        $script:Pass++
    }
    else {
        Write-Host "  FAIL $What" -ForegroundColor Red
        $script:Fail++
    }
}

# --- the stub uv -------------------------------------------------------------------------------

$bin = Join-Path $Stage 'bin'
$toolBin = Join-Path $Stage 'toolbin'
$log = Join-Path $Stage 'uv.log'
New-Item -ItemType Directory -Force -Path $bin, $toolBin | Out-Null

$stub = @"
@echo off
echo %* >> "$log"
if "%1"=="--version" (
  echo uv 0.0.0-stub
  exit /b 0
)
if "%1"=="tool" (
  if "%2"=="install" (
    if not exist "%UV_TOOL_BIN_DIR%" mkdir "%UV_TOOL_BIN_DIR%"
    copy /y "$toolBin\astro-canvas-stub.cmd" "%UV_TOOL_BIN_DIR%\astro-canvas.cmd" >nul
    exit /b 0
  )
)
exit /b 0
"@
Set-Content -Path (Join-Path $bin 'uv.cmd') -Value $stub -Encoding ascii

# The shim the installer then runs (`& $exe version`, `& $exe doctor`). A batch file cannot be
# renamed to .exe and still run, which is why install.ps1 accepts .cmd as well.
$exeStub = @"
@echo off
if "%1"=="version" echo 0.0.0-stub
if "%1"=="doctor" echo all checks passed
exit /b 0
"@
Set-Content -Path (Join-Path $toolBin 'astro-canvas-stub.cmd') -Value $exeStub -Encoding ascii

Write-Host '==> install.ps1 with uv already present'

# Redirect everything the script writes: LOCALAPPDATA decides the install root, APPDATA the
# Start menu, and USERPROFILE the fallback uv locations.
$saved = @{}
foreach ($name in 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'Path') {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name)
}
try {
    $env:LOCALAPPDATA = Join-Path $Stage 'local'
    $env:APPDATA = Join-Path $Stage 'roaming'
    $env:USERPROFILE = Join-Path $Stage 'user'
    $env:Path = "$bin;$env:Path"
    New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA, $env:APPDATA, $env:USERPROFILE | Out-Null

    # install.ps1 runs on Windows PowerShell 5.1 and on PowerShell 7; use whichever is here.
    $host_exe = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell' }
    # With -File an array argument has to arrive as one comma-joined token.
    $output = & $host_exe -NoProfile -File $Script -Version '1.2.3' `
        -Packs 'astro-canvas-rbcodes,astro-canvas-extra' -NoShortcut -NoOpen 2>&1 |
        Out-String
}
finally {
    foreach ($name in $saved.Keys) { Set-Item -Path "env:$name" -Value $saved[$name] }
}

$recorded = if (Test-Path $log) { (Get-Content $log -Raw) } else { '' }

Assert-Contains 'installs the pinned version' $recorded 'tool install astro-canvas==1.2.3'
Assert-Contains 'targets Python 3.12' $recorded '--python 3.12'
Assert-Contains 'brings the rbcodes pack' $recorded '--with astro-canvas-rbcodes'
Assert-Contains 'passes extra packs through' $recorded '--with astro-canvas-extra'
# The tooling rule: uv only. Any pip at all in the recorded arguments is a failure.
Assert-True 'never invokes pip' (-not ($recorded -like '*pip*'))
Assert-Contains 'runs doctor' $output 'all checks passed'

Write-Host '==> the short install path (MAX_PATH)'
Assert-Contains 'installs under %LOCALAPPDATA%\astro-canvas' $output 'astro-canvas'
Assert-True 'the install root is short' ((Join-Path $Stage 'local\astro-canvas').Length -lt 120)

Write-Host ''
if ($script:Fail -gt 0) {
    Write-Host "$($script:Fail) check(s) failed, $($script:Pass) passed" -ForegroundColor Red
    Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "$($script:Pass) checks passed" -ForegroundColor Green
Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
