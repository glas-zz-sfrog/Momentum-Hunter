param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("morning", "evening", "manual")]
    [string]$Session,
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$PythonExe = "C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

$logDir = Join-Path $ProjectRoot "MomentumHunterData\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$logPath = Join-Path $logDir "capture-$Session-$timestamp.log"
$jobPath = Join-Path $ProjectRoot "tools\capture_job.py"
$outcomePath = Join-Path $ProjectRoot "tools\update_outcomes.py"

try {
    "Momentum Hunter capture started: $(Get-Date -Format o)" | Tee-Object -FilePath $logPath
    "Session: $Session" | Tee-Object -FilePath $logPath -Append
    "ProjectRoot: $ProjectRoot" | Tee-Object -FilePath $logPath -Append
    & $PythonExe $jobPath --session $Session 2>&1 | Tee-Object -FilePath $logPath -Append
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        "Updating outcomes: $(Get-Date -Format o)" | Tee-Object -FilePath $logPath -Append
        & $PythonExe $outcomePath 2>&1 | Tee-Object -FilePath $logPath -Append
        $exitCode = $LASTEXITCODE
    }
    "ExitCode: $exitCode" | Tee-Object -FilePath $logPath -Append
    exit $exitCode
}
catch {
    "ERROR: $($_.Exception.Message)" | Tee-Object -FilePath $logPath -Append
    ($_ | Format-List * -Force | Out-String) | Tee-Object -FilePath $logPath -Append
    exit 1
}
