[CmdletBinding()]
param(
    [string]$WakeTaskName = "Momentum Hunter Automation Readiness Wake",
    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$WakeTime = "08:15",
    [switch]$RunNow,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

$plan = [ordered]@{
    schemaVersion = 1
    taskName = $WakeTaskName
    principal = "SYSTEM"
    action = "w32tm.exe /resync /rediscover"
    triggers = @("AT_STARTUP", "DAILY_$($WakeTime.Replace(':', '_'))")
    wakeToRun = $true
    startWhenAvailable = $false
    restartCount = 5
    restartIntervalMinutes = 2
    runNow = [bool]$RunNow
    deletesTask = $false
    orderTransmission = "UNAVAILABLE"
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 4
    exit 0
}

if (-not (Test-IsAdministrator)) {
    throw "Clock-task hardening requires an elevated PowerShell session."
}

$existing = Get-ScheduledTask -TaskName $WakeTaskName -ErrorAction Stop
if ($existing.Principal.UserId -notin @("SYSTEM", "S-1-5-18")) {
    throw "Existing wake task principal is not SYSTEM; refusing to alter it."
}
if (@($existing.Actions).Count -ne 1) {
    throw "Existing wake task action count is unexpected; refusing to alter it."
}
$existingAction = @($existing.Actions)[0]
$existingExecute = [string]$existingAction.Execute
$existingArguments = [string]$existingAction.Arguments
$isExpectedNoOp = (
    [System.IO.Path]::GetFileName($existingExecute) -ieq "cmd.exe" -and
    $existingArguments.Trim() -ieq "/d /c exit 0"
)
$isExpectedTimeSync = (
    [System.IO.Path]::GetFileName($existingExecute) -ieq "w32tm.exe" -and
    $existingArguments.Trim() -ieq "/resync /rediscover"
)
if (-not ($isExpectedNoOp -or $isExpectedTimeSync)) {
    throw "Existing wake task action is unexpected; refusing to alter it."
}

$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\w32tm.exe" `
    -Argument "/resync /rediscover"
$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -Daily -At $WakeTime)
)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 5 `
    -RestartInterval ([TimeSpan]::FromMinutes(2)) `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(15))

Set-ScheduledTask `
    -TaskName $WakeTaskName `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings | Out-Null

$lastTaskResult = $null
$clockSource = "NOT_CHECKED"
$clockSynchronized = $null
if ($RunNow) {
    $before = Get-ScheduledTaskInfo -TaskName $WakeTaskName
    Start-ScheduledTask -TaskName $WakeTaskName
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 500
        $task = Get-ScheduledTask -TaskName $WakeTaskName
        $info = Get-ScheduledTaskInfo -TaskName $WakeTaskName
        $newRunObserved = $info.LastRunTime -gt $before.LastRunTime
    } while (
        ($task.State -eq "Running" -or -not $newRunObserved) -and
        (Get-Date) -lt $deadline
    )
    if ($task.State -eq "Running" -or -not $newRunObserved) {
        throw "Windows Time resync task did not finish within 45 seconds."
    }
    $lastTaskResult = $info.LastTaskResult
    if ($lastTaskResult -ne 0) {
        throw "Windows Time resync task failed with result $lastTaskResult."
    }
    $clockSource = (& "$env:SystemRoot\System32\w32tm.exe" /query /source).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Windows Time source query failed after resync."
    }
    $clockStatus = & "$env:SystemRoot\System32\w32tm.exe" /query /status
    if ($LASTEXITCODE -ne 0) {
        throw "Windows Time status query failed after resync."
    }
    $clockSynchronized = (
        ($clockStatus -match "Leap Indicator:\s+0") -and
        ($clockSource -notmatch "Local CMOS Clock")
    )
    if (-not $clockSynchronized) {
        throw "Windows Time remains unsynchronized after the resync task."
    }
}

[ordered]@{
    hardened = $true
    taskName = $WakeTaskName
    principal = "SYSTEM"
    action = "w32tm.exe /resync /rediscover"
    startupTrigger = $true
    dailyWakeTime = $WakeTime
    wakeToRun = $true
    restartCount = 5
    restartIntervalMinutes = 2
    runNow = [bool]$RunNow
    lastTaskResult = $lastTaskResult
    clockSynchronized = $clockSynchronized
    clockSource = $clockSource
    taskDeleted = $false
    orderTransmission = "UNAVAILABLE"
} | ConvertTo-Json -Depth 4
