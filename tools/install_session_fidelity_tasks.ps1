[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$PythonRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$OutputDirectory = "C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\SESSION-FIDELITY-001-20260810",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedGitCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedRunnerSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedAlpacaCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedAlpacaModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedSchwabOvernightCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedSchwabOvernightModuleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedOvernightShimCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedOvernightShimSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$runner = Join-Path $ProjectRoot "tools\run_session_fidelity_checkpoint.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "The session-fidelity task runner is unavailable."
}

function Assert-CleanCommit {
    param([string]$Root, [string]$Expected, [string]$Label)
    $actual = (& git -C $Root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $Expected.ToLowerInvariant()) {
        throw "$Label does not match its frozen Git commit."
    }
    $dirty = & git -C $Root status --porcelain
    if ($LASTEXITCODE -ne 0 -or $dirty) {
        throw "$Label is not clean."
    }
}

function Assert-FileHash {
    param([string]$Path, [string]$Expected, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is unavailable."
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $Expected.ToUpperInvariant()) {
        throw "$Label does not match its frozen SHA-256."
    }
}

$AlpacaRoot = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-OVERNIGHT-001-readonly-market-data-probe"
$SchwabOvernightRoot = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-SCHWAB-OVERNIGHT-001-readonly-fidelity-probe"
$OvernightShimRoot = "C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-OVERNIGHT-002-midweek-fidelity-replication"
Assert-CleanCommit -Root $ProjectRoot -Expected $ExpectedGitCommit -Label "Session-fidelity worktree"
Assert-FileHash -Path (Join-Path $ProjectRoot "momentum_hunter\session_fidelity.py") -Expected $ExpectedModuleSha256 -Label "Session-fidelity module"
Assert-FileHash -Path (Join-Path $ProjectRoot "tools\run_session_fidelity_checkpoint.py") -Expected $ExpectedRunnerSha256 -Label "Session-fidelity runner"
Assert-CleanCommit -Root $AlpacaRoot -Expected $ExpectedAlpacaCommit -Label "Frozen Alpaca probe"
Assert-FileHash -Path (Join-Path $AlpacaRoot "momentum_hunter\alpaca_overnight_probe.py") -Expected $ExpectedAlpacaModuleSha256 -Label "Frozen Alpaca module"
Assert-CleanCommit -Root $SchwabOvernightRoot -Expected $ExpectedSchwabOvernightCommit -Label "Frozen Schwab overnight probe"
Assert-FileHash -Path (Join-Path $SchwabOvernightRoot "momentum_hunter\schwab_overnight_probe.py") -Expected $ExpectedSchwabOvernightModuleSha256 -Label "Frozen Schwab overnight module"
Assert-CleanCommit -Root $OvernightShimRoot -Expected $ExpectedOvernightShimCommit -Label "Frozen overnight shim"
Assert-FileHash -Path (Join-Path $OvernightShimRoot "tools\run_midweek_overnight_probe.py") -Expected $ExpectedOvernightShimSha256 -Label "Frozen overnight shim"

if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path

$definitions = @(
    [ordered]@{ Code = "E"; Name = "Momentum Hunter Session Fidelity E 20260810"; Time = [datetime]"2026-08-10T12:00:00" },
    [ordered]@{ Code = "F"; Name = "Momentum Hunter Session Fidelity F 20260810"; Time = [datetime]"2026-08-10T15:05:00" },
    [ordered]@{ Code = "G"; Name = "Momentum Hunter Session Fidelity G 20260810"; Time = [datetime]"2026-08-10T18:55:00" },
    [ordered]@{ Code = "H"; Name = "Momentum Hunter Session Fidelity H 20260810"; Time = [datetime]"2026-08-10T19:05:00" },
    [ordered]@{ Code = "A"; Name = "Momentum Hunter Session Fidelity A 20260811"; Time = [datetime]"2026-08-11T03:05:00" },
    [ordered]@{ Code = "B"; Name = "Momentum Hunter Session Fidelity B 20260811"; Time = [datetime]"2026-08-11T05:55:00" },
    [ordered]@{ Code = "C"; Name = "Momentum Hunter Session Fidelity C 20260811"; Time = [datetime]"2026-08-11T06:05:00" }
)

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

if (-not $Execute) {
    [ordered]@{
        mode = "PLAN_ONLY"
        taskId = "SESSION-FIDELITY-001"
        tasks = @($definitions | ForEach-Object {
            [ordered]@{
                checkpoint = $_.Code
                taskName = $_.Name
                scheduledCentral = $_.Time.ToString("o")
            }
        })
        reusedExistingLanes = @("D_OPENING_CAPTURE", "I_OVERNIGHT_002")
        oneTimeOnly = $true
        startWhenAvailable = $false
        userMustRemainLoggedIn = $true
        lockedDesktopAllowed = $true
        codexRequired = $false
        serviceChanged = $false
        productionPersistence = $false
        ordersRequested = $false
        positionsRequested = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json -Depth 6
    exit 0
}

$now = Get-Date
foreach ($definition in $definitions) {
    if ($definition.Time -le $now) {
        throw "Checkpoint $($definition.Code) is no longer safely schedulable."
    }
    if (Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue) {
        throw "A session-fidelity task already exists; refusing to replace it."
    }
}

$common = @(
    "-NoProfile",
    "-NonInteractive",
    "-WindowStyle Hidden",
    "-ExecutionPolicy Bypass",
    "-File `"$runner`"",
    "-ProjectRoot `"$ProjectRoot`"",
    "-PythonRoot `"$PythonRoot`"",
    "-OutputDirectory `"$OutputDirectory`"",
    "-ExpectedGitCommit $($ExpectedGitCommit.ToLowerInvariant())",
    "-ExpectedModuleSha256 $($ExpectedModuleSha256.ToUpperInvariant())",
    "-ExpectedRunnerSha256 $($ExpectedRunnerSha256.ToUpperInvariant())",
    "-ExpectedAlpacaCommit $($ExpectedAlpacaCommit.ToLowerInvariant())",
    "-ExpectedAlpacaModuleSha256 $($ExpectedAlpacaModuleSha256.ToUpperInvariant())",
    "-ExpectedSchwabOvernightCommit $($ExpectedSchwabOvernightCommit.ToLowerInvariant())",
    "-ExpectedSchwabOvernightModuleSha256 $($ExpectedSchwabOvernightModuleSha256.ToUpperInvariant())",
    "-ExpectedOvernightShimCommit $($ExpectedOvernightShimCommit.ToLowerInvariant())",
    "-ExpectedOvernightShimSha256 $($ExpectedOvernightShimSha256.ToUpperInvariant())",
    "-Execute"
)

$installed = @()
foreach ($definition in $definitions) {
    $arguments = (@($common[0..4]) + "-Checkpoint $($definition.Code)" + @($common[5..($common.Count - 1)])) -join " "
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
    if ([bool]$task.Settings.StartWhenAvailable) {
        throw "The installed checkpoint unexpectedly permits a late start."
    }
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
    taskId = "SESSION-FIDELITY-001"
    installedAt = [datetime]::UtcNow.ToString("o")
    expectedGitCommit = $ExpectedGitCommit.ToLowerInvariant()
    tasks = $installed
    reusedExistingLanes = @("D_OPENING_CAPTURE", "I_OVERNIGHT_002")
    oneTimeOnly = $true
    userMustRemainLoggedIn = $true
    lockedDesktopAllowed = $true
    codexRequired = $false
    serviceChanged = $false
    serviceManifestChanged = $false
    productionPersistence = $false
    positionsRequested = $false
    ordersRequested = $false
    previewsRequested = $false
    orderTransmission = "UNAVAILABLE"
}
$receiptPath = Join-Path $OutputDirectory "session-fidelity-launcher-receipt.json"
if (Test-Path -LiteralPath $receiptPath) {
    throw "The write-once launcher receipt already exists."
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
$receipt | ConvertTo-Json -Depth 8
