[CmdletBinding()]
param(
    [ValidateSet("Prepare", "InstallDisabled", "Verify", "Preflight", "Arm")]
    [string]$Stage = "Prepare",
    [string]$ProjectRoot = "",
    [string]$PreparedRoot = "",
    [string]$ConfigRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$PaperRoot = "C:\ProgramData\MomentumHunter\ContinuousPaper",
    [string]$PaperStateRoot = "C:\ProgramData\MomentumHunter\ContinuousPaperState",
    [string]$LifecycleProofPath = ""
)

$ErrorActionPreference = "Stop"
$paperServiceName = "MomentumHunterContinuousPaper"
$researchConfigPath = Join-Path $ConfigRoot "continuous-deployment.json"
$researchManifestPath = Join-Path $ConfigRoot "continuous-deployment-manifest.json"
$paperConfigPath = Join-Path $ConfigRoot "continuous-paper-deployment.json"
$paperManifestPath = Join-Path $ConfigRoot "continuous-paper-deployment-manifest.json"

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-ProjectRoot {
    param([string]$Value)
    if (-not $Value) { $Value = Split-Path -Parent $PSScriptRoot }
    return (Resolve-Path -LiteralPath $Value).Path
}

function Assert-ProductionPath {
    param([Parameter(Mandatory)][string]$PathValue)
    $full = [IO.Path]::GetFullPath($PathValue)
    $allowed = [IO.Path]::GetFullPath("C:\ProgramData\MomentumHunter")
    if (-not $full.StartsWith($allowed + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Production path is outside C:\ProgramData\MomentumHunter: $full"
    }
    if ($full -match "OneDrive|\.git|\\Temp\\") {
        throw "Production path violates the deployment root policy: $full"
    }
    return $full
}

function Get-GitValue {
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string[]]$Arguments)
    $value = (& git -C $Root @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Git command failed: git $($Arguments -join ' ')" }
    return $value
}

function Get-CanonicalIdentity {
    param([Parameter(Mandatory)][string]$Root)
    if ((Get-GitValue $Root @("branch", "--show-current")) -ne "master") {
        throw "Continuous Paper deployment must use canonical master."
    }
    if (Get-GitValue $Root @("status", "--porcelain")) {
        throw "Canonical checkout is dirty; Continuous Paper deployment stopped."
    }
    $head = Get-GitValue $Root @("rev-parse", "HEAD")
    $origin = Get-GitValue $Root @("rev-parse", "origin/master")
    if ($head -ne $origin) { throw "Canonical master and origin/master differ." }
    return [ordered]@{ head = $head; originMaster = $origin }
}

function Read-JsonObject {
    param([Parameter(Mandatory)][string]$PathValue, [Parameter(Mandatory)][string]$Label)
    if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
        throw "$Label is missing: $PathValue"
    }
    return Get-Content -Raw -LiteralPath $PathValue | ConvertFrom-Json
}

function Write-JsonAscii {
    param([Parameter(Mandatory)][string]$PathValue, [Parameter(Mandatory)][object]$Value)
    $parent = Split-Path -Parent $PathValue
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    [IO.File]::WriteAllText(
        $PathValue,
        (($Value | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
        [Text.Encoding]::ASCII
    )
}

function Get-ServiceSnapshot {
    param([Parameter(Mandatory)][string]$Name)
    $service = Get-CimInstance Win32_Service -Filter "Name='$Name'" -ErrorAction SilentlyContinue
    if (-not $service) { return $null }
    return [ordered]@{
        name = $service.Name
        state = $service.State
        startMode = $service.StartMode
        startName = $service.StartName
        pathName = $service.PathName
        processId = $service.ProcessId
    }
}

function Test-ServiceAccountMatch {
    param([Parameter(Mandatory)][string]$Actual, [Parameter(Mandatory)][string]$Expected)
    if ($Actual -ieq $Expected) { return $true }
    if ($Expected -match "^[^\\]+\\(?<user>[^\\]+)$") {
        return $Actual -ieq (".\" + $Matches.user)
    }
    return $false
}

function Assert-WindowsCredential {
    param(
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential,
        [Parameter(Mandatory)][string]$ExpectedAccount
    )
    if (-not (Test-ServiceAccountMatch $Credential.UserName $ExpectedAccount)) {
        throw "The Windows credential must use $ExpectedAccount."
    }
    $proof = Start-Process -FilePath $env:ComSpec -ArgumentList "/d", "/c", "exit 0" `
        -Credential $Credential -LoadUserProfile -WindowStyle Hidden -Wait -PassThru
    if ($proof.ExitCode -ne 0) { throw "Windows service credential validation failed." }
}

function Set-ServiceLogonCredential {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Account,
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    $service = Get-CimInstance Win32_Service -Filter "Name='$Name'" -ErrorAction Stop
    $pointer = [IntPtr]::Zero
    $password = $null
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential.Password)
        $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $change = Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{
            StartName = $Account
            StartPassword = $password
        }
        if ([int]$change.ReturnValue -ne 0) {
            throw "Windows rejected the Paper service logon update (code $($change.ReturnValue))."
        }
    } finally {
        $password = $null
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

function Invoke-InstalledPython {
    param(
        [Parameter(Mandatory)][object]$ResearchManifest,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    Push-Location -LiteralPath ([string]$ResearchManifest.runtimeSourceRoot)
    try {
        $output = & ([string]$ResearchManifest.pythonExecutable) @Arguments 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "Installed Continuous Paper command failed safely.`n$output" }
        return $output.Trim()
    } finally {
        Pop-Location
    }
}

function Protect-PaperPath {
    param([Parameter(Mandatory)][string]$PathValue, [Parameter(Mandatory)][string]$RuntimeAccount)
    New-Item -ItemType Directory -Force -Path $PathValue | Out-Null
    & icacls.exe $PathValue /inheritance:r /grant:r `
        "SYSTEM:(OI)(CI)F" "BUILTIN\Administrators:(OI)(CI)F" "$RuntimeAccount`:(OI)(CI)M" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not protect Continuous Paper path: $PathValue" }
}

function Stop-PaperService {
    $service = Get-Service -Name $paperServiceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne "Stopped") {
        Stop-Service -Name $paperServiceName
        $service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
    }
}

$project = Resolve-ProjectRoot $ProjectRoot
if (-not $PreparedRoot) { $PreparedRoot = Join-Path $env:TEMP "MomentumHunter-Continuous-Paper" }
$prepared = [IO.Path]::GetFullPath($PreparedRoot)
$planPath = Join-Path $prepared "continuous-paper-plan.json"

if ($Stage -eq "Prepare") {
    $identity = Get-CanonicalIdentity $project
    $researchManifest = Read-JsonObject $researchManifestPath "Continuous research deployment manifest"
    $researchConfig = Read-JsonObject $researchConfigPath "Continuous research configuration"
    if ([string]$researchManifest.canonicalHead -ne $identity.head -or [string]$researchConfig.installedProductSha -ne $identity.head) {
        throw "Installed continuous research is not the exact canonical product."
    }
    if ($researchConfig.mode -ne "RESEARCH_ONLY" -or $researchConfig.orderCapability -ne "UNAVAILABLE") {
        throw "Installed continuous research authority is unexpected."
    }
    if (-not $LifecycleProofPath) {
        $proofRoot = Join-Path $env:LOCALAPPDATA "MomentumHunterData\data\paper-engineering\lifecycle-proofs"
        $proof = Get-ChildItem -LiteralPath $proofRoot -Filter "*-final.json" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $proof) { throw "No direct Alpaca Paper lifecycle proof is available." }
        $LifecycleProofPath = $proof.FullName
    }
    $activation = (Get-Date).ToUniversalTime().ToString("o")
    $sampleDate = (Get-Date).ToString("yyyyMMdd")
    $plan = [ordered]@{
        schemaVersion = 1
        status = "PREPARED_DISABLED_INSTALL"
        canonicalHead = $identity.head
        originMaster = $identity.originMaster
        researchConfigPath = $researchConfigPath
        researchManifestPath = $researchManifestPath
        runtimeAccount = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        serviceHostExecutable = [string]$researchManifest.serviceHostExecutable
        pythonExecutable = [string]$researchManifest.pythonExecutable
        runtimeSourceRoot = [string]$researchManifest.runtimeSourceRoot
        paperConfigPath = Assert-ProductionPath $paperConfigPath
        paperManifestPath = Assert-ProductionPath $paperManifestPath
        paperRoot = Assert-ProductionPath $PaperRoot
        paperStateRoot = Assert-ProductionPath $PaperStateRoot
        lifecycleProofPath = (Resolve-Path -LiteralPath $LifecycleProofPath).Path
        sampleId = "continuous-paper-engineering-$sampleDate-v1"
        activationTimestamp = $activation
        entryAuthority = "ENTRY_AUTHORITY_DISABLED"
        paperHost = "https://paper-api.alpaca.markets"
        liveHost = "UNAVAILABLE"
    }
    Write-JsonAscii $planPath $plan
    [ordered]@{
        status = "PREPARED_DISABLED_INSTALL"
        planPath = $planPath
        canonicalHead = $identity.head
        sampleId = $plan.sampleId
        productionChanged = $false
        nextStep = "After review, run InstallDisabled from an elevated PowerShell session."
    } | ConvertTo-Json -Depth 8
    exit 0
}

$plan = Read-JsonObject $planPath "Prepared Continuous Paper plan"
$identity = Get-CanonicalIdentity $project
if ($plan.canonicalHead -ne $identity.head -or $plan.originMaster -ne $identity.originMaster) {
    throw "Prepared Continuous Paper plan no longer matches canonical master."
}
$researchManifest = Read-JsonObject ([string]$plan.researchManifestPath) "Continuous research deployment manifest"
$researchConfig = Read-JsonObject ([string]$plan.researchConfigPath) "Continuous research configuration"
if ([string]$researchManifest.canonicalHead -ne $identity.head -or [string]$researchConfig.installedProductSha -ne $identity.head) {
    throw "Installed research identity changed after preparation."
}
if ($researchConfig.mode -ne "RESEARCH_ONLY" -or $researchConfig.orderCapability -ne "UNAVAILABLE") {
    throw "Installed research authority changed after preparation."
}

if ($Stage -eq "InstallDisabled") {
    if (-not (Test-IsAdministrator)) { throw "InstallDisabled requires an elevated PowerShell session." }
    $credential = Get-Credential -UserName ([string]$plan.runtimeAccount) `
        -Message "Enter the local Windows password for the disabled Continuous Paper service. Do not enter a PIN or broker credential."
    if (-not $credential) { throw "Windows credential entry was cancelled." }
    Assert-WindowsCredential $credential ([string]$plan.runtimeAccount)

    $automationBefore = Get-ServiceSnapshot "MomentumHunterAutomation"
    $runtimeBefore = Get-ServiceSnapshot "MomentumHunterContinuousRuntime"
    $writerBefore = Get-ServiceSnapshot "MomentumHunterContinuousWriter"
    $automationManifest = Join-Path $ConfigRoot "automation-manifest.json"
    $automationManifestBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $automationManifest).Hash

    Protect-PaperPath ([string]$plan.paperRoot) ([string]$plan.runtimeAccount)
    Protect-PaperPath ([string]$plan.paperStateRoot) ([string]$plan.runtimeAccount)
    $freezeArguments = @(
        "-B", "-m", "momentum_hunter.alpaca_paper_engineering", "freeze-sample",
        "--risk-dollars", "2", "--max-notional", "95", "--cash-reserve", "5",
        "--max-open-risk", "2", "--daily-loss-limit", "4", "--max-positions", "1",
        "--account-max-age", "30", "--max-spread-percent", "3",
        "--max-entry-extension-percent", "0.25", "--minimum-reward-risk", "1.5",
        "--entry-notional-buffer-percent", "1", "--minimum-entry-notional", "1",
        "--lifecycle-proof", [string]$plan.lifecycleProofPath,
        "--output-directory", [string]$plan.paperRoot,
        "--sample-id", [string]$plan.sampleId,
        "--activated-at", [string]$plan.activationTimestamp,
        "--confirmation", "FREEZE ALPACA PAPER ENGINEERING SAMPLE"
    )
    $freeze = Invoke-InstalledPython $researchManifest $freezeArguments | ConvertFrom-Json
    $configureArguments = @(
        "-B", "-m", "momentum_hunter.continuous_paper",
        "--config", [string]$plan.paperConfigPath, "create-config",
        "--research-config", [string]$plan.researchConfigPath,
        "--paper-state-root", [string]$plan.paperStateRoot,
        "--paper-engineering-root", [string]$plan.paperRoot,
        "--installed-product-sha", [string]$plan.canonicalHead,
        "--sample-id", [string]$plan.sampleId,
        "--policy-fingerprint", [string]$freeze.policyFingerprint,
        "--activation-timestamp", [string]$freeze.activationTimestamp
    )
    Invoke-InstalledPython $researchManifest $configureArguments | Out-Null

    Stop-PaperService
    $binary = '"{0}" --role paper --repository-root "{1}" --python-executable "{2}" --config "{3}"' -f `
        [string]$plan.serviceHostExecutable, [string]$plan.runtimeSourceRoot, `
        [string]$plan.pythonExecutable, [string]$plan.paperConfigPath
    $existing = Get-ServiceSnapshot $paperServiceName
    if ($existing) {
        if (-not (Test-ServiceAccountMatch ([string]$existing.startName) ([string]$plan.runtimeAccount))) {
            throw "Existing Continuous Paper service uses an unexpected identity."
        }
        & sc.exe config $paperServiceName binPath= $binary start= auto | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not update the Continuous Paper service." }
        Set-ServiceLogonCredential $paperServiceName ([string]$existing.startName) $credential
    } else {
        New-Service -Name $paperServiceName -DisplayName "Momentum Hunter Continuous Paper (One-Entry Canary)" `
            -Description "Independent Alpaca Paper one-entry canary supervisor" `
            -BinaryPathName $binary -StartupType Automatic -Credential $credential | Out-Null
    }
    & sc.exe config $paperServiceName depend= MomentumHunterContinuousWriter | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not bind the Paper writer dependency." }
    Start-Service -Name $paperServiceName
    (Get-Service -Name $paperServiceName).WaitForStatus("Running", [TimeSpan]::FromSeconds(30))

    $manifest = [ordered]@{
        schemaVersion = 1
        profile = "continuous-paper-one-entry-canary-v1"
        installedAt = (Get-Date).ToUniversalTime().ToString("o")
        canonicalHead = $identity.head
        sampleId = [string]$plan.sampleId
        policyFingerprint = [string]$freeze.policyFingerprint
        activationTimestamp = [string]$freeze.activationTimestamp
        paperService = Get-ServiceSnapshot $paperServiceName
        researchService = Get-ServiceSnapshot "MomentumHunterContinuousRuntime"
        writerService = Get-ServiceSnapshot "MomentumHunterContinuousWriter"
        paperHost = "https://paper-api.alpaca.markets"
        entryAuthority = "ENTRY_AUTHORITY_DISABLED"
        alpacaLive = "UNAVAILABLE"
        schwabOrders = "UNAVAILABLE"
        liveExecution = "UNAVAILABLE"
    }
    Write-JsonAscii ([string]$plan.paperManifestPath) $manifest

    if (($automationBefore | ConvertTo-Json -Compress) -ne ((Get-ServiceSnapshot "MomentumHunterAutomation") | ConvertTo-Json -Compress)) {
        throw "Ordinary Automation Service changed unexpectedly."
    }
    if (($runtimeBefore | ConvertTo-Json -Compress) -ne ((Get-ServiceSnapshot "MomentumHunterContinuousRuntime") | ConvertTo-Json -Compress)) {
        throw "Continuous research service changed unexpectedly."
    }
    if (($writerBefore | ConvertTo-Json -Compress) -ne ((Get-ServiceSnapshot "MomentumHunterContinuousWriter") | ConvertTo-Json -Compress)) {
        throw "Continuous writer service changed unexpectedly."
    }
    if ($automationManifestBefore -ne (Get-FileHash -Algorithm SHA256 -LiteralPath $automationManifest).Hash) {
        throw "Ordinary Automation manifest changed unexpectedly."
    }
}

if ($Stage -eq "Verify") {
    $service = Get-ServiceSnapshot $paperServiceName
    if (-not $service -or $service.state -ne "Running" -or $service.startMode -ne "Auto") {
        throw "Continuous Paper disabled service is not healthy."
    }
    $status = Invoke-InstalledPython $researchManifest @(
        "-B", "-m", "momentum_hunter.continuous_paper",
        "--config", [string]$plan.paperConfigPath, "status"
    ) | ConvertFrom-Json
    if ($status.mode -ne "ENTRY_AUTHORITY_DISABLED") {
        throw "Continuous Paper entry authority is not disabled."
    }
}

if ($Stage -eq "Preflight") {
    $preflight = Invoke-InstalledPython $researchManifest @(
        "-B", "-m", "momentum_hunter.continuous_paper",
        "--config", [string]$plan.paperConfigPath, "preflight"
    ) | ConvertFrom-Json
    if ($preflight.classification -ne "PAPER_ENVIRONMENT_CLEAN") {
        throw "Continuous Paper preflight did not prove a clean Paper environment."
    }
}

if ($Stage -eq "Arm") {
    if (-not (Test-IsAdministrator)) { throw "Arm requires an elevated PowerShell session." }
    Stop-PaperService
    try {
        $armed = Invoke-InstalledPython $researchManifest @(
            "-B", "-m", "momentum_hunter.continuous_paper",
            "--config", [string]$plan.paperConfigPath, "arm",
            "--confirmation", "ARM ONE CONTINUOUS ALPACA PAPER ENTRY"
        ) | ConvertFrom-Json
        if ($armed.mode -ne "CANARY_ARMED_ONE_ENTRY") {
            throw "Continuous Paper arm did not establish one-entry authority."
        }
    } finally {
        Start-Service -Name $paperServiceName
        (Get-Service -Name $paperServiceName).WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
    }
}

[ordered]@{
    status = switch ($Stage) {
        "InstallDisabled" { "CONTINUOUS_PAPER_INSTALLED_DISABLED" }
        "Verify" { "CONTINUOUS_PAPER_DISABLED_VERIFIED" }
        "Preflight" { "CONTINUOUS_PAPER_READ_ONLY_PREFLIGHT_PASSED" }
        "Arm" { "CONTINUOUS_PAPER_CANARY_ARMED_ONE_ENTRY" }
    }
    stage = $Stage
    canonicalHead = $identity.head
    paperService = Get-ServiceSnapshot $paperServiceName
    researchMode = [string]$researchConfig.mode
    researchOrderCapability = [string]$researchConfig.orderCapability
    tradePlanProducer = [string]$researchConfig.continuousTradePlanProducer
    paperHost = "https://paper-api.alpaca.markets"
    alpacaLive = "UNAVAILABLE"
    schwabOrders = "UNAVAILABLE"
    liveExecution = "UNAVAILABLE"
} | ConvertTo-Json -Depth 10
