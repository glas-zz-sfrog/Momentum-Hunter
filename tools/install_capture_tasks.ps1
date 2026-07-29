param(
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$PythonExe = "C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe",
    [string]$MorningTime = "07:00",
    [string]$ShadowTime = "08:35",
    [datetime]$ShadowRunAt = [datetime]::MinValue,
    [string]$EveningTime = "19:00",
    [string]$SelectorProofBundle = "",
    [string]$Provider = "finviz",
    [string]$Scanner = "Institutional Momentum",
    [switch]$ArmShadowSelector,
    [switch]$EnableShadowTask,
    [switch]$ShadowOnly,
    [switch]$PlanOnly,
    [switch]$RunWhetherLoggedOn
)

$ErrorActionPreference = "Stop"

$hasOneTimeShadow = $ShadowRunAt -ne [datetime]::MinValue
if ($ArmShadowSelector -and -not $ShadowOnly) {
    throw "An armed Shadow task must be installed with -ShadowOnly."
}
if ($ArmShadowSelector -and -not $hasOneTimeShadow) {
    throw "An armed Shadow task must use an explicit one-time -ShadowRunAt value."
}
if ($ArmShadowSelector -and -not $EnableShadowTask) {
    throw "An armed Shadow task must be explicitly enabled with -EnableShadowTask."
}
if ($ArmShadowSelector -and $RunWhetherLoggedOn) {
    throw "An armed Shadow task must use the limited interactive Windows principal."
}
if ($ShadowOnly -and -not $hasOneTimeShadow) {
    throw "-ShadowOnly requires an explicit one-time -ShadowRunAt value."
}
if ($hasOneTimeShadow -and -not $ShadowOnly) {
    throw "-ShadowRunAt may only be used with -ShadowOnly."
}
if ($hasOneTimeShadow -and $ShadowRunAt -le (Get-Date)) {
    throw "The one-time Shadow run must be scheduled in the future."
}
if ($ArmShadowSelector -and $ShadowRunAt.ToString("HH:mm:ss") -ne "08:35:00") {
    throw "The armed Shadow opening must be scheduled at exactly 08:35:00 local Central time."
}
if ($ArmShadowSelector -and -not $PlanOnly -and (Get-TimeZone).Id -ne "Central Standard Time") {
    throw "The armed Shadow opening requires the Windows Central Standard Time zone."
}

$toolsDir = Join-Path $ProjectRoot "tools"
$logDir = Join-Path $ProjectRoot "MomentumHunterData\logs"
if (-not $PlanOnly) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

$morningTaskName = "Momentum Hunter Morning Capture"
$shadowTaskName = "Momentum Hunter Shadow Opening Capture"
$eveningTaskName = "Momentum Hunter Evening Capture"
$runnerScript = Join-Path $toolsDir "run_capture_job.ps1"
$taskDefinitionPath = Join-Path $ProjectRoot "MomentumHunterData\data\reports\shadow-opening-task-definition.xml"
if (-not $SelectorProofBundle) {
    $head = (& git -C $ProjectRoot rev-parse --short=7 HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $head) {
        throw "Cannot derive the canonical Git HEAD for the Shadow proof bundle."
    }
    $SelectorProofBundle = Join-Path $ProjectRoot "MomentumHunterData\data\reports\official-shadow-v2-selector-proof-bundle-$head"
}
if (-not (Test-Path -LiteralPath $SelectorProofBundle -PathType Container)) {
    throw "Shadow selector proof bundle is missing: $SelectorProofBundle"
}

function Register-CaptureTask {
    param(
        [string]$TaskName,
        [string]$Session,
        [string]$Time,
        [string]$ScriptPath
    )

    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -Session $Session -ProjectRoot `"$ProjectRoot`" -PythonExe `"$PythonExe`" -Provider `"$Provider`" -Scanner `"$Scanner`""
    if ($Session -eq "shadow") {
        $argument += " -SelectorProofBundle `"$SelectorProofBundle`" -TaskDefinitionPath `"$taskDefinitionPath`""
        if ($ArmShadowSelector) {
            $argument += " -ArmShadowSelector"
        }
    }
    $oneTime = $Session -eq "shadow" -and $hasOneTimeShadow
    $startWhenAvailable = -not $oneTime
    if ($PlanOnly) {
        return [pscustomobject]@{
            taskName = $TaskName
            session = $Session
            triggerKind = if ($oneTime) { "ONCE" } else { "DAILY" }
            runAt = if ($oneTime) { $ShadowRunAt.ToString("o") } else { $Time }
            enabled = if ($Session -eq "shadow") { [bool]$EnableShadowTask } else { $true }
            armShadowSelector = $Session -eq "shadow" -and [bool]$ArmShadowSelector
            executable = "powershell.exe"
            arguments = $argument
            workingDirectory = $ProjectRoot
            requiredWindowsTimeZone = if ($Session -eq "shadow") { "Central Standard Time" } else { "" }
            startWhenAvailable = $startWhenAvailable
            schedulerRestartCount = 0
            runnerOwnedMaximumAttempts = if ($Session -eq "shadow") { 4 } else { 1 }
        }
    }

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $ProjectRoot
    $trigger = if ($oneTime) {
        New-ScheduledTaskTrigger -Once -At $ShadowRunAt
    }
    else {
        New-ScheduledTaskTrigger -Daily -At $Time
    }
    $settingsArguments = @{
        StartWhenAvailable = $startWhenAvailable
        AllowStartIfOnBatteries = $true
        DontStopIfGoingOnBatteries = $true
        MultipleInstances = "IgnoreNew"
        WakeToRun = $true
        ExecutionTimeLimit = (New-TimeSpan -Minutes 30)
    }
    $settings = New-ScheduledTaskSettingsSet @settingsArguments

    if ($RunWhetherLoggedOn) {
        $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Highest
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    }
    else {
        $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    }
}

$plans = @()
if (-not $ShadowOnly) {
    $plans += Register-CaptureTask -TaskName $morningTaskName -Session "morning" -Time $MorningTime -ScriptPath $runnerScript
}
$plans += Register-CaptureTask -TaskName $shadowTaskName -Session "shadow" -Time $ShadowTime -ScriptPath $runnerScript
if (-not $ShadowOnly) {
    $plans += Register-CaptureTask -TaskName $eveningTaskName -Session "evening" -Time $EveningTime -ScriptPath $runnerScript
}

if ($PlanOnly) {
    $plans | ConvertTo-Json -Depth 4
    exit 0
}

if (-not $EnableShadowTask) {
    Disable-ScheduledTask -TaskName $shadowTaskName | Out-Null
}
$taskDefinitionDirectory = Split-Path -Parent $taskDefinitionPath
New-Item -ItemType Directory -Force -Path $taskDefinitionDirectory | Out-Null
Export-ScheduledTask -TaskName $shadowTaskName | Set-Content -LiteralPath $taskDefinitionPath -Encoding Unicode

Write-Host "Installed scheduled tasks:"
if (-not $ShadowOnly) {
    Write-Host " - $morningTaskName at $MorningTime"
}
if ($hasOneTimeShadow) {
    Write-Host " - $shadowTaskName once at $($ShadowRunAt.ToString('o'))"
}
else {
    Write-Host " - $shadowTaskName daily at $ShadowTime"
}
if (-not $ShadowOnly) {
    Write-Host " - $eveningTaskName at $EveningTime"
}
Write-Host " - Shadow task enabled: $([bool]$EnableShadowTask)"
Write-Host " - Shadow selector arm requested: $([bool]$ArmShadowSelector)"
Write-Host " - Frozen Shadow task definition: $taskDefinitionPath"
Write-Host ""
Write-Host "Market-calendar policy:"
Write-Host " - Morning task captures only on XNYS market-open days."
Write-Host " - Shadow opening task captures once at 9:35 AM ET on XNYS market-open days and immediately triggers the guarded Engine Host selector cycle."
Write-Host " - Evening task captures ordinary market-day evenings and preopen gap-review sessions before the next market-open day."
Write-Host ""
Write-Host "Note: If Windows asks for credentials when using -RunWhetherLoggedOn, provide your Windows account password."
