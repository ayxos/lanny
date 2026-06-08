# Build Lanny.exe and a distributable Lanny-windows.zip on Windows.
#
# Output:
#   dist\Lanny\Lanny.exe    — windowless tray executable (folder mode)
#   dist\Lanny-windows.zip      — zipped folder ready to ship
#
# Must be run on Windows (PyInstaller can't cross-compile).
#
# Usage (PowerShell, repo root):
#   powershell -ExecutionPolicy Bypass -File build\build_win.ps1
$ErrorActionPreference = "Stop"

if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
    Write-Error "build_win.ps1 must run on Windows."
    exit 1
}

Set-Location (Split-Path $PSScriptRoot -Parent)
$root = (Get-Location).Path

# 1. Isolated venv with PyInstaller pinned.
if (-not (Test-Path ".venv-build")) {
    python -m venv .venv-build
}
. .\.venv-build\Scripts\Activate.ps1
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install pyinstaller==6.10.0 --quiet

# 2. Build the .exe (folder mode — much faster startup than --onefile).
Remove-Item -Recurse -Force build\work, dist\Lanny, dist\Lanny-windows.zip -ErrorAction SilentlyContinue
pyinstaller --noconfirm --clean `
    --workpath build\work `
    --distpath dist `
    build\lanny.spec

$exe = "dist\Lanny\Lanny.exe"
if (-not (Test-Path $exe)) {
    Write-Error "PyInstaller did not produce $exe"
    exit 1
}

# 3. Zip the folder for distribution.
$zip = "dist\Lanny-windows.zip"
Write-Host "==> creating $zip"
Compress-Archive -Path dist\Lanny\* -DestinationPath $zip -Force

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $root\$exe"
Write-Host "  $root\$zip"
Write-Host ""
Write-Host "Run locally:  .\$exe"
Write-Host "Ship:         $zip"
