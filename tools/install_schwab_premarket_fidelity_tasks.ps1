[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$SessionDate,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$ProjectRoot = "",
    [string]$PythonRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{40}$')] [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedModuleSha256,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedRunnerSha256,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedPowerShellRunnerSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$runner = Join-Path $ProjectRoot "tools\run_schwab_premarket_fidelity.ps1"
if ((Get-FileHash -LiteralPath $runner -Algorithm SHA256).Hash -ne $ExpectedPowerShellRunnerSha256.ToUpperInvariant()) {
    throw "The Schwab premarket PowerShell runner hash changed."
}
$session = [datetime]::ParseExact($SessionDate, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture)
$definitions = @(
    [ordered]@{
        Code = "BOUNDARY"
        Name = "Momentum Hunter Schwab Premarket Boundary $($session.ToString('yyyyMMdd'))"
        Time = $session.Date.AddHours(5).AddMinutes(55)
    },
    [ordered]@{
        Code = "ACTIVE"
        Name = "Momentum Hunter Schwab Premarket Active $($session.ToString('yyyyMMdd'))"
        Time = $session.Date.AddHours(6).AddMinutes(5)
    }
)
if (-not $Execute) {
    [ordered]@{
        mode = "PLAN_ONLY"
        taskId = "SESSION-FIDELITY-008"
        providerScope = "SCHWAB_ONLY"
        tasks = @($definitions | ForEach-Object {
            [ordered]@{ checkpoint = $_.Code; taskName = $_.Name; scheduledCentral = $_.Time.ToString("o") }
        })
        oneTimeOnly = $true
        startWhenAvailable = $false
        serviceChanged = $false
        productionPersistence = $false
        positionsRequested = $false
        ordersRequested = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json -Depth 6
    exit 0
}
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($OutputDirectory.StartsWith($ProjectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Schwab premarket evidence must remain outside the repository."
}
$now = Get-Date
foreach ($definition in $definitions) {
    if ($definition.Time -le $now) {
        throw "Checkpoint $($definition.Code) is no longer prospectively schedulable."
    }
    if (Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue) {
        throw "A Schwab premarket task already exists; replacement is forbidden."
    }
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$installed = @()
foreach ($definition in $definitions) {
    $arguments = @(
        "-NoProfile", "-NonInteractive", "-WindowStyle Hidden", "-ExecutionPolicy Bypass",
        "-File `"$runner`"", "-Checkpoint $($definition.Code)", "-SessionDate $SessionDate",
        "-OutputDirectory `"$OutputDirectory`"", "-ProjectRoot `"$ProjectRoot`"",
        "-PythonRoot `"$PythonRoot`"", "-ExpectedGitCommit $($ExpectedGitCommit.ToLowerInvariant())",
        "-ExpectedModuleSha256 $($ExpectedModuleSha256.ToUpperInvariant())",
        "-ExpectedRunnerSha256 $($ExpectedRunnerSha256.ToUpperInvariant())", "-Execute"
    ) -join " "
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Once -At $definition.Time
    Register-ScheduledTask -TaskName $definition.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    $task = Get-ScheduledTask -TaskName $definition.Name
    if ([bool]$task.Settings.StartWhenAvailable) {
        throw "The installed task unexpectedly permits a late start."
    }
    $installed += [ordered]@{
        checkpoint = $definition.Code
        taskName = $definition.Name
        scheduledCentral = $definition.Time.ToString("o")
        state = [string]$task.State
        providerScope = "SCHWAB_ONLY"
        wakeToRun = [bool]$task.Settings.WakeToRun
        startWhenAvailable = [bool]$task.Settings.StartWhenAvailable
    }
}
$receipt = [ordered]@{
    schemaVersion = 1
    taskId = "SESSION-FIDELITY-008"
    installedAt = [datetime]::UtcNow.ToString("o")
    expectedGitCommit = $ExpectedGitCommit.ToLowerInvariant()
    tasks = $installed
    providerScope = "SCHWAB_ONLY"
    oneTimeOnly = $true
    serviceChanged = $false
    productionPersistence = $false
    positionsRequested = $false
    ordersRequested = $false
    orderTransmission = "UNAVAILABLE"
}
$receiptPath = Join-Path $OutputDirectory "schwab-premarket-$SessionDate-schedule-receipt.json"
if (Test-Path -LiteralPath $receiptPath) {
    throw "The write-once scheduler receipt already exists."
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
$receipt | ConvertTo-Json -Depth 8
