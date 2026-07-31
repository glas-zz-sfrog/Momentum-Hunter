[CmdletBinding()]
param(
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$ServiceName = "MomentumHunterAutomation",
    [string]$WakeTaskName = "Momentum Hunter Automation Readiness Wake"
)

$ErrorActionPreference = "Stop"

$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$statePath = Join-Path $ServiceRoot "state\automation-service-state.json"
$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$serviceConfig = Get-CimInstance Win32_Service -Filter (
    "Name='$($ServiceName.Replace("'", "''"))'"
) -ErrorAction SilentlyContinue
$wakeTaskErrors = @()
$wakeTask = Get-ScheduledTask -TaskName $WakeTaskName `
    -ErrorAction SilentlyContinue `
    -ErrorVariable wakeTaskErrors
$wakeTaskInfoErrors = @()
$wakeTaskInfo = Get-ScheduledTaskInfo -TaskName $WakeTaskName `
    -ErrorAction SilentlyContinue `
    -ErrorVariable wakeTaskInfoErrors
$wakeTaskAccessDenied = [bool](
    @($wakeTaskErrors) + @($wakeTaskInfoErrors) |
        Where-Object { $_.Exception.Message -match "Access is denied" }
)
$wakeTaskPresent = [bool]$wakeTask -or $wakeTaskAccessDenied
$manifest = if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
}
else {
    $null
}
$state = if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
}
else {
    $null
}
$jobs = @()
if ($manifest) {
    $jobs = @($manifest.jobs | ForEach-Object {
        $receipt = if ($state -and $state.jobs) {
            $state.jobs.($_.jobId)
        }
        else {
            $null
        }
        [ordered]@{
            jobId = $_.jobId
            kind = $_.kind
            enabled = [bool]$_.enabled
            scheduledAt = $_.scheduledAt
            latestStartAt = $_.latestStartAt
            status = if ($receipt) { $receipt.status } else { "NOT_OBSERVED" }
            reason = if ($receipt) { $receipt.reason } else { "" }
        }
    })
}
$shadowEnabled = @(
    $jobs | Where-Object {
        $_.kind -eq "shadow_opening" -and $_.enabled
    }
).Count

[ordered]@{
    serviceName = $ServiceName
    installed = [bool]$service
    status = if ($service) { $service.Status.ToString() } else { "NOT_INSTALLED" }
    startMode = if ($serviceConfig) { $serviceConfig.StartMode } else { "" }
    startName = if ($serviceConfig) { $serviceConfig.StartName } else { "" }
    processId = if ($serviceConfig) { $serviceConfig.ProcessId } else { 0 }
    wakeTaskName = $WakeTaskName
    wakeTaskPresent = $wakeTaskPresent
    wakeTaskVisibility = if ($wakeTask) {
        "VISIBLE"
    }
    elseif ($wakeTaskAccessDenied) {
        "PRESENT_REQUIRES_ELEVATION"
    }
    else {
        "NOT_FOUND"
    }
    wakeTaskState = if ($wakeTask) {
        $wakeTask.State.ToString()
    }
    elseif ($wakeTaskAccessDenied) {
        "PRESENT_REQUIRES_ELEVATION"
    }
    else {
        ""
    }
    wakeToRun = if ($wakeTask) {
        [bool]$wakeTask.Settings.WakeToRun
    }
    else {
        $null
    }
    wakeTaskPrincipal = if ($wakeTask) {
        $wakeTask.Principal.UserId
    }
    else {
        ""
    }
    wakeTaskNextRunAt = if ($wakeTaskInfo) {
        $wakeTaskInfo.NextRunTime.ToString("o")
    }
    else {
        ""
    }
    manifestPresent = [bool]$manifest
    statePresent = [bool]$state
    lastHeartbeatAt = if ($state) { $state.last_heartbeat_at } else { "" }
    engineHostState = if ($state) { $state.engine_host_state } else { "UNKNOWN" }
    engineHostDetail = if ($state) { $state.engine_host_detail } else { "" }
    codexHeadlessConfigured = [bool](
        $manifest -and
        $manifest.codexExecutable -and
        (Test-Path -LiteralPath $manifest.codexExecutable -PathType Leaf)
    )
    jobs = $jobs
    shadowJobsEnabled = $shadowEnabled
    orderTransmission = "UNAVAILABLE"
} | ConvertTo-Json -Depth 8
