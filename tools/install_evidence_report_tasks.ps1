param(
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$PythonExe = "C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe",
    [string]$DailyEvidenceTime = "20:30",
    [string]$WeeklyReliabilityTime = "20:45",
    [string]$WeeklyReliabilityDay = "Friday",
    [switch]$RunWhetherLoggedOn
)

$ErrorActionPreference = "Stop"

$toolsDir = Join-Path $ProjectRoot "tools"
$logDir = Join-Path $ProjectRoot "MomentumHunterData\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$runnerScript = Join-Path $toolsDir "run_evidence_report_job.ps1"
$dailyTaskName = "Momentum Hunter Evidence Health Daily"
$weeklyTaskName = "Momentum Hunter Reliability Weekly"

function New-MomentumHunterPrincipal {
    if ($RunWhetherLoggedOn) {
        $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        return New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Highest
    }
    $interactiveUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    return New-ScheduledTaskPrincipal -UserId $interactiveUser -LogonType Interactive -RunLevel Limited
}

function Register-EvidenceTask {
    param(
        [string]$TaskName,
        [string]$ReportKind,
        $Trigger
    )

    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`" -ReportKind $ReportKind -ProjectRoot `"$ProjectRoot`" -PythonExe `"$PythonExe`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $ProjectRoot
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -WakeToRun `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $Trigger -Settings $settings -Principal (New-MomentumHunterPrincipal) -Force | Out-Null
}

$dailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyEvidenceTime
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyReliabilityDay -At $WeeklyReliabilityTime

Register-EvidenceTask -TaskName $dailyTaskName -ReportKind "evidence" -Trigger $dailyTrigger
Register-EvidenceTask -TaskName $weeklyTaskName -ReportKind "reliability" -Trigger $weeklyTrigger

Write-Host "Installed scheduled evidence tasks:"
Write-Host " - $dailyTaskName daily at $DailyEvidenceTime"
Write-Host " - $weeklyTaskName weekly on $WeeklyReliabilityDay at $WeeklyReliabilityTime"
Write-Host ""
Write-Host "These reports are derived evidence only. They do not change alerts, scores, readiness, rankings, or trade plans."
Write-Host ""
Write-Host "Note: If Windows asks for credentials when using -RunWhetherLoggedOn, provide your Windows account password."
