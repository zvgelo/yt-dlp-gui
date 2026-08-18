# Build the Windows release artifacts.
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -AllowDirty
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -SkipRuntimeDeps
#
# Produces a portable ZIP, and an Inno Setup installer when the Inno Setup
# compiler is on the machine. Both contain the same directory: the application,
# the Python runtime, Qt, yt-dlp, FFmpeg and Deno. Nothing else has to be
# installed on the target machine.
#
# Must run on Windows. PySide6 and the PyInstaller bootloader are native, so
# there is no supported way to produce this from Linux.

[CmdletBinding()]
param(
    [switch]$AllowDirty,
    [switch]$SkipRuntimeDeps,
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$BuildDir = Join-Path $Root 'build'
$FrozenDir = Join-Path $BuildDir 'frozen'
$DistDir = Join-Path $Root 'dist\windows'
$StagingDir = Join-Path $BuildDir 'windows-stage'

function Write-Step([string]$Message) { Write-Host "`n[windows] $Message" }
function Fail([string]$Message) { Write-Error "[windows] error: $Message"; exit 1 }

Write-Step 'checking prerequisites'
if (-not $Python) {
    $candidate = Join-Path $Root '.venv-build\Scripts\python.exe'
    $Python = if (Test-Path $candidate) { $candidate } else { 'python' }
}
& $Python -c 'import PyInstaller' 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail @"
PyInstaller is not installed in $Python
  create the build environment with:
    python -m venv .venv-build
    .venv-build\Scripts\pip install -r packaging\requirements-build.txt
"@
}

$Version = (& $Python -c "import sys; sys.path.insert(0, r'$Root'); from app import __version__; print(__version__)").Trim()
$ZipName = "yt-dlp-gui-$Version-windows-x86_64.zip"
Write-Host "  version   $Version"
Write-Host "  artifact  $ZipName"

Write-Step 'writing the executable version resource'
$VersionFile = Join-Path $BuildDir 'windows-version-info.txt'
& $Python (Join-Path $PSScriptRoot 'windows_version_info.py') --output $VersionFile
if ($LASTEXITCODE -ne 0) { Fail 'could not write the version resource' }

Write-Step 'building the application bundle'
$buildArgs = @((Join-Path $PSScriptRoot 'build_app.py'), '--output', $FrozenDir,
               '--windows-version-file', $VersionFile)
if ($AllowDirty) { $buildArgs += '--allow-dirty' }
if ($SkipRuntimeDeps) { $buildArgs += '--skip-runtime-deps' }
& $Python @buildArgs
if ($LASTEXITCODE -ne 0) { Fail 'the application bundle failed to build' }

Write-Step 'staging the portable directory'
if (Test-Path $StagingDir) { Remove-Item -Recurse -Force $StagingDir }
$AppDir = Join-Path $StagingDir 'yt-dlp-gui'
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
Copy-Item -Recurse -Force (Join-Path $FrozenDir 'yt-dlp-gui\*') $AppDir

# Licences travel with the binaries they cover
$LicenseDir = Join-Path $AppDir 'licenses'
New-Item -ItemType Directory -Path $LicenseDir -Force | Out-Null
Copy-Item (Join-Path $Root 'LICENSE') (Join-Path $LicenseDir 'LICENSE')
if (Test-Path (Join-Path $Root 'licenses')) {
    Copy-Item -Recurse -Force (Join-Path $Root 'licenses\*') $LicenseDir
}
$FfmpegLicense = Join-Path $BuildDir 'runtime-windows\FFMPEG-LICENSE.txt'
if (Test-Path $FfmpegLicense) { Copy-Item $FfmpegLicense $LicenseDir }
Copy-Item (Join-Path $Root 'README.md') (Join-Path $AppDir 'README.md')

Write-Step 'smoke-testing the bundle'
$exe = Join-Path $AppDir 'yt-dlp-gui.exe'
if (-not (Test-Path $exe)) { Fail "the executable is missing at $exe" }
& $exe --version
if ($LASTEXITCODE -ne 0) { Fail 'the executable does not report its version' }
& $exe --self-test
if ($LASTEXITCODE -ne 0) { Fail 'the self-test failed' }

Write-Step 'creating the portable ZIP'
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
$ZipPath = Join-Path $DistDir $ZipName
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path $AppDir -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Step 'building the installer'
$IsccCandidates = @(
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe'
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { $Iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }

if ($Iscc) {
    & $Iscc `
        "/DAppVersion=$Version" `
        "/DSourceDir=$AppDir" `
        "/DOutputDir=$DistDir" `
        (Join-Path $Root 'packaging\windows\yt-dlp-gui.iss')
    if ($LASTEXITCODE -ne 0) { Fail 'the installer failed to build' }
} else {
    Write-Host '  Inno Setup (ISCC.exe) was not found; skipping the installer.'
    Write-Host '  The portable ZIP is a complete artifact on its own.'
    Write-Host '  Install Inno Setup 6 from https://jrsoftware.org/isdl.php to build one.'
}

Write-Step 'hashing the artifacts'
Get-ChildItem $DistDir -File | Where-Object { $_.Extension -in '.zip', '.exe' } | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "$hash  $($_.Name)" | Out-File -Encoding ascii (Join-Path $DistDir "$($_.Name).sha256")
    Write-Host ("  {0}  {1}  {2:N0} bytes" -f $hash.Substring(0, 16), $_.Name, $_.Length)
}

Write-Step 'done'
Write-Host "  artifacts in $DistDir"
