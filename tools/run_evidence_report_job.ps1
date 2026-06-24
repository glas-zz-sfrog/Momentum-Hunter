param(
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$PythonExe = "C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe",
    [ValidateSet("evidence", "reliability", "both")]
    [string]$ReportKind = "evidence"
)

$ErrorActionPreference = "Stop"

$logDir = Join-Path $ProjectRoot "MomentumHunterData\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "evidence-report-$ReportKind-$stamp.log"

Set-Location $ProjectRoot

try {
    & $PythonExe -m momentum_hunter.evidence_health --report-kind $ReportKind *> $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Evidence report job failed with exit code $exitCode. See $logPath"
    }
    Add-Content -Path $logPath -Value "Evidence report job completed successfully at $(Get-Date -Format o)."
}
catch {
    Add-Content -Path $logPath -Value "Evidence report job failed at $(Get-Date -Format o): $($_.Exception.Message)"
    throw
}
