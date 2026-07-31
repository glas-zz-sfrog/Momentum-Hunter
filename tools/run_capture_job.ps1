param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("morning", "opening", "evening", "preopen", "shadow", "manual")]
    [string]$Session,
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$PythonExe = "C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe",
    [string]$SelectorProofBundle = "",
    [string]$TaskDefinitionPath = "",
    [string]$Provider = "finviz",
    [string]$Scanner = "Institutional Momentum",
    [switch]$ArmShadowSelector,
    [int]$ShadowRetryCount = 3,
    [int]$ShadowRetryDelaySeconds = 60,
    [int]$OpeningRetryCount = 3,
    [int]$OpeningRetryDelaySeconds = 60
)

$ErrorActionPreference = "Stop"

$logDir = Join-Path $ProjectRoot "MomentumHunterData\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$logPath = Join-Path $logDir "capture-$Session-$timestamp.log"
$outcomeLogPath = Join-Path $logDir "outcomes-$Session-$timestamp.log"
$outcomeStatusPath = Join-Path $logDir "outcomes-$Session-$timestamp.status.json"
$jobPath = Join-Path $ProjectRoot "tools\capture_job.py"
$outcomePath = Join-Path $ProjectRoot "tools\update_outcomes.py"
$retryableInfrastructureExit = 75

try {
    "Momentum Hunter capture started: $(Get-Date -Format o)" | Tee-Object -FilePath $logPath
    "Session: $Session" | Tee-Object -FilePath $logPath -Append
    "ProjectRoot: $ProjectRoot" | Tee-Object -FilePath $logPath -Append
    $captureArguments = @(
        $jobPath,
        "--session", $Session,
        "--provider", $Provider,
        "--scanner", $Scanner
    )
    if ($Session -eq "shadow") {
        if (-not $SelectorProofBundle) {
            throw "Shadow opening requires an explicit selector proof bundle."
        }
        if (-not $TaskDefinitionPath -or -not (Test-Path -LiteralPath $TaskDefinitionPath -PathType Leaf)) {
            throw "Shadow opening requires the exported scheduled-task definition."
        }
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        $taskStream = [System.IO.File]::OpenRead($TaskDefinitionPath)
        try {
            $taskHash = [System.BitConverter]::ToString(
                $sha256.ComputeHash($taskStream)
            ).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $taskStream.Dispose()
            $sha256.Dispose()
        }
        "TaskDefinitionPath: $TaskDefinitionPath" | Tee-Object -FilePath $logPath -Append
        "TaskDefinitionSha256: $taskHash" | Tee-Object -FilePath $logPath -Append
        $captureArguments += "--trigger-shadow-selector"
        $captureArguments += @(
            "--selector-proof-bundle", $SelectorProofBundle,
            "--task-definition", $TaskDefinitionPath
        )
        if (-not $ArmShadowSelector) {
            $captureArguments += "--shadow-opening-proof-only"
        }
    }
    $maximumAttempts = if ($Session -eq "shadow") {
        1 + [Math]::Max(0, $ShadowRetryCount)
    }
    elseif ($Session -eq "opening") {
        1 + [Math]::Max(0, $OpeningRetryCount)
    }
    else {
        1
    }
    $exitCode = 1
    for ($attempt = 1; $attempt -le $maximumAttempts; $attempt++) {
        "OpeningAttempt: $attempt / $maximumAttempts" | Tee-Object -FilePath $logPath -Append
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $PythonExe @captureArguments 2>&1 |
                ForEach-Object { $_.ToString() } |
                Tee-Object -FilePath $logPath -Append
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        "OpeningAttemptExitCode: $exitCode" | Tee-Object -FilePath $logPath -Append
        $retryable = (
            ($Session -eq "shadow" -and $exitCode -eq $retryableInfrastructureExit) -or
            ($Session -eq "opening" -and $exitCode -ne 0)
        )
        if (-not $retryable) {
            break
        }
        if ($attempt -lt $maximumAttempts) {
            "Retrying bounded capture failure without changing capture/report identity." | Tee-Object -FilePath $logPath -Append
            $delaySeconds = if ($Session -eq "opening") {
                $OpeningRetryDelaySeconds
            }
            else {
                $ShadowRetryDelaySeconds
            }
            Start-Sleep -Seconds ([Math]::Max(0, $delaySeconds))
        }
    }
    if ($exitCode -eq 0) {
        "Updating outcomes independently: $(Get-Date -Format o)" | Tee-Object -FilePath $outcomeLogPath
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $PythonExe $outcomePath 2>&1 |
                ForEach-Object { $_.ToString() } |
                Tee-Object -FilePath $outcomeLogPath -Append
            $outcomeExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        @{
            schemaVersion = 1
            session = $Session
            completedAt = (Get-Date -Format o)
            exitCode = $outcomeExitCode
            openingResultPreserved = ($Session -eq "shadow")
        } | ConvertTo-Json | Set-Content -LiteralPath $outcomeStatusPath -Encoding utf8
        "OutcomeUpdateExitCode: $outcomeExitCode" | Tee-Object -FilePath $logPath -Append
        if ($Session -ne "shadow") {
            $exitCode = $outcomeExitCode
        }
        elseif ($outcomeExitCode -ne 0) {
            "WARNING: Shadow outcome update failed after the opening result became immutable; no opening retry will occur." | Tee-Object -FilePath $logPath -Append
        }
    }
    "ExitCode: $exitCode" | Tee-Object -FilePath $logPath -Append
    exit $exitCode
}
catch {
    "ERROR: $($_.Exception.Message)" | Tee-Object -FilePath $logPath -Append
    ($_ | Format-List * -Force | Out-String) | Tee-Object -FilePath $logPath -Append
    exit 1
}
