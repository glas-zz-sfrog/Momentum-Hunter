[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$PythonRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$OutputDirectory = "C:\Users\steve\OneDrive\Documents\ArgusReviewBundles",
    [string]$ExpectedSessionDate = "2026-08-11",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedModuleSha256,
    [switch]$ReplaceExisting,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PythonRoot = (Resolve-Path -LiteralPath $PythonRoot).Path
$runner = Join-Path $ProjectRoot "tools\run_schwab_after_hours_probe.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "The after-hours task runner is unavailable."
}
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path

$expectedDate = [datetime]::ParseExact(
    $ExpectedSessionDate,
    "yyyy-MM-dd",
    [Globalization.CultureInfo]::InvariantCulture
)
if ($ExpectedSessionDate -ne "2026-08-11") {
    throw "This frozen installer is limited to the Tuesday 2026-08-11 proof."
}
if ($expectedDate.Date -le [datetime]::Today) {
    throw "The scheduled after-hours proof date must be in the future."
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 25) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 2)

$definitions = @(
    [ordered]@{
        Name = "Momentum Hunter Schwab After Hours Open Proof 20260811"
        Label = "OPEN"
        Time = $expectedDate.Date.AddHours(15).AddMinutes(5)
    },
    [ordered]@{
        Name = "Momentum Hunter Schwab After Hours Late Proof 20260811"
        Label = "LATE"
        Time = $expectedDate.Date.AddHours(18).AddMinutes(35)
    }
)

if (-not $Execute) {
    [ordered]@{
        mode = "PLAN_ONLY"
        expectedSessionDate = $ExpectedSessionDate
        expectedGitCommit = $ExpectedGitCommit.ToLowerInvariant()
        expectedModuleSha256 = $ExpectedModuleSha256.ToUpperInvariant()
        tasks = @(
            $definitions | ForEach-Object {
                [ordered]@{
                    taskName = $_.Name
                    attemptLabel = $_.Label
                    scheduledLocal = $_.Time.ToString("o")
                }
            }
        )
        userMustRemainLoggedIn = $true
        lockedDesktopAllowed = $true
        codexRequired = $false
        serviceChanged = $false
        positionsRequested = $false
        ordersRequested = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json -Depth 5
    exit 0
}

$installed = @()
foreach ($definition in $definitions) {
    if (
        (Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue) -and
        -not $ReplaceExisting
    ) {
        throw "An after-hours proof task already exists; refusing to overwrite it."
    }
    $arguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle Hidden",
        "-ExecutionPolicy Bypass",
        "-File `"$runner`"",
        "-ProjectRoot `"$ProjectRoot`"",
        "-PythonRoot `"$PythonRoot`"",
        "-OutputDirectory `"$OutputDirectory`"",
        "-ExpectedSessionDate $ExpectedSessionDate",
        "-DurationSeconds 900",
        "-AttemptLabel $($definition.Label)",
        "-ExpectedGitCommit $($ExpectedGitCommit.ToLowerInvariant())",
        "-ExpectedModuleSha256 $($ExpectedModuleSha256.ToUpperInvariant())",
        "-Execute"
    ) -join " "
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument $arguments `
        -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Once -At $definition.Time
    Register-ScheduledTask `
        -TaskName $definition.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    $task = Get-ScheduledTask -TaskName $definition.Name
    $info = Get-ScheduledTaskInfo -TaskName $definition.Name
    $xmlPath = Join-Path $OutputDirectory (($definition.Name -replace '[^A-Za-z0-9.-]', '-') + ".xml")
    Export-ScheduledTask -TaskName $definition.Name | Set-Content -LiteralPath $xmlPath -Encoding utf8
    $installed += [ordered]@{
        taskName = $definition.Name
        attemptLabel = $definition.Label
        scheduledLocal = $definition.Time.ToString("o")
        state = [string]$task.State
        nextRunTime = $info.NextRunTime.ToString("o")
        principal = $identity
        logonType = "INTERACTIVE_TOKEN"
        wakeToRun = [bool]$task.Settings.WakeToRun
        startWhenAvailable = [bool]$task.Settings.StartWhenAvailable
        restartCount = [int]$task.Settings.RestartCount
        restartInterval = [string]$task.Settings.RestartInterval
        executionTimeLimit = [string]$task.Settings.ExecutionTimeLimit
        exportedXml = $xmlPath
    }
}

[ordered]@{
    installed = $true
    expectedSessionDate = $ExpectedSessionDate
    tasks = $installed
    userMustRemainLoggedIn = $true
    lockedDesktopAllowed = $true
    sleepWakeRequested = $true
    codexRequired = $false
    serviceChanged = $false
    productionPersistence = $false
    positionsRequested = $false
    ordersRequested = $false
    orderTransmission = "UNAVAILABLE"
} | ConvertTo-Json -Depth 6
