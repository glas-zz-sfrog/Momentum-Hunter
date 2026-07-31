[CmdletBinding()]
param(
    [string]$WakeTaskName = "Momentum Hunter Automation Readiness Wake",
    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$WakeTime = "08:15",
    [switch]$RunNow,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

$startupDelayMinutes = 2
$startupDelayIso = "PT$($startupDelayMinutes)M"
$finalResyncTime = (
    [DateTime]::ParseExact(
        $WakeTime,
        "HH:mm",
        [Globalization.CultureInfo]::InvariantCulture
    ).AddMinutes(10).ToString("HH:mm")
)

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Confirm-WakeTaskConfiguration {
    param(
        [Parameter(Mandatory)]
        [object]$Task,
        [Parameter(Mandatory)]
        [string]$PrimaryTime,
        [Parameter(Mandatory)]
        [string]$FinalTime,
        [Parameter(Mandatory)]
        [string]$StartupDelay
    )

    if ($Task.Principal.UserId -notin @("SYSTEM", "S-1-5-18")) {
        throw "Installed wake task principal is not SYSTEM."
    }
    $actions = @($Task.Actions)
    if ($actions.Count -ne 1) {
        throw "Installed wake task action count is unexpected."
    }
    $action = $actions[0]
    if (
        [System.IO.Path]::GetFileName([string]$action.Execute) -ine "w32tm.exe" -or
        ([string]$action.Arguments).Trim() -ine "/resync /rediscover"
    ) {
        throw "Installed wake task action is not the expected time resync."
    }

    $bootTriggers = @(
        $Task.Triggers |
            Where-Object { $_.CimClass.CimClassName -eq "MSFT_TaskBootTrigger" }
    )
    $dailyTriggers = @(
        $Task.Triggers |
            Where-Object { $_.CimClass.CimClassName -eq "MSFT_TaskDailyTrigger" }
    )
    if (
        $bootTriggers.Count -ne 1 -or
        [string]$bootTriggers[0].Delay -ne $StartupDelay
    ) {
        throw "Installed wake task startup trigger is missing or has the wrong delay."
    }
    if ($dailyTriggers.Count -ne 2) {
        throw "Installed wake task must have exactly two daily resync triggers."
    }
    $dailyTimes = @(
        $dailyTriggers |
            ForEach-Object {
                [DateTimeOffset]::Parse(
                    [string]$_.StartBoundary
                ).ToLocalTime().ToString("HH:mm")
            } |
            Sort-Object
    )
    $expectedTimes = @($PrimaryTime, $FinalTime) | Sort-Object
    if (Compare-Object -ReferenceObject $expectedTimes -DifferenceObject $dailyTimes) {
        throw "Installed wake task daily trigger times are unexpected."
    }
    if (
        -not [bool]$Task.Settings.WakeToRun -or
        [bool]$Task.Settings.StartWhenAvailable -or
        [int]$Task.Settings.RestartCount -ne 5 -or
        [string]$Task.Settings.RestartInterval -ne "PT2M"
    ) {
        throw "Installed wake task settings do not match the fail-closed plan."
    }

    return [ordered]@{
        validated = $true
        principal = "SYSTEM"
        action = "w32tm.exe /resync /rediscover"
        startupDelay = $StartupDelay
        dailyTimes = $dailyTimes
        wakeToRun = $true
        startWhenAvailable = $false
        restartCount = 5
        restartInterval = "PT2M"
    }
}

$plan = [ordered]@{
    schemaVersion = 1
    taskName = $WakeTaskName
    principal = "SYSTEM"
    action = "w32tm.exe /resync /rediscover"
    triggers = @(
        "AT_STARTUP_DELAY_$($startupDelayMinutes)_MINUTES",
        "DAILY_$($WakeTime.Replace(':', '_'))",
        "DAILY_$($finalResyncTime.Replace(':', '_'))"
    )
    startupDelayMinutes = $startupDelayMinutes
    finalResyncTime = $finalResyncTime
    wakeToRun = $true
    startWhenAvailable = $false
    restartCount = 5
    restartIntervalMinutes = 2
    runNow = [bool]$RunNow
    createsIfMissing = $true
    deletesTask = $false
    orderTransmission = "UNAVAILABLE"
}

if ($PlanOnly) {
    $planAction = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\w32tm.exe" `
        -Argument "/resync /rediscover"
    $planStartupTrigger = New-ScheduledTaskTrigger -AtStartup
    $planStartupTrigger.Delay = $startupDelayIso
    $planTriggers = @(
        $planStartupTrigger,
        (New-ScheduledTaskTrigger -Daily -At $WakeTime),
        (New-ScheduledTaskTrigger -Daily -At $finalResyncTime)
    )
    $planPrincipal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
    $planSettings = New-ScheduledTaskSettingsSet `
        -WakeToRun `
        -MultipleInstances IgnoreNew `
        -RestartCount 5 `
        -RestartInterval ([TimeSpan]::FromMinutes(2)) `
        -ExecutionTimeLimit ([TimeSpan]::FromMinutes(15))
    $planTask = New-ScheduledTask `
        -Action $planAction `
        -Trigger $planTriggers `
        -Principal $planPrincipal `
        -Settings $planSettings
    $plan.taskShapeValidation = Confirm-WakeTaskConfiguration `
        -Task $planTask `
        -PrimaryTime $WakeTime `
        -FinalTime $finalResyncTime `
        -StartupDelay $startupDelayIso
    $plan | ConvertTo-Json -Depth 4
    exit 0
}

if (-not (Test-IsAdministrator)) {
    throw "Clock-task hardening requires an elevated PowerShell session."
}

$lookupErrors = @()
$existing = Get-ScheduledTask -TaskName $WakeTaskName `
    -ErrorAction SilentlyContinue `
    -ErrorVariable lookupErrors
$lookupBlocked = [bool](
    @($lookupErrors) |
        Where-Object { $_.Exception.Message -match "Access is denied" }
)
if ($lookupBlocked) {
    throw "Existing wake task cannot be inspected without elevation."
}
if ($existing) {
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
}

$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\w32tm.exe" `
    -Argument "/resync /rediscover"
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$startupTrigger.Delay = $startupDelayIso
$triggers = @(
    $startupTrigger,
    (New-ScheduledTaskTrigger -Daily -At $WakeTime),
    (New-ScheduledTaskTrigger -Daily -At $finalResyncTime)
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

$taskCreated = -not [bool]$existing
if ($taskCreated) {
    Register-ScheduledTask `
        -TaskName $WakeTaskName `
        -Action $action `
        -Trigger $triggers `
        -Principal $principal `
        -Settings $settings | Out-Null
}
else {
    Set-ScheduledTask `
        -TaskName $WakeTaskName `
        -Action $action `
        -Trigger $triggers `
        -Principal $principal `
        -Settings $settings | Out-Null
}

$installedTask = Get-ScheduledTask -TaskName $WakeTaskName
$installedConfiguration = Confirm-WakeTaskConfiguration `
    -Task $installedTask `
    -PrimaryTime $WakeTime `
    -FinalTime $finalResyncTime `
    -StartupDelay $startupDelayIso

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
    taskCreated = $taskCreated
    taskName = $WakeTaskName
    principal = "SYSTEM"
    action = "w32tm.exe /resync /rediscover"
    startupTrigger = $true
    startupDelayMinutes = $startupDelayMinutes
    dailyWakeTime = $WakeTime
    finalResyncTime = $finalResyncTime
    installedConfiguration = $installedConfiguration
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
