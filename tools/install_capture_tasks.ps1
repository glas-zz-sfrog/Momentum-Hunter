param(
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$PythonExe = "C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe",
    [string]$MorningTime = "07:00",
    [string]$EveningTime = "19:00",
    [switch]$RunWhetherLoggedOn
)

$ErrorActionPreference = "Stop"

$toolsDir = Join-Path $ProjectRoot "tools"
$logDir = Join-Path $ProjectRoot "MomentumHunterData\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$morningTaskName = "Momentum Hunter Morning Capture"
$eveningTaskName = "Momentum Hunter Evening Capture"
$runnerScript = Join-Path $toolsDir "run_capture_job.ps1"

function Register-CaptureTask {
    param(
        [string]$TaskName,
        [string]$Session,
        [string]$Time,
        [string]$ScriptPath
    )

    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -Session $Session -ProjectRoot `"$ProjectRoot`" -PythonExe `"$PythonExe`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -WakeToRun `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

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

Register-CaptureTask -TaskName $morningTaskName -Session "morning" -Time $MorningTime -ScriptPath $runnerScript
Register-CaptureTask -TaskName $eveningTaskName -Session "evening" -Time $EveningTime -ScriptPath $runnerScript

Write-Host "Installed scheduled tasks:"
Write-Host " - $morningTaskName at $MorningTime"
Write-Host " - $eveningTaskName at $EveningTime"
Write-Host ""
Write-Host "Note: If Windows asks for credentials when using -RunWhetherLoggedOn, provide your Windows account password."
