[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$PythonRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$OutputDirectory = "C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\SESSION-FIDELITY-003-20260812",
    [string]$AlpacaRoot = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-OVERNIGHT-001-readonly-market-data-probe",
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{40}$')] [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedRetryModuleSha256,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedRetryRunnerSha256,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedAdapterSha256,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedPowerShellRunnerSha256,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{40}$')] [string]$ExpectedAlpacaCommit,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedAlpacaModuleSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PythonRoot = (Resolve-Path -LiteralPath $PythonRoot).Path
$AlpacaRoot = (Resolve-Path -LiteralPath $AlpacaRoot).Path
$python = Join-Path $PythonRoot ".venv\Scripts\python.exe"
$runner = Join-Path $ProjectRoot "tools\run_session_fidelity_premarket_retry.ps1"
$retryModule = Join-Path $ProjectRoot "momentum_hunter\session_fidelity_premarket_retry.py"
$retryRunner = Join-Path $ProjectRoot "tools\run_session_fidelity_premarket_retry.py"
$adapter = Join-Path $ProjectRoot "tools\run_session_fidelity_alpaca.py"
$alpacaModule = Join-Path $AlpacaRoot "momentum_hunter\alpaca_overnight_probe.py"

function Assert-FileHash {
    param([string]$Path, [string]$Expected, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label is unavailable." }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Expected.ToUpperInvariant()) {
        throw "$Label does not match its frozen SHA-256."
    }
}

$actualCommit = (& git -C $ProjectRoot rev-parse HEAD).Trim()
$dirty = & git -C $ProjectRoot status --porcelain
if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $ExpectedGitCommit.ToLowerInvariant() -or $dirty) {
    throw "The premarket retry worktree is not clean at its frozen commit."
}
Assert-FileHash -Path $runner -Expected $ExpectedPowerShellRunnerSha256 -Label "Premarket retry PowerShell runner"
Assert-FileHash -Path $retryModule -Expected $ExpectedRetryModuleSha256 -Label "Premarket retry module"
Assert-FileHash -Path $retryRunner -Expected $ExpectedRetryRunnerSha256 -Label "Premarket retry runner"
Assert-FileHash -Path $adapter -Expected $ExpectedAdapterSha256 -Label "Repaired Alpaca adapter"

$actualAlpacaCommit = (& git -C $AlpacaRoot rev-parse HEAD).Trim()
$dirtyAlpaca = & git -C $AlpacaRoot status --porcelain
if (
    $LASTEXITCODE -ne 0 -or
    $actualAlpacaCommit -ne $ExpectedAlpacaCommit.ToLowerInvariant() -or
    $dirtyAlpaca
) {
    throw "The frozen Alpaca probe worktree does not match its expected clean commit."
}
Assert-FileHash -Path $alpacaModule -Expected $ExpectedAlpacaModuleSha256 -Label "Frozen Alpaca module"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The pinned Python executable is unavailable."
}

$definitions = @(
    [ordered]@{ Code = "A"; Name = "Momentum Hunter Session Fidelity Retry A 20260812"; Time = [datetime]"2026-08-12T03:05:00" },
    [ordered]@{ Code = "B"; Name = "Momentum Hunter Session Fidelity Retry B 20260812"; Time = [datetime]"2026-08-12T05:55:00" },
    [ordered]@{ Code = "C"; Name = "Momentum Hunter Session Fidelity Retry C 20260812"; Time = [datetime]"2026-08-12T06:05:00" }
)

if (-not $Execute) {
    [ordered]@{
        mode = "PLAN_ONLY"
        taskId = "SESSION-FIDELITY-003"
        sourceTaskId = "SESSION-FIDELITY-001"
        tasks = @($definitions | ForEach-Object {
            [ordered]@{ checkpoint = $_.Code; taskName = $_.Name; scheduledCentral = $_.Time.ToString("o") }
        })
        providerScope = "ALPACA_ONLY"
        oneTimeOnly = $true
        startWhenAvailable = $false
        userMustRemainLoggedIn = $true
        codexRequired = $false
        serviceChanged = $false
        productionPersistence = $false
        accountRequested = $false
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
if ($OutputDirectory.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Premarket retry evidence must remain outside the repository."
}
$receiptPath = Join-Path $OutputDirectory "session-fidelity-premarket-retry-launcher-receipt.json"
if (Test-Path -LiteralPath $receiptPath) {
    throw "The write-once premarket retry receipt already exists."
}
$now = Get-Date
foreach ($definition in $definitions) {
    if ($definition.Time -le $now) { throw "Checkpoint $($definition.Code) is no longer safely schedulable." }
    if (Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue) {
        throw "A premarket retry task already exists; refusing to replace it."
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 12) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$common = @(
    "-NoProfile", "-NonInteractive", "-WindowStyle Hidden", "-ExecutionPolicy Bypass",
    "-File `"$runner`"", "-ProjectRoot `"$ProjectRoot`"", "-PythonRoot `"$PythonRoot`"",
    "-OutputDirectory `"$OutputDirectory`"", "-AlpacaRoot `"$AlpacaRoot`"",
    "-ExpectedGitCommit $($ExpectedGitCommit.ToLowerInvariant())",
    "-ExpectedRetryModuleSha256 $($ExpectedRetryModuleSha256.ToUpperInvariant())",
    "-ExpectedRetryRunnerSha256 $($ExpectedRetryRunnerSha256.ToUpperInvariant())",
    "-ExpectedAdapterSha256 $($ExpectedAdapterSha256.ToUpperInvariant())",
    "-ExpectedAlpacaCommit $($ExpectedAlpacaCommit.ToLowerInvariant())",
    "-ExpectedAlpacaModuleSha256 $($ExpectedAlpacaModuleSha256.ToUpperInvariant())", "-Execute"
)

$installed = @()
foreach ($definition in $definitions) {
    $arguments = (@($common[0..4]) + "-Checkpoint $($definition.Code)" + @($common[5..($common.Count - 1)])) -join " "
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Once -At $definition.Time
    Register-ScheduledTask -TaskName $definition.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    $task = Get-ScheduledTask -TaskName $definition.Name
    $info = Get-ScheduledTaskInfo -TaskName $definition.Name
    if ([bool]$task.Settings.StartWhenAvailable) { throw "The installed retry unexpectedly permits a late start." }
    $xmlPath = Join-Path $OutputDirectory (($definition.Name -replace '[^A-Za-z0-9.-]', '-') + ".xml")
    Export-ScheduledTask -TaskName $definition.Name | Set-Content -LiteralPath $xmlPath -Encoding utf8
    $installed += [ordered]@{
        checkpoint = $definition.Code
        taskName = $definition.Name
        state = [string]$task.State
        nextRunTime = $info.NextRunTime.ToString("o")
        scheduledCentral = $definition.Time.ToString("o")
        logonType = "INTERACTIVE_TOKEN"
        wakeToRun = [bool]$task.Settings.WakeToRun
        startWhenAvailable = [bool]$task.Settings.StartWhenAvailable
        restartCount = [int]$task.Settings.RestartCount
        executionTimeLimit = [string]$task.Settings.ExecutionTimeLimit
        exportedXml = $xmlPath
    }
}

$receipt = [ordered]@{
    schemaVersion = 1
    taskId = "SESSION-FIDELITY-003"
    sourceTaskId = "SESSION-FIDELITY-001"
    installedAt = [datetime]::UtcNow.ToString("o")
    expectedGitCommit = $ExpectedGitCommit.ToLowerInvariant()
    tasks = $installed
    providerScope = "ALPACA_ONLY"
    oneTimeOnly = $true
    userMustRemainLoggedIn = $true
    codexRequired = $false
    serviceChanged = $false
    productionPersistence = $false
    accountRequested = $false
    positionsRequested = $false
    ordersRequested = $false
    orderTransmission = "UNAVAILABLE"
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
$receipt | ConvertTo-Json -Depth 8
