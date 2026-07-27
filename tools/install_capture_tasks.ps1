param(
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$PythonExe = "C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe",
    [string]$MorningTime = "07:00",
    [string]$ShadowTime = "08:35",
    [string]$EveningTime = "19:00",
    [string]$SelectorProofBundle = "",
    [switch]$RunWhetherLoggedOn
)

$ErrorActionPreference = "Stop"

$toolsDir = Join-Path $ProjectRoot "tools"
$logDir = Join-Path $ProjectRoot "MomentumHunterData\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$morningTaskName = "Momentum Hunter Morning Capture"
$shadowTaskName = "Momentum Hunter Shadow Opening Capture"
$eveningTaskName = "Momentum Hunter Evening Capture"
$runnerScript = Join-Path $toolsDir "run_capture_job.ps1"
if (-not $SelectorProofBundle) {
    $head = (& git -C $ProjectRoot rev-parse --short=7 HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $head) {
        throw "Cannot derive the canonical Git HEAD for the Shadow proof bundle."
    }
    $SelectorProofBundle = Join-Path $ProjectRoot "MomentumHunterData\data\reports\official-shadow-v1-selector-proof-bundle-$head"
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

    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -Session $Session -ProjectRoot `"$ProjectRoot`" -PythonExe `"$PythonExe`""
    if ($Session -eq "shadow") {
        $argument += " -SelectorProofBundle `"$SelectorProofBundle`""
    }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $settingsArguments = @{
        StartWhenAvailable = $true
        AllowStartIfOnBatteries = $true
        DontStopIfGoingOnBatteries = $true
        MultipleInstances = "IgnoreNew"
        WakeToRun = $true
        ExecutionTimeLimit = (New-TimeSpan -Minutes 30)
    }
    if ($Session -eq "shadow") {
        $settingsArguments["RestartCount"] = 3
        $settingsArguments["RestartInterval"] = (New-TimeSpan -Minutes 1)
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

Register-CaptureTask -TaskName $morningTaskName -Session "morning" -Time $MorningTime -ScriptPath $runnerScript
Register-CaptureTask -TaskName $shadowTaskName -Session "shadow" -Time $ShadowTime -ScriptPath $runnerScript
Register-CaptureTask -TaskName $eveningTaskName -Session "evening" -Time $EveningTime -ScriptPath $runnerScript

Write-Host "Installed scheduled tasks:"
Write-Host " - $morningTaskName at $MorningTime"
Write-Host " - $shadowTaskName at $ShadowTime"
Write-Host " - $eveningTaskName at $EveningTime"
Write-Host ""
Write-Host "Market-calendar policy:"
Write-Host " - Morning task captures only on XNYS market-open days."
Write-Host " - Shadow opening task captures once at 9:35 AM ET on XNYS market-open days and immediately triggers the guarded Engine Host selector cycle."
Write-Host " - Evening task captures ordinary market-day evenings and preopen gap-review sessions before the next market-open day."
Write-Host ""
Write-Host "Note: If Windows asks for credentials when using -RunWhetherLoggedOn, provide your Windows account password."
