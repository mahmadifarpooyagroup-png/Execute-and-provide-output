param(
    [switch]$InstallWeb,
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'

$appData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE 'AppData\Local' }
$atrinRoot = Join-Path $appData 'Atrin\runtime'
$venvPath = Join-Path $atrinRoot 'venv'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$requirementsMarker = Join-Path $atrinRoot 'requirements.ready'

New-Item -ItemType Directory -Force -Path $atrinRoot | Out-Null

function Get-PythonExecutable {
    $candidates = @(
        (Join-Path $atrinRoot 'python.exe'),
        'python.exe',
        'python',
        'py.exe',
        'py'
    )
    foreach ($candidate in $candidates) {
        if ([IO.Path]::IsPathRooted($candidate)) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return (Resolve-Path -LiteralPath $candidate).Path }
            continue
        }
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    return $null
}

$systemPython = Get-PythonExecutable
if (-not $systemPython) {
    Write-Error "Python 3.12+ is required for first-run bootstrap. Install Python and ensure it is available on PATH."
    exit 1
}

$versionText = & $systemPython --version 2>&1
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch 'Python (\d+)\.(\d+)') {
    Write-Error "Unable to determine the Python version from '$systemPython'."
    exit 1
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -ne 3 -or $minor -lt 10) {
    Write-Error "Atrin requires Python 3.10 or newer. Detected: $versionText"
    exit 1
}

if (-not (Test-Path (Join-Path $venvPath 'Scripts\python.exe') -PathType Leaf)) {
    Write-Host "Creating managed Atrin virtual environment: $venvPath"
    & $systemPython -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create the managed Atrin virtual environment."
        exit $LASTEXITCODE
    }
}

$pythonExe = Join-Path $venvPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    Write-Error "Managed Atrin Python executable was not created: $pythonExe"
    exit 1
}

if (-not (Test-Path -LiteralPath $requirementsMarker -PathType Leaf)) {
    if ($Offline) {
        Write-Error "Offline bootstrap requested but the managed runtime has not been provisioned yet."
        exit 1
    }
    Write-Host "Installing Atrin runtime dependencies..."
    & $pythonExe -m pip install --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $extras = if ($InstallWeb) { '.[web]' } else { '.' }
    & $pythonExe -m pip install --disable-pip-version-check --no-deps $repoRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install the Atrin package into the managed runtime."
        exit $LASTEXITCODE
    }

    if (-not $Offline) {
        & $pythonExe -m pip install --disable-pip-version-check $extras
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install Atrin runtime dependencies. Check network access or use a pre-provisioned runtime."
            exit $LASTEXITCODE
        }
    }

    Set-Content -LiteralPath $requirementsMarker -Value (Get-Date).ToUniversalTime().ToString('o') -Encoding ascii
}

Write-Host "Atrin managed Python runtime: $pythonExe"
Write-Host "Launch command: `"$pythonExe`" -m atrin_core.runtime"
