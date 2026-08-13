[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("BOUNDARY", "ACTIVE")]
    [string]$Checkpoint,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$SessionDate,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$ProjectRoot = "",
    [string]$PythonRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$DependencyRoot = "C:\Users\steve\AppData\Local\MomentumHunter\deps\R031-websocket-client-1.9.0",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedRunnerSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PythonRoot = (Resolve-Path -LiteralPath $PythonRoot).Path
$DependencyRoot = (Resolve-Path -LiteralPath $DependencyRoot).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$python = Join-Path $PythonRoot ".venv\Scripts\python.exe"
$module = Join-Path $ProjectRoot "momentum_hunter\schwab_premarket_fidelity.py"
$runner = Join-Path $ProjectRoot "tools\run_schwab_premarket_fidelity.py"

foreach ($required in @($python, $module, $runner, (Join-Path $DependencyRoot "websocket\__init__.py"))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "A pinned Schwab premarket input is unavailable."
    }
}
if ($OutputDirectory.StartsWith($ProjectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Schwab premarket evidence must remain outside the repository."
}
$actualCommit = (& git -C $ProjectRoot rev-parse HEAD).Trim()
$dirty = & git -C $ProjectRoot status --porcelain
if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $ExpectedGitCommit.ToLowerInvariant() -or $dirty) {
    throw "The Schwab premarket worktree does not match its pinned clean commit."
}
if ((Get-FileHash -LiteralPath $module -Algorithm SHA256).Hash -ne $ExpectedModuleSha256.ToUpperInvariant()) {
    throw "The Schwab premarket module hash changed."
}
if ((Get-FileHash -LiteralPath $runner -Algorithm SHA256).Hash -ne $ExpectedRunnerSha256.ToUpperInvariant()) {
    throw "The Schwab premarket runner hash changed."
}

if (-not $Execute) {
    [ordered]@{
        mode = "PLAN_ONLY"
        taskId = "SESSION-FIDELITY-008"
        checkpoint = $Checkpoint
        sessionDate = $SessionDate
        providerScope = "SCHWAB_ONLY"
        productionPersistence = $false
        positionsRequested = $false
        ordersRequested = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json
    exit 0
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$output = Join-Path $OutputDirectory (
    "checkpoint-schwab-premarket-$SessionDate-$($Checkpoint.ToLowerInvariant()).json"
)
$arguments = @(
    "-B", $runner,
    "--checkpoint", $Checkpoint,
    "--session-date", $SessionDate,
    "--output", $output
)
if (Test-Path -LiteralPath $output -PathType Leaf) {
    $arguments += "--verify-existing"
}
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = @($DependencyRoot, $ProjectRoot, $oldPythonPath) -join [IO.Path]::PathSeparator
    $result = & $python @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $log = Join-Path $OutputDirectory (
        "checkpoint-schwab-premarket-$SessionDate-$($Checkpoint.ToLowerInvariant()).log"
    )
    Add-Content -LiteralPath $log -Encoding utf8 -Value @(
        "[$([datetime]::UtcNow.ToString('o'))] checkpoint=$Checkpoint provider=SCHWAB commit=$($ExpectedGitCommit.ToLowerInvariant())",
        ($result | Out-String).TrimEnd(),
        "[$([datetime]::UtcNow.ToString('o'))] exitCode=$exitCode"
    )
    $result | Write-Output
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}
if ($exitCode -ne 0) {
    throw "The Schwab premarket checkpoint failed safely with exit code $exitCode."
}
