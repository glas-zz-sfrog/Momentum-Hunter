[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$PythonExe = "",
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$ServiceName = "MomentumHunterAutomation",
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$projectPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $PythonExe) {
    $PythonExe = Join-Path $projectPath ".venv\Scripts\python.exe"
}
$pythonPath = (Resolve-Path -LiteralPath $PythonExe).Path
$stateDirectory = Join-Path $ServiceRoot "state"
$baselinePath = Join-Path $stateDirectory "reboot-canary-baseline.json"
$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$statePath = Join-Path $stateDirectory "automation-service-state.json"
$verifier = Join-Path $projectPath "tools\verify_automation_reboot_canary.ps1"
foreach ($path in @($baselinePath, $manifestPath, $statePath, $verifier)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required reboot-canary evidence is missing: $path"
    }
}

$verificationText = & powershell.exe `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File $verifier `
    -ProjectRoot $projectPath `
    -PythonExe $pythonPath `
    -ServiceRoot $ServiceRoot `
    -ServiceName $ServiceName
if ($LASTEXITCODE -ne 0) {
    throw "Reboot canary did not verify; canonical evidence was preserved."
}
$verification = ($verificationText -join [Environment]::NewLine) |
    ConvertFrom-Json
if ($verification.classification -ne "PASS") {
    throw "Only a verified PASS reboot canary may be archived."
}
$baseline = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
$canaryJobId = [string]$baseline.canaryJobId
if ($canaryJobId -notmatch "^[a-z0-9-]+$") {
    throw "Reboot canary identifier is unsafe for an archive path."
}
$archiveRoot = Join-Path $stateDirectory "reboot-canary-attempts"
$archivePath = Join-Path $archiveRoot "$canaryJobId-pass"
if (Test-Path -LiteralPath $archivePath) {
    throw "Reboot canary archive already exists: $archivePath"
}

$plan = [ordered]@{
    classification = "PASS_READY_TO_ARCHIVE"
    canaryJobId = $canaryJobId
    archivePath = $archivePath
    baselineWillBeMoved = $true
    evidenceWillBeDeleted = $false
    orderTransmission = "UNAVAILABLE"
}
if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 4
    exit 0
}

New-Item -ItemType Directory -Path $archivePath | Out-Null
Copy-Item -LiteralPath $manifestPath -Destination (
    Join-Path $archivePath "automation-manifest.json"
)
Copy-Item -LiteralPath $statePath -Destination (
    Join-Path $archivePath "automation-service-state.json"
)
[System.IO.File]::WriteAllText(
    (Join-Path $archivePath "verification.json"),
    (($verification | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
    [System.Text.UTF8Encoding]::new($false)
)

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
foreach ($jobId in @($baseline.canaryJobId, $baseline.codexProbeJobId)) {
    if (-not $jobId) {
        continue
    }
    $receipt = $state.jobs.$jobId
    if (-not $receipt -or -not $receipt.log_path) {
        throw "Verified reboot receipt log path is missing for $jobId."
    }
    $logPath = [string]$receipt.log_path
    if (-not (Test-Path -LiteralPath $logPath -PathType Leaf)) {
        throw "Verified reboot receipt log is missing for $jobId."
    }
    Copy-Item -LiteralPath $logPath -Destination $archivePath
}

$hashes = @(
    Get-ChildItem -LiteralPath $archivePath -File |
        Sort-Object Name |
        ForEach-Object {
            [ordered]@{
                file = $_.Name
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
                size = $_.Length
            }
        }
)
[System.IO.File]::WriteAllText(
    (Join-Path $archivePath "archive-manifest.json"),
    (([ordered]@{
        schemaVersion = 1
        classification = "PASS_ARCHIVED"
        canaryJobId = $canaryJobId
        archivedAt = (Get-Date -Format o)
        files = $hashes
        evidenceDeleted = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json -Depth 6) + [Environment]::NewLine),
    [System.Text.UTF8Encoding]::new($false)
)

Move-Item -LiteralPath $baselinePath -Destination (
    Join-Path $archivePath "reboot-canary-baseline.retired.json"
)

[ordered]@{
    archived = $true
    classification = "PASS_ARCHIVED"
    canaryJobId = $canaryJobId
    archivePath = $archivePath
    canonicalBaselinePresent = Test-Path -LiteralPath $baselinePath
    evidenceDeleted = $false
    orderTransmission = "UNAVAILABLE"
} | ConvertTo-Json -Depth 4
