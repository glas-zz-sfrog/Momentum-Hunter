[CmdletBinding()]
param(
    [Parameter(Mandatory)][datetime]$CanaryAt,
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
$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$stateDirectory = Join-Path $ServiceRoot "state"
$statePath = Join-Path $stateDirectory "automation-service-state.json"
$baselinePath = Join-Path $stateDirectory "reboot-canary-baseline.json"
foreach ($path in @($manifestPath, $statePath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required automation-service evidence is missing: $path"
    }
}
if (Test-Path -LiteralPath $baselinePath -PathType Leaf) {
    throw (
        "A reboot-canary baseline already exists. Verify or preserve that " +
        "attempt before preparing another one."
    )
}

$preparedAt = Get-Date
$bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$arguments = @(
    "-B",
    "-m",
    "momentum_hunter.automation_reboot_canary",
    "plan",
    "--manifest",
    $manifestPath,
    "--state",
    $statePath,
    "--scheduled-at",
    $CanaryAt.ToString("o"),
    "--prepared-at",
    $preparedAt.ToString("o"),
    "--pre-reboot-boot-time",
    $bootTime.ToString("o"),
    "--baseline",
    $baselinePath
)
Push-Location -LiteralPath $projectPath
try {
    $planJson = & $pythonPath @arguments
    $planExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
if ($planExitCode -ne 0) {
    throw "Reboot-canary planning failed: $($planJson -join [Environment]::NewLine)"
}
$plan = ($planJson -join [Environment]::NewLine) | ConvertFrom-Json
if ($plan.summary.shadowJobsEnabled -ne 0) {
    throw "Reboot-canary planning unexpectedly enabled a Shadow job."
}
if ($plan.summary.orderTransmission -ne "UNAVAILABLE") {
    throw "Reboot-canary planning changed the transmission boundary."
}

if ($PlanOnly) {
    $plan.summary | ConvertTo-Json -Depth 6
    exit 0
}
$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $service) {
    throw "Automation service $ServiceName is not installed."
}
$serviceConfig = Get-CimInstance Win32_Service -Filter (
    "Name='$($ServiceName.Replace("'", "''"))'"
)
if (
    $service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running -or
    $serviceConfig.StartMode -ne "Auto"
) {
    throw "Automation service must be Running with Automatic startup."
}

$backupPath = "$manifestPath.$($preparedAt.ToString('yyyyMMddTHHmmss')).bak"
Copy-Item -LiteralPath $manifestPath -Destination $backupPath
$temporaryManifest = "$manifestPath.$([guid]::NewGuid().ToString('N')).tmp"
$temporaryBaseline = "$baselinePath.$([guid]::NewGuid().ToString('N')).tmp"
try {
    [System.IO.File]::WriteAllText(
        $temporaryManifest,
        ($plan.manifest | ConvertTo-Json -Depth 10),
        [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::WriteAllText(
        $temporaryBaseline,
        ($plan.baseline | ConvertTo-Json -Depth 6),
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporaryBaseline -Destination $baselinePath
    Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force
}
catch {
    if (Test-Path -LiteralPath $temporaryManifest) {
        Remove-Item -LiteralPath $temporaryManifest -Force
    }
    if (Test-Path -LiteralPath $temporaryBaseline) {
        Remove-Item -LiteralPath $temporaryBaseline -Force
    }
    throw
}

[ordered]@{
    installed = $true
    serviceName = $ServiceName
    serviceStatus = $service.Status.ToString()
    serviceStartMode = $serviceConfig.StartMode
    manifestPath = $manifestPath
    baselinePath = $baselinePath
    previousManifest = $backupPath
    canaryJobId = $plan.summary.canaryJobId
    codexProbeJobId = $plan.summary.codexProbeJobId
    scheduledAt = $plan.summary.scheduledAt
    latestStartAt = $plan.summary.latestStartAt
    serviceRestarted = $false
    requiresReboot = $true
    requiresNoInteractiveLogin = $true
    shadowJobsEnabled = 0
    orderTransmission = "UNAVAILABLE"
} | ConvertTo-Json -Depth 5
