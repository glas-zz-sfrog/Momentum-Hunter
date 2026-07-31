[CmdletBinding()]
param(
    [ValidateRange(5, 15)][int]$LeadMinutes = 5,
    [datetime]$CanaryAt = [datetime]::MinValue,
    [string]$ProjectRoot = "",
    [string]$PythonExe = "",
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$ServiceName = "MomentumHunterAutomation",
    [string]$ConfirmImmediateReboot = "",
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
$prepareScript = Join-Path $projectPath "tools\prepare_automation_reboot_canary.ps1"
$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$statePath = Join-Path $ServiceRoot "state\automation-service-state.json"
$baselinePath = Join-Path $ServiceRoot "state\reboot-canary-baseline.json"

foreach ($path in @($prepareScript, $manifestPath, $statePath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required reboot-canary input is missing: $path"
    }
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$serviceConfig = Get-CimInstance Win32_Service -Filter (
    "Name='$($ServiceName.Replace("'", "''"))'"
)
if (
    -not $service -or
    $service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running -or
    $serviceConfig.StartMode -ne "Auto"
) {
    throw "Automation service must be Running with Automatic startup."
}

$manifestBefore = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$stateBefore = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
$pendingOpeningBefore = @(
    $manifestBefore.jobs | Where-Object {
        $receipt = $stateBefore.jobs.($_.jobId)
        $_.kind -eq "opening_capture" -and
        [bool]$_.enabled -and
        $receipt.status -eq "PENDING" -and
        [datetimeoffset]$_.scheduledAt -gt [datetimeoffset]::Now
    }
)
if (
    $PSBoundParameters.ContainsKey("CanaryAt") -and
    $PSBoundParameters.ContainsKey("LeadMinutes")
) {
    throw "Specify either -CanaryAt or -LeadMinutes, not both."
}
$now = Get-Date
$scheduledCanaryAt = if ($PSBoundParameters.ContainsKey("CanaryAt")) {
    if ($CanaryAt.Kind -eq [DateTimeKind]::Unspecified) {
        [DateTime]::SpecifyKind($CanaryAt, [DateTimeKind]::Local)
    }
    else {
        $CanaryAt.ToLocalTime()
    }
}
else {
    $now.AddMinutes($LeadMinutes)
}
if ($scheduledCanaryAt -lt $now.AddMinutes(3)) {
    throw "The exact canary time must remain at least three minutes ahead."
}
if ($scheduledCanaryAt -gt $now.AddMinutes(15)) {
    throw "The exact canary time cannot be more than fifteen minutes ahead."
}
$prepareArguments = @{
    CanaryAt = $scheduledCanaryAt
    ProjectRoot = $projectPath
    PythonExe = $pythonPath
    ServiceRoot = $ServiceRoot
    ServiceName = $ServiceName
}

if ($PlanOnly) {
    $summary = & $prepareScript @prepareArguments -PlanOnly
    if ($LASTEXITCODE -ne 0) {
        throw "Reboot-canary planning failed."
    }
    [ordered]@{
        classification = "PLAN_ONLY"
        leadMinutes = [math]::Round(
            ($scheduledCanaryAt - $now).TotalMinutes,
            3
        )
        scheduledAt = $scheduledCanaryAt.ToString("o")
        pendingOpeningCaptureJobs = $pendingOpeningBefore.Count
        immediateReboot = $false
        orderTransmission = "UNAVAILABLE"
        planner = (($summary -join [Environment]::NewLine) | ConvertFrom-Json)
    } | ConvertTo-Json -Depth 6
    exit 0
}

if ($ConfirmImmediateReboot -cne "REBOOT NOW") {
    throw (
        "Immediate reboot was not authorized. Re-run only after Steven approves, " +
        "using -ConfirmImmediateReboot 'REBOOT NOW'."
    )
}

$preparedJson = & $prepareScript @prepareArguments
if ($LASTEXITCODE -ne 0) {
    throw "Reboot-canary preparation failed."
}
$prepared = ($preparedJson -join [Environment]::NewLine) | ConvertFrom-Json
if (
    -not $prepared.installed -or
    $prepared.requiresReboot -ne $true -or
    $prepared.requiresNoInteractiveLogin -ne $true -or
    $prepared.shadowJobsEnabled -ne 0 -or
    $prepared.orderTransmission -ne "UNAVAILABLE"
) {
    throw "Prepared reboot-canary summary violated a safety invariant."
}

$deadline = (Get-Date).AddSeconds(20)
$canaryReceipt = $null
$codexReceipt = $null
do {
    Start-Sleep -Milliseconds 250
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $canaryReceipt = $state.jobs.($prepared.canaryJobId)
    $codexReceipt = if ($prepared.codexProbeJobId -eq "NOT_CONFIGURED") {
        $null
    }
    else {
        $state.jobs.($prepared.codexProbeJobId)
    }
    $receiptsReady = (
        $canaryReceipt.status -eq "PENDING" -and
        (
            $prepared.codexProbeJobId -eq "NOT_CONFIGURED" -or
            $codexReceipt.status -eq "PENDING"
        )
    )
} while (-not $receiptsReady -and (Get-Date) -lt $deadline)

if (-not $receiptsReady) {
    throw "The service did not acknowledge every reboot-canary job as PENDING."
}

$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$baseline = Get-Content -Raw -LiteralPath $baselinePath | ConvertFrom-Json
$canaryJob = @($manifest.jobs | Where-Object jobId -eq $prepared.canaryJobId)
$codexJob = @($manifest.jobs | Where-Object jobId -eq $prepared.codexProbeJobId)
$pendingOpeningAfter = @(
    $manifest.jobs | Where-Object {
        $receipt = $state.jobs.($_.jobId)
        $_.kind -eq "opening_capture" -and
        [bool]$_.enabled -and
        $receipt.status -eq "PENDING" -and
        [datetimeoffset]$_.scheduledAt -gt [datetimeoffset]::Now
    }
)
$enabledShadowJobs = @(
    $manifest.jobs | Where-Object {
        $_.kind -eq "shadow_opening" -and [bool]$_.enabled
    }
)
if (
    $canaryJob.Count -ne 1 -or
    -not [bool]$canaryJob[0].enabled -or
    $canaryJob[0].kind -ne "nonmarket_canary" -or
    (
        $prepared.codexProbeJobId -ne "NOT_CONFIGURED" -and
        (
            $codexJob.Count -ne 1 -or
            -not [bool]$codexJob[0].enabled -or
            $codexJob[0].kind -ne "codex_review"
        )
    ) -or
    $pendingOpeningAfter.Count -ne $pendingOpeningBefore.Count -or
    @($baseline.preservedPendingOpeningJobs).Count -ne $pendingOpeningBefore.Count -or
    $enabledShadowJobs.Count -ne 0 -or
    $baseline.orderTransmission -ne "UNAVAILABLE"
) {
    throw "Post-preparation verification failed; Windows will not reboot."
}

$secondsRemaining = (
    [datetimeoffset]$prepared.scheduledAt - [datetimeoffset]::Now
).TotalSeconds
if ($secondsRemaining -lt 180) {
    throw "Less than three minutes remain before the canary; Windows will not reboot."
}

$launchReceiptPath = Join-Path (
    $ServiceRoot
) "state\reboot-canary-launch-receipt.json"
$launchReceipt = [ordered]@{
    schemaVersion = 1
    classification = "VERIFIED_REBOOT_REQUESTED"
    verifiedAt = (Get-Date).ToString("o")
    canaryJobId = $prepared.canaryJobId
    codexProbeJobId = $prepared.codexProbeJobId
    scheduledAt = $prepared.scheduledAt
    secondsRemaining = [math]::Round($secondsRemaining, 3)
    pendingOpeningCaptureJobsPreserved = $pendingOpeningAfter.Count
    serviceStatus = $service.Status.ToString()
    serviceStartMode = $serviceConfig.StartMode
    shadowJobsEnabled = 0
    orderTransmission = "UNAVAILABLE"
    rebootCommand = "shutdown.exe /r /f /t 0"
}
[System.IO.File]::WriteAllText(
    $launchReceiptPath,
    ($launchReceipt | ConvertTo-Json -Depth 5),
    [System.Text.UTF8Encoding]::new($false)
)

$launchReceipt | ConvertTo-Json -Depth 5
& "$env:SystemRoot\System32\shutdown.exe" /r /f /t 0 /d p:0:0 /c (
    "Momentum Hunter verified automation-service reboot canary"
)
if ($LASTEXITCODE -ne 0) {
    throw "Windows rejected the verified reboot request."
}
