[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CandidateSymbol,

    [ValidateRange(180, 900)]
    [int]$DurationSeconds = 300,

    [string]$OutputDirectory = "",

    [switch]$AllowExtendedHours,

    [switch]$Execute,

    [string]$ProjectRoot = "",

    [string]$DependencyRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

$candidate = $CandidateSymbol.Trim().ToUpperInvariant()
if ($candidate -notmatch '^[A-Z0-9][A-Z0-9.-]{0,9}$') {
    throw "CandidateSymbol must be one normalized ticker with at most ten characters."
}
if ($candidate -in @("SPY", "IWM")) {
    throw "CandidateSymbol must be a Hunter candidate distinct from SPY and IWM."
}

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$observerModule = Join-Path $ProjectRoot "momentum_hunter\schwab_candle_observer.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The isolated project Python executable is unavailable."
}
if (-not (Test-Path -LiteralPath $observerModule -PathType Leaf)) {
    throw "The Schwab candle observer module is unavailable."
}

$arguments = @(
    "-B",
    "-m",
    "momentum_hunter.schwab_candle_observer",
    "--symbols",
    "SPY",
    "IWM",
    $candidate,
    "--expected-account-ending",
    "2573",
    "--duration-seconds",
    $DurationSeconds.ToString()
)
if ($AllowExtendedHours) {
    $arguments += "--allow-extended-hours"
}

$originalPythonPath = $env:PYTHONPATH
try {
    $pythonPathEntries = @()
    if ($Execute) {
        if ([string]::IsNullOrWhiteSpace($DependencyRoot)) {
            if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
                throw "LOCALAPPDATA is unavailable for the isolated dependency boundary."
            }
            $DependencyRoot = Join-Path $env:LOCALAPPDATA (
                "MomentumHunter\deps\R031-websocket-client-1.9.0"
            )
        }
        $DependencyRoot = (Resolve-Path -LiteralPath $DependencyRoot).Path
        $websocketPackage = Join-Path $DependencyRoot "websocket\__init__.py"
        if (-not (Test-Path -LiteralPath $websocketPackage -PathType Leaf)) {
            throw "The pinned isolated websocket-client dependency is unavailable."
        }
        if ($DependencyRoot.StartsWith(
            $ProjectRoot,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "The websocket-client dependency must remain outside the repository."
        }

        if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
            if (-not [string]::IsNullOrWhiteSpace($env:OneDrive)) {
                $OutputDirectory = Join-Path $env:OneDrive "Documents\ArgusReviewBundles"
            }
            else {
                $OutputDirectory = Join-Path (
                    [Environment]::GetFolderPath("MyDocuments")
                ) "ArgusReviewBundles"
            }
        }
        $OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
        if ($OutputDirectory.StartsWith(
            $ProjectRoot,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Live candle proof output must remain outside the repository."
        }
        $timestamp = [datetime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
        $outputPath = Join-Path $OutputDirectory (
            "schwab-candle-market-hours-proof-$timestamp-$candidate.json"
        )
        if (Test-Path -LiteralPath $outputPath) {
            throw "The generated candle proof path already exists."
        }
        $arguments += @("--execute", "--output", $outputPath)
        $pythonPathEntries += $DependencyRoot
    }

    # Pin imports to this worktree even when the script is launched elsewhere.
    $pythonPathEntries += $ProjectRoot
    if (-not [string]::IsNullOrWhiteSpace($originalPythonPath)) {
        $pythonPathEntries += $originalPythonPath
    }
    $env:PYTHONPATH = $pythonPathEntries -join [IO.Path]::PathSeparator

    & $python @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $originalPythonPath
}

if ($exitCode -ne 0) {
    throw "The Schwab candle observer failed safely with exit code $exitCode."
}
