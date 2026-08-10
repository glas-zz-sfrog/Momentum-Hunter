[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("OPEN", "LATE")]
    [string]$AttemptLabel,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedSessionDate,

    [ValidateRange(300, 900)]
    [int]$DurationSeconds = 900,

    [string]$ProjectRoot = "",
    [string]$PythonRoot = "",
    [string]$DependencyRoot = "",
    [string]$OutputDirectory = "",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedModuleSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($PythonRoot)) {
    $PythonRoot = $ProjectRoot
}
$PythonRoot = (Resolve-Path -LiteralPath $PythonRoot).Path
$python = Join-Path $PythonRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The pinned Python executable is unavailable."
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "momentum_hunter\schwab_after_hours_probe.py") -PathType Leaf)) {
    throw "The after-hours probe module is unavailable."
}
$actualCommit = (& git -C $ProjectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $ExpectedGitCommit.ToLowerInvariant()) {
    throw "The after-hours proof worktree does not match its frozen Git commit."
}
$dirty = & git -C $ProjectRoot status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "The after-hours proof worktree is not clean."
}
$modulePath = Join-Path $ProjectRoot "momentum_hunter\schwab_after_hours_probe.py"
$actualModuleSha256 = (Get-FileHash -LiteralPath $modulePath -Algorithm SHA256).Hash
if ($actualModuleSha256 -ne $ExpectedModuleSha256.ToUpperInvariant()) {
    throw "The after-hours probe module does not match its frozen SHA-256."
}
if ([string]::IsNullOrWhiteSpace($DependencyRoot)) {
    $DependencyRoot = Join-Path $env:LOCALAPPDATA "MomentumHunter\deps\R031-websocket-client-1.9.0"
}
$DependencyRoot = (Resolve-Path -LiteralPath $DependencyRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $DependencyRoot "websocket\__init__.py") -PathType Leaf)) {
    throw "The pinned websocket-client dependency is unavailable."
}
if ($DependencyRoot.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The websocket dependency must remain outside the repository."
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $env:OneDrive "Documents\ArgusReviewBundles"
}
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($OutputDirectory.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "After-hours proof output must remain outside the repository."
}

$label = $AttemptLabel.ToLowerInvariant()
$outputPath = Join-Path $OutputDirectory "schwab-after-hours-$label-$ExpectedSessionDate.json"
$logPath = Join-Path $OutputDirectory "schwab-after-hours-$label-$ExpectedSessionDate.log"
$arguments = @(
    "-P", "-B", "-m", "momentum_hunter.schwab_after_hours_probe",
    "--output", $outputPath,
    "--expected-session-date", $ExpectedSessionDate,
    "--attempt-label", $AttemptLabel,
    "--duration-seconds", $DurationSeconds.ToString()
)
if (Test-Path -LiteralPath $outputPath -PathType Leaf) {
    $arguments += "--verify-existing"
}

if (-not $Execute) {
    [ordered]@{
        mode = "PLAN_ONLY"
        attemptLabel = $AttemptLabel
        expectedSessionDate = $ExpectedSessionDate
        durationSeconds = $DurationSeconds
        expectedGitCommit = $ExpectedGitCommit.ToLowerInvariant()
        expectedModuleSha256 = $ExpectedModuleSha256.ToUpperInvariant()
        outputPath = $outputPath
        logPath = $logPath
        positionsRequested = $false
        ordersRequested = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json
    exit 0
}

$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = @($DependencyRoot, $ProjectRoot, $oldPythonPath) -join [IO.Path]::PathSeparator
    $startedAt = [datetime]::UtcNow.ToString("o")
    $output = & $python @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $lines = @(
        "[$startedAt] attempt=$AttemptLabel execute=true commit=$($ExpectedGitCommit.ToLowerInvariant()) moduleSha256=$($ExpectedModuleSha256.ToUpperInvariant())",
        ($output | Out-String).TrimEnd(),
        "[$([datetime]::UtcNow.ToString('o'))] exitCode=$exitCode"
    )
    Add-Content -LiteralPath $logPath -Value $lines -Encoding utf8
    $output | Write-Output
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}
if ($exitCode -ne 0) {
    throw "The read-only after-hours probe failed safely with exit code $exitCode."
}
