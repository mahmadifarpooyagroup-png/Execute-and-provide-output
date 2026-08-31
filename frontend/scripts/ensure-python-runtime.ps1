param()

$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$python = Get-Command python -ErrorAction SilentlyContinue

if (-not $python) {
    Write-Error "Python runtime is required for Atrin. Install Python 3.12+ and ensure 'python' is on PATH before continuing."
    exit 1
}

$pythonExe = $python.Source
Write-Host "Using Python: $pythonExe"

# Ensure the project installation is available to the app runtime.
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -e $repoRoot

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install the Atrin project and runtime dependencies."
    exit $LASTEXITCODE
}

Write-Host "Python runtime and Atrin project dependencies are ready."
Write-Host "Launch the runtime with: python -m atrin_core.runtime"
