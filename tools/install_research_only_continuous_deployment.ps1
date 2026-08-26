[CmdletBinding()]
param(
    [ValidateSet("Prepare", "Install", "Verify")]
    [string]$Stage = "Prepare",
    [string]$ProjectRoot = "",
    [string]$PreparedRoot = "",
    [string]$RuntimeUser = "",
    [string]$ExpectedAccountEnding = "2573",
    [string]$EvidenceRoot = "C:\ProgramData\MomentumHunter\Continuous",
    [string]$RuntimeStateRoot = "C:\ProgramData\MomentumHunter\ContinuousRuntime",
    [string]$ConfigRoot = "C:\ProgramData\MomentumHunter\Automation",
    [switch]$RepairAutomationCredential
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-ProjectRoot {
    param([string]$Value)
    if (-not $Value) {
        $Value = Split-Path -Parent $PSScriptRoot
    }
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
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Arguments -join ' ')"
    }
    return $value
}

function Get-CanonicalIdentity {
    param([Parameter(Mandatory)][string]$Root)
    $branch = Get-GitValue $Root @("branch", "--show-current")
    if ($branch -ne "master") {
        throw "Deployment must be prepared from canonical master, not '$branch'."
    }
    $status = Get-GitValue $Root @("status", "--porcelain")
    if ($status) {
        throw "Canonical checkout is dirty; deployment preparation stopped."
    }
    $head = Get-GitValue $Root @("rev-parse", "HEAD")
    $origin = Get-GitValue $Root @("rev-parse", "origin/master")
    if ($head -ne $origin) {
        throw "Canonical master and origin/master differ."
    }
    $manifest = Join-Path $ConfigRoot "automation-manifest.json"
    $manifestHash = if (Test-Path -LiteralPath $manifest -PathType Leaf) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $manifest).Hash.ToLowerInvariant()
    } else {
        "NOT_FOUND"
    }
    return [ordered]@{
        branch = $branch
        head = $head
        originMaster = $origin
        automationManifestSha256 = $manifestHash
    }
}

function Get-RuntimeBuildHash {
    param([Parameter(Mandatory)][string]$Root)
    $paths = @(
        "momentum_hunter\continuous_production.py",
        "momentum_hunter\continuous_runtime.py",
        "momentum_hunter\continuous_live_qualification.py",
        "momentum_hunter\continuous_natural_setup.py",
        "momentum_hunter\continuous_evidence_writer.py",
        "momentum_hunter\event_runtime_writer_ipc.py",
        "momentum_hunter\windows_writer_storage.py"
    )
    $parts = foreach ($relative in $paths) {
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Runtime source file is missing: $relative"
        }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
        "$relative=$hash"
    }
    $bytes = [Text.Encoding]::ASCII.GetBytes(($parts -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace "-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Write-JsonAscii {
    param([Parameter(Mandatory)][string]$PathValue, [Parameter(Mandatory)][object]$Value)
    $parent = Split-Path -Parent $PathValue
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $json = $Value | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($PathValue, $json + [Environment]::NewLine, [Text.Encoding]::ASCII)
}

function Read-Plan {
    param([Parameter(Mandatory)][string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
        throw "Prepared deployment plan is missing: $PathValue"
    }
    return Get-Content -Raw -LiteralPath $PathValue | ConvertFrom-Json
}

function Invoke-DotnetPublish {
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$OutputPath)
    $project = Join-Path $Root "src\MomentumHunter.ContinuousServiceHost\MomentumHunter.ContinuousServiceHost.csproj"
    if (-not (Test-Path -LiteralPath $project -PathType Leaf)) {
        throw "Continuous service host project is missing."
    }
    New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null
    & dotnet publish $project -c Release -r win-x64 --self-contained false -o $OutputPath --nologo
    if ($LASTEXITCODE -ne 0) {
        throw "Continuous service host publish failed."
    }
}

function Protect-Directory {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [Parameter(Mandatory)][string]$WriterAccount,
        [Parameter(Mandatory)][string]$ReaderAccount,
        [switch]$ReaderModify
    )
    $mode = if ($ReaderModify) { "M" } else { "RX" }
    & icacls $PathValue /inheritance:r /grant:r `
        "SYSTEM:(OI)(CI)(F)" `
        "BUILTIN\Administrators:(OI)(CI)(F)" `
        "${WriterAccount}:(OI)(CI)(F)" `
        "${ReaderAccount}:(OI)(CI)($mode)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "ACL hardening failed for $PathValue."
    }
}

function Protect-File {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [Parameter(Mandatory)][string]$WriterAccount,
        [Parameter(Mandatory)][string]$ReaderAccount
    )
    & icacls $PathValue /inheritance:r /grant:r `
        "SYSTEM:(F)" `
        "BUILTIN\Administrators:(F)" `
        "${WriterAccount}:(R)" `
        "${ReaderAccount}:(R)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "ACL hardening failed for $PathValue."
    }
}

function Protect-ReadOnlyDirectory {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [Parameter(Mandatory)][string]$ReaderAccount,
        [Parameter(Mandatory)][string]$SecondReaderAccount
    )
    & icacls $PathValue /inheritance:r /grant:r `
        "SYSTEM:(OI)(CI)(F)" `
        "BUILTIN\Administrators:(OI)(CI)(F)" `
        "${ReaderAccount}:(OI)(CI)(RX)" `
        "${SecondReaderAccount}:(OI)(CI)(RX)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Read-only ACL hardening failed for $PathValue."
    }
}

function Get-SystemPythonExecutable {
    $candidate = "C:\Program Files\Python311\python.exe"
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "System Python 3.11 is unavailable for the dedicated service runtime."
    }
    return $candidate
}

function Invoke-PythonRuntimeBuild {
    param(
        [Parameter(Mandatory)][string]$SystemPython,
        [Parameter(Mandatory)][string]$RequirementsPath,
        [Parameter(Mandatory)][string]$OutputPath,
        [Parameter(Mandatory)][string]$RepositoryRoot
    )
    if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
        throw "Continuous runtime requirements are missing."
    }
    $deploymentPython = Join-Path $OutputPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $deploymentPython -PathType Leaf)) {
        Write-Host "Building isolated system-Python runtime..."
        & $SystemPython -m venv $OutputPath | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Continuous Python runtime creation failed."
        }
    }
    Write-Host "Installing pinned continuous-runtime dependencies..."
    & $deploymentPython -m pip install --disable-pip-version-check --requirement $RequirementsPath | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Continuous Python runtime dependency installation failed."
    }
    Push-Location -LiteralPath $RepositoryRoot
    try {
        & $deploymentPython -B -c "import momentum_hunter.continuous_production; print('continuous-runtime-import-ok')" | Out-Host
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Continuous Python runtime import validation failed."
    }
    return $deploymentPython
}

function New-IpcKey {
    param([Parameter(Mandatory)][string]$PathValue)
    if (Test-Path -LiteralPath $PathValue -PathType Leaf) {
        $existing = [IO.File]::ReadAllBytes($PathValue)
        if ($existing.Length -ne 32) {
            throw "Existing IPC key has an invalid length."
        }
        return
    }
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $parent = Split-Path -Parent $PathValue
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    [IO.File]::WriteAllBytes($PathValue, $bytes)
    [Array]::Clear($bytes, 0, $bytes.Length)
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
    }
}

function Test-ServiceAccountMatch {
    param(
        [Parameter(Mandatory)][string]$Actual,
        [Parameter(Mandatory)][string]$Expected
    )
    if ($Actual -ieq $Expected) { return $true }
    if ($Expected -match "^[^\\]+\\(?<user>[^\\]+)$") {
        return $Actual -ieq (".\" + $Matches.user)
    }
    return $false
}

function Install-ContinuousService {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$DisplayName,
        [Parameter(Mandatory)][string]$BinaryPath,
        [Parameter(Mandatory)][string]$Account,
        [System.Management.Automation.PSCredential]$Credential
    )
    $existing = Get-ServiceSnapshot $Name
    if ($existing) {
        if (-not (Test-ServiceAccountMatch $existing.startName $Account)) {
            throw "Existing $Name service does not match the expected deployment identity."
        }
        if ($existing.pathName -ne $BinaryPath) {
            & sc.exe config $Name binPath= $BinaryPath | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not update the $Name binary path." }
        }
        if ($Credential) {
            Set-ServiceLogonCredential $Name ([string]$existing.startName) $Credential
        }
        return Get-ServiceSnapshot $Name
    }
    if ($Credential) {
        New-Service -Name $Name -DisplayName $DisplayName -Description $DisplayName `
            -BinaryPathName $BinaryPath -StartupType Automatic -Credential $Credential | Out-Null
    } else {
        New-Service -Name $Name -DisplayName $DisplayName -Description $DisplayName `
            -BinaryPathName $BinaryPath -StartupType Automatic | Out-Null
        & sc.exe config $Name obj= $Account | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not bind $Name to $Account." }
    }
    return Get-ServiceSnapshot $Name
}

function Set-ServiceLogonCredential {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Account,
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    $service = Get-CimInstance Win32_Service -Filter "Name='$Name'" -ErrorAction Stop
    $passwordPointer = [IntPtr]::Zero
    $password = $null
    try {
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential.Password)
        $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        $change = Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{
            StartName = $Account
            StartPassword = $password
        }
        if ([int]$change.ReturnValue -ne 0) {
            throw "Windows rejected the $Name service logon update (code $($change.ReturnValue))."
        }
    } finally {
        $password = $null
        if ($passwordPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        }
    }
}

function Assert-WindowsCredential {
    param(
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential,
        [Parameter(Mandatory)][string]$ExpectedAccount
    )
    if (-not (Test-ServiceAccountMatch $Credential.UserName $ExpectedAccount)) {
        throw "The Windows credential must use $ExpectedAccount."
    }
    $proof = Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList "/d", "/c", "exit 0" `
        -Credential $Credential `
        -LoadUserProfile `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($proof.ExitCode -ne 0) {
        throw "The Windows service credential validation process failed."
    }
}

function Stop-ServiceIfRunning {
    param([Parameter(Mandatory)][string]$Name)
    $service = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne "Stopped") {
        Stop-Service -Name $Name
        $service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
    }
}

if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$project = Resolve-ProjectRoot $ProjectRoot
if (-not $PreparedRoot) {
    $PreparedRoot = Join-Path $env:TEMP "MomentumHunter-Continuous-Deployment"
}
$prepared = [IO.Path]::GetFullPath($PreparedRoot)
$planPath = Join-Path $prepared "deployment-plan.json"
$writerServiceName = "MomentumHunterContinuousWriter"
$runtimeServiceName = "MomentumHunterContinuousRuntime"
$writerAccount = "NT AUTHORITY\LOCAL SERVICE"
if (-not $RuntimeUser) { $RuntimeUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name }

if ($Stage -eq "Prepare") {
    $identity = Get-CanonicalIdentity $project
    $publish = Join-Path $prepared ("host-" + $identity.head)
    $pythonRuntimeStagingRoot = Join-Path $prepared ("python-runtime-" + $identity.head)
    $pythonRuntimeRoot = Assert-ProductionPath (Join-Path $ConfigRoot ("continuous-python-runtime-" + $identity.head))
    $systemPython = Get-SystemPythonExecutable
    $runtimeRequirements = Join-Path $project "tools\continuous_runtime_requirements.txt"
    $python = Invoke-PythonRuntimeBuild $systemPython $runtimeRequirements $pythonRuntimeStagingRoot $project
    $hostInstallRoot = Assert-ProductionPath (Join-Path $ConfigRoot "continuous-service-host")
    $runtimeSourceRoot = Assert-ProductionPath (Join-Path $ConfigRoot ("continuous-python-" + $identity.head))
    Invoke-DotnetPublish $project $publish
    $runtimeHash = Get-RuntimeBuildHash $project
    $plan = [ordered]@{
        schemaVersion = 1
        status = "PREPARED_PENDING_UAC"
        createdAt = (Get-Date).ToUniversalTime().ToString("o")
        canonicalHead = $identity.head
        originMaster = $identity.originMaster
        automationManifestSha256 = $identity.automationManifestSha256
        repositoryRoot = $project
        pythonRuntimeStagingRoot = $pythonRuntimeStagingRoot
        pythonRuntimeRoot = $pythonRuntimeRoot
        pythonExecutable = Join-Path $pythonRuntimeRoot "Scripts\python.exe"
        serviceHostStagingRoot = $publish
        serviceHostRoot = $hostInstallRoot
        serviceHostExecutable = Join-Path $hostInstallRoot "MomentumHunter.ContinuousServiceHost.exe"
        runtimeSourceRoot = $runtimeSourceRoot
        writerServiceName = $writerServiceName
        runtimeServiceName = $runtimeServiceName
        writerAccount = $writerAccount
        runtimeAccount = $RuntimeUser
        expectedAccountEnding = $ExpectedAccountEnding
        evidenceRoot = Assert-ProductionPath $EvidenceRoot
        runtimeStateRoot = Assert-ProductionPath $RuntimeStateRoot
        configPath = Assert-ProductionPath (Join-Path $ConfigRoot "continuous-deployment.json")
        ipcKeyPath = Assert-ProductionPath (Join-Path $EvidenceRoot "ipc\writer.key")
        runtimeBuildHash = $runtimeHash
        existingAutomationService = Get-ServiceSnapshot "MomentumHunterAutomation"
        existingAutomationManifest = Join-Path $ConfigRoot "automation-manifest.json"
        productionChangesInPrepare = $false
    }
    Write-JsonAscii $planPath $plan
    [ordered]@{
        status = "PREPARED_PENDING_UAC"
        planPath = $planPath
        canonicalHead = $identity.head
        serviceHostExecutable = $plan.serviceHostExecutable
        productionRootsCreated = $false
        existingAutomationServiceChanged = $false
        existingAutomationManifestChanged = $false
        nextStep = "Review the plan, then rerun this script as Administrator with -Stage Install."
    } | ConvertTo-Json -Depth 8
    exit 0
}

$plan = Read-Plan $planPath
$identity = Get-CanonicalIdentity $project
if ($plan.canonicalHead -ne $identity.head -or $plan.originMaster -ne $identity.originMaster) {
    throw "Prepared plan no longer matches clean canonical master."
}
if ($Stage -eq "Install" -and -not (Test-IsAdministrator)) {
    throw "Installation requires an elevated PowerShell session. Preparation did not require elevation."
}

$evidence = Assert-ProductionPath ([string]$plan.evidenceRoot)
$runtimeState = Assert-ProductionPath ([string]$plan.runtimeStateRoot)
$configPath = Assert-ProductionPath ([string]$plan.configPath)
$ipcKeyPath = Assert-ProductionPath ([string]$plan.ipcKeyPath)
$serviceHostRoot = Assert-ProductionPath ([string]$plan.serviceHostRoot)
$serviceHostStagingRoot = [IO.Path]::GetFullPath([string]$plan.serviceHostStagingRoot)
$runtimeSourceRoot = Assert-ProductionPath ([string]$plan.runtimeSourceRoot)
$pythonRuntimeStagingRoot = [IO.Path]::GetFullPath([string]$plan.pythonRuntimeStagingRoot)
$pythonRuntimeRoot = Assert-ProductionPath ([string]$plan.pythonRuntimeRoot)
$writerRoot = Join-Path $evidence "writer"
$automationBefore = Get-ServiceSnapshot "MomentumHunterAutomation"
$manifestBefore = if (Test-Path -LiteralPath $plan.existingAutomationManifest -PathType Leaf) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $plan.existingAutomationManifest).Hash
} else { "NOT_FOUND" }

if ($Stage -eq "Install") {
    if (-not (Test-Path -LiteralPath $serviceHostStagingRoot -PathType Container)) {
        throw "Prepared service host staging root is missing: $serviceHostStagingRoot"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $pythonRuntimeStagingRoot "Scripts\python.exe") -PathType Leaf)) {
        throw "Prepared continuous Python runtime is missing."
    }
    $existingRuntime = Get-ServiceSnapshot $runtimeServiceName
    $credentialRequired = (-not $existingRuntime) -or [bool]$RepairAutomationCredential
    $credential = $null
    if ($credentialRequired) {
        $credential = Get-Credential -UserName ([string]$plan.runtimeAccount) -Message "Enter the Windows account password for the research-only continuous runtime. Do not enter a PIN or any broker credential."
        if (-not $credential) { throw "Windows credential entry was cancelled." }
        Assert-WindowsCredential $credential ([string]$plan.runtimeAccount)
    } elseif (-not (Test-ServiceAccountMatch ([string]$existingRuntime.startName) ([string]$plan.runtimeAccount))) {
        throw "Existing continuous runtime service uses an unexpected Windows identity."
    }

    if ($RepairAutomationCredential) {
        if (-not $automationBefore) { throw "MomentumHunterAutomation is missing; credential repair stopped." }
        if (-not (Test-ServiceAccountMatch ([string]$automationBefore.startName) ([string]$plan.runtimeAccount))) {
            throw "MomentumHunterAutomation is bound to an unexpected Windows account."
        }
        Set-ServiceLogonCredential "MomentumHunterAutomation" ([string]$automationBefore.startName) $credential
        Start-Service -Name "MomentumHunterAutomation"
        (Get-Service -Name "MomentumHunterAutomation").WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
    }

    Stop-ServiceIfRunning $runtimeServiceName
    Stop-ServiceIfRunning $writerServiceName
    $sourcePackage = Join-Path ([string]$plan.repositoryRoot) "momentum_hunter"
    if (-not (Test-Path -LiteralPath $sourcePackage -PathType Container)) {
        throw "Canonical Python package is missing: $sourcePackage"
    }
    New-Item -ItemType Directory -Force -Path $runtimeSourceRoot | Out-Null
    Copy-Item -Path $sourcePackage -Destination $runtimeSourceRoot -Recurse -Force
    Protect-ReadOnlyDirectory $runtimeSourceRoot $writerAccount ([string]$plan.runtimeAccount)
    Write-Host "Installing the isolated Python runtime under ProgramData..."
    New-Item -ItemType Directory -Force -Path $pythonRuntimeRoot | Out-Null
    Protect-ReadOnlyDirectory $pythonRuntimeRoot $writerAccount ([string]$plan.runtimeAccount)
    Get-ChildItem -LiteralPath $pythonRuntimeStagingRoot -Force | Copy-Item -Destination $pythonRuntimeRoot -Recurse -Force
    Protect-ReadOnlyDirectory $pythonRuntimeRoot $writerAccount ([string]$plan.runtimeAccount)
    if (-not (Test-Path -LiteralPath ([string]$plan.pythonExecutable) -PathType Leaf)) {
        throw "Installed continuous Python runtime is missing."
    }
    New-Item -ItemType Directory -Force -Path $serviceHostRoot | Out-Null
    Get-ChildItem -LiteralPath $serviceHostStagingRoot -Force | Copy-Item -Destination $serviceHostRoot -Recurse -Force
    Protect-ReadOnlyDirectory $serviceHostRoot $writerAccount ([string]$plan.runtimeAccount)
    foreach ($directory in @($evidence, $runtimeState, (Split-Path -Parent $configPath), (Split-Path -Parent $ipcKeyPath))) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    New-IpcKey $ipcKeyPath
    $config = [ordered]@{
        schemaVersion = 1
        activationProfile = "research-only-continuous-deployment-v1"
        activationStart = (Get-Date).ToUniversalTime().ToString("o")
        mode = "RESEARCH_ONLY"
        authority = "RESEARCH_ONLY"
        executionAuthority = "NONE"
        orderCapability = "UNAVAILABLE"
        # A cadence/configuration change gets a new checkpoint namespace. The prior
        # namespace remains preserved as historical evidence and is never restored
        # under a different configuration fingerprint.
        runtimeIdentity = "production-continuous-runtime-v2"
        configurationSessionDate = "1970-01-01"
        runtimeBuildHash = [string]$plan.runtimeBuildHash
        evidenceProgramId = "continuous-opportunity-production"
        evidenceRoot = $evidence
        runtimeStateRoot = $runtimeState
        ipcKeyPath = $ipcKeyPath
        ipcHost = "127.0.0.1"
        ipcPort = 49281
        expectedAccountEnding = [string]$plan.expectedAccountEnding
        premarketDiscoverySeconds = 600
        broadDiscoverySeconds = 300
        configurationFingerprint = ""
        accountReads = "AUTHORIZATION_BOUNDARY_ONLY"
        positionsRequested = $false
        ordersRequested = $false
        orderTransmission = "UNAVAILABLE"
        shadowExecution = "UNAVAILABLE"
    }
    Write-JsonAscii $configPath $config
    # The elevated installer may start in an unrelated directory such as System32.
    # Run the repository module from the canonical checkout so imports resolve reliably.
    Push-Location -LiteralPath ([string]$plan.repositoryRoot)
    try {
        $fingerprint = (& $plan.pythonExecutable -B -m momentum_hunter.continuous_production --config $configPath --print-config-fingerprint 2>$null).Trim()
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0 -or $fingerprint -notmatch '^[0-9a-f]{64}$') { throw "Could not calculate the deployment configuration fingerprint." }
    $config.configurationFingerprint = $fingerprint
    Write-JsonAscii $configPath $config

    Protect-Directory $evidence $writerAccount ([string]$plan.runtimeAccount)
    Protect-Directory $runtimeState $writerAccount ([string]$plan.runtimeAccount) -ReaderModify
    Protect-File $ipcKeyPath $writerAccount ([string]$plan.runtimeAccount)
    Protect-File $configPath $writerAccount ([string]$plan.runtimeAccount)

    $serviceHostPath = Join-Path $serviceHostRoot "MomentumHunter.ContinuousServiceHost.exe"
    $writerBinary = '"{0}" --role writer --repository-root "{1}" --python-executable "{2}" --config "{3}"' -f $serviceHostPath, $runtimeSourceRoot, $plan.pythonExecutable, $configPath
    $runtimeBinary = '"{0}" --role runtime --repository-root "{1}" --python-executable "{2}" --config "{3}"' -f $serviceHostPath, $runtimeSourceRoot, $plan.pythonExecutable, $configPath
    Install-ContinuousService $writerServiceName "Momentum Hunter Continuous Writer (Research Only)" $writerBinary $writerAccount $null | Out-Null
    Install-ContinuousService $runtimeServiceName "Momentum Hunter Continuous Runtime (Research Only)" $runtimeBinary ([string]$plan.runtimeAccount) $credential | Out-Null
    & sc.exe config $runtimeServiceName depend= $writerServiceName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not bind the continuous runtime dependency." }
    Start-Service -Name $writerServiceName
    (Get-Service -Name $writerServiceName).WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
    Start-Service -Name $runtimeServiceName
    (Get-Service -Name $runtimeServiceName).WaitForStatus("Running", [TimeSpan]::FromSeconds(30))

    $deploymentManifest = [ordered]@{
        schemaVersion = 1
        profile = "research-only-continuous-deployment-v1"
        installedAt = (Get-Date).ToUniversalTime().ToString("o")
        canonicalHead = $identity.head
        runtimeBuildHash = $plan.runtimeBuildHash
        runtimeSourceRoot = $runtimeSourceRoot
        configurationFingerprint = $fingerprint
        writerService = Get-ServiceSnapshot $writerServiceName
        runtimeService = Get-ServiceSnapshot $runtimeServiceName
        evidenceRoot = $evidence
        runtimeStateRoot = $runtimeState
        orderCapability = "UNAVAILABLE"
        shadowJobsEnabled = 0
        existingAutomationServiceDefinitionUnchanged = $true
        existingAutomationCredentialRefreshed = [bool]$RepairAutomationCredential
        existingAutomationManifestUnchanged = $true
    }
    Write-JsonAscii (Join-Path $ConfigRoot "continuous-deployment-manifest.json") $deploymentManifest
}

$automationAfter = Get-ServiceSnapshot "MomentumHunterAutomation"
$manifestAfter = if (Test-Path -LiteralPath $plan.existingAutomationManifest -PathType Leaf) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $plan.existingAutomationManifest).Hash
} else { "NOT_FOUND" }
if ($RepairAutomationCredential) {
    foreach ($field in @("name", "startMode", "startName", "pathName")) {
        if ([string]$automationBefore.$field -ne [string]$automationAfter.$field) {
            throw "Existing Automation Service definition changed unexpectedly."
        }
    }
    if ($automationAfter.state -ne "Running") { throw "Existing Automation Service did not recover after credential refresh." }
} elseif (($automationBefore | ConvertTo-Json -Compress) -ne ($automationAfter | ConvertTo-Json -Compress)) {
    throw "Existing Automation Service changed unexpectedly."
}
if ($manifestBefore -ne $manifestAfter) { throw "Existing automation manifest changed unexpectedly." }

$result = [ordered]@{
    status = if ($Stage -eq "Install") { "INSTALLED_RESEARCH_ONLY_CONTINUOUS" } else { "VERIFIED" }
    stage = $Stage
    canonicalHead = $identity.head
    originMaster = $identity.originMaster
    writerService = if ($Stage -eq "Install") { Get-ServiceSnapshot $writerServiceName } else { $null }
    runtimeService = if ($Stage -eq "Install") { Get-ServiceSnapshot $runtimeServiceName } else { $null }
    evidenceRoot = $evidence
    runtimeStateRoot = $runtimeState
    configurationPath = $configPath
    orderCapability = "UNAVAILABLE"
    accountValuesRequested = $false
    positionsRequested = $false
    ordersRequested = $false
    existingAutomationServiceDefinitionUnchanged = $true
    existingAutomationCredentialRefreshed = [bool]$RepairAutomationCredential
    existingAutomationManifestUnchanged = $true
    nextStep = "Run the separate physical writer/root and runtime restart proofs before any research-only activation claim."
}
$result | ConvertTo-Json -Depth 12
