[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "B", "C")]
    [string]$Checkpoint,
    [string]$ProjectRoot = "",
    [string]$PythonRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$OutputDirectory = "C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\SESSION-FIDELITY-003-20260812",
    [string]$AlpacaRoot = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-OVERNIGHT-001-readonly-market-data-probe",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedRetryModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedRetryRunnerSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedAdapterSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedAlpacaCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedAlpacaModuleSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PythonRoot = (Resolve-Path -LiteralPath $PythonRoot).Path
$AlpacaRoot = (Resolve-Path -LiteralPath $AlpacaRoot).Path
$python = Join-Path $PythonRoot ".venv\Scripts\python.exe"
$retryModule = Join-Path $ProjectRoot "momentum_hunter\session_fidelity_premarket_retry.py"
$retryRunner = Join-Path $ProjectRoot "tools\run_session_fidelity_premarket_retry.py"
$adapter = Join-Path $ProjectRoot "tools\run_session_fidelity_alpaca.py"

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
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is unavailable."
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $Expected.ToUpperInvariant()) {
        throw "$Label does not match its frozen SHA-256."
    }
}

Assert-CleanCommit -Root $ProjectRoot -Expected $ExpectedGitCommit -Label "Premarket retry worktree"
Assert-FileHash -Path $retryModule -Expected $ExpectedRetryModuleSha256 -Label "Premarket retry module"
Assert-FileHash -Path $retryRunner -Expected $ExpectedRetryRunnerSha256 -Label "Premarket retry runner"
Assert-FileHash -Path $adapter -Expected $ExpectedAdapterSha256 -Label "Repaired Alpaca adapter"
Assert-CleanCommit -Root $AlpacaRoot -Expected $ExpectedAlpacaCommit -Label "Frozen Alpaca probe"
Assert-FileHash -Path (Join-Path $AlpacaRoot "momentum_hunter\alpaca_overnight_probe.py") -Expected $ExpectedAlpacaModuleSha256 -Label "Frozen Alpaca module"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The pinned Python executable is unavailable."
}
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($OutputDirectory.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Premarket retry evidence must remain outside the repository."
}

if (-not $Execute) {
    [ordered]@{
        mode = "PLAN_ONLY"
        taskId = "SESSION-FIDELITY-003"
        checkpoint = $Checkpoint
        expectedGitCommit = $ExpectedGitCommit.ToLowerInvariant()
        outputDirectory = $OutputDirectory
        providerScope = "ALPACA_ONLY"
        serviceChanged = $false
        schedulerChanged = $false
        productionPersistence = $false
        accountRequested = $false
        positionsRequested = $false
        ordersRequested = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json
    exit 0
}

$outputPath = Join-Path $OutputDirectory "checkpoint-$($Checkpoint.ToLowerInvariant())-alpaca.json"
$logPath = Join-Path $OutputDirectory "checkpoint-$($Checkpoint.ToLowerInvariant())-retry.log"
$arguments = @(
    "-B", $retryRunner,
    "--checkpoint", $Checkpoint,
    "--project-root", $ProjectRoot,
    "--source-root", $AlpacaRoot,
    "--output", $outputPath
)
$startedAt = [datetime]::UtcNow.ToString("o")
$output = & $python @arguments 2>&1
$exitCode = $LASTEXITCODE
Add-Content -LiteralPath $logPath -Encoding utf8 -Value @(
    "[$startedAt] taskId=SESSION-FIDELITY-003 checkpoint=$Checkpoint commit=$($ExpectedGitCommit.ToLowerInvariant())",
    ($output | Out-String).TrimEnd(),
    "[$([datetime]::UtcNow.ToString('o'))] exitCode=$exitCode"
)
$output | Write-Output
if ($exitCode -ne 0) {
    throw "The read-only premarket retry failed safely with exit code $exitCode."
}
