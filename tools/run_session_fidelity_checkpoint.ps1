[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "B", "C", "E", "F", "G", "H")]
    [string]$Checkpoint,

    [string]$ProjectRoot = "",
    [string]$PythonRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$OutputDirectory = "C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\SESSION-FIDELITY-001-20260810",
    [string]$DependencyRoot = "C:\Users\steve\AppData\Local\MomentumHunter\deps\R031-websocket-client-1.9.0",
    [string]$AlpacaRoot = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-OVERNIGHT-001-readonly-market-data-probe",
    [string]$SchwabOvernightRoot = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-SCHWAB-OVERNIGHT-001-readonly-fidelity-probe",
    [string]$OvernightShim = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-OVERNIGHT-002-midweek-fidelity-replication\tools\run_midweek_overnight_probe.py",

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedRunnerSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedAlpacaCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedAlpacaModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedSchwabOvernightCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedSchwabOvernightModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedOvernightShimCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedOvernightShimSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PythonRoot = (Resolve-Path -LiteralPath $PythonRoot).Path
$DependencyRoot = (Resolve-Path -LiteralPath $DependencyRoot).Path
$AlpacaRoot = (Resolve-Path -LiteralPath $AlpacaRoot).Path
$SchwabOvernightRoot = (Resolve-Path -LiteralPath $SchwabOvernightRoot).Path
$OvernightShim = (Resolve-Path -LiteralPath $OvernightShim).Path
$python = Join-Path $PythonRoot ".venv\Scripts\python.exe"
$module = Join-Path $ProjectRoot "momentum_hunter\session_fidelity.py"
$runner = Join-Path $ProjectRoot "tools\run_session_fidelity_checkpoint.py"

foreach ($required in @($python, $module, $runner)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "A pinned session-fidelity input is unavailable."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $DependencyRoot "websocket\__init__.py") -PathType Leaf)) {
    throw "The pinned websocket dependency is unavailable."
}

function Assert-CleanCommit {
    param([string]$Root, [string]$Expected, [string]$Label)
    $actual = (& git -C $Root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $Expected.ToLowerInvariant()) {
        throw "$Label does not match its frozen Git commit."
    }
    $dirty = & git -C $Root status --porcelain
    if ($LASTEXITCODE -ne 0 -or $dirty) {
        throw "$Label is not clean."
    }
}

function Assert-FileHash {
    param([string]$Path, [string]$Expected, [string]$Label)
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $Expected.ToUpperInvariant()) {
        throw "$Label does not match its frozen SHA-256."
    }
}

Assert-CleanCommit -Root $ProjectRoot -Expected $ExpectedGitCommit -Label "Session-fidelity worktree"
Assert-FileHash -Path $module -Expected $ExpectedModuleSha256 -Label "Session-fidelity module"
Assert-FileHash -Path $runner -Expected $ExpectedRunnerSha256 -Label "Session-fidelity runner"
Assert-CleanCommit -Root $AlpacaRoot -Expected $ExpectedAlpacaCommit -Label "Frozen Alpaca probe"
Assert-FileHash -Path (Join-Path $AlpacaRoot "momentum_hunter\alpaca_overnight_probe.py") -Expected $ExpectedAlpacaModuleSha256 -Label "Frozen Alpaca module"
Assert-CleanCommit -Root $SchwabOvernightRoot -Expected $ExpectedSchwabOvernightCommit -Label "Frozen Schwab overnight probe"
Assert-FileHash -Path (Join-Path $SchwabOvernightRoot "momentum_hunter\schwab_overnight_probe.py") -Expected $ExpectedSchwabOvernightModuleSha256 -Label "Frozen Schwab overnight module"
$OvernightShimRoot = Split-Path -Parent (Split-Path -Parent $OvernightShim)
Assert-CleanCommit -Root $OvernightShimRoot -Expected $ExpectedOvernightShimCommit -Label "Frozen overnight shim"
Assert-FileHash -Path $OvernightShim -Expected $ExpectedOvernightShimSha256 -Label "Frozen overnight shim"

if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($OutputDirectory.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Session-fidelity evidence must remain outside the repository."
}

$arguments = @(
    "-B", $runner,
    "--checkpoint", $Checkpoint,
    "--output-dir", $OutputDirectory,
    "--python", $python,
    "--project-root", $ProjectRoot,
    "--alpaca-root", $AlpacaRoot,
    "--overnight-shim", $OvernightShim,
    "--schwab-overnight-root", $SchwabOvernightRoot
)

if (-not $Execute) {
    [ordered]@{
        mode = "PLAN_ONLY"
        taskId = "SESSION-FIDELITY-001"
        checkpoint = $Checkpoint
        expectedGitCommit = $ExpectedGitCommit.ToLowerInvariant()
        outputDirectory = $OutputDirectory
        serviceChanged = $false
        schedulerChanged = $false
        productionPersistence = $false
        positionsRequested = $false
        ordersRequested = $false
        previewsRequested = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json
    exit 0
}

$logPath = Join-Path $OutputDirectory "checkpoint-$($Checkpoint.ToLowerInvariant()).log"
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = @($DependencyRoot, $ProjectRoot, $oldPythonPath) -join [IO.Path]::PathSeparator
    $startedAt = [datetime]::UtcNow.ToString("o")
    $output = & $python @arguments 2>&1
    $exitCode = $LASTEXITCODE
    Add-Content -LiteralPath $logPath -Encoding utf8 -Value @(
        "[$startedAt] checkpoint=$Checkpoint execute=true commit=$($ExpectedGitCommit.ToLowerInvariant())",
        ($output | Out-String).TrimEnd(),
        "[$([datetime]::UtcNow.ToString('o'))] exitCode=$exitCode"
    )
    $output | Write-Output
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}
if ($exitCode -ne 0) {
    throw "The read-only session-fidelity checkpoint failed safely with exit code $exitCode."
}
