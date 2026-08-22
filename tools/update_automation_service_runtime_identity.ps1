param(
    [ValidateSet("Plan", "Apply")]
    [string]$Stage = "Plan",
    [string]$ProjectRoot = "C:\Users\steve\OneDrive\Documents\Investing",
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$Confirmation = ""
)

$ErrorActionPreference = "Stop"
$requiredConfirmation = "UPDATE AUTOMATION SERVICE FOR RUNTIME IDENTITY"
$serviceName = "MomentumHunterAutomation"
$projectPath = [System.IO.Path]::GetFullPath($ProjectRoot)
$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$statePath = Join-Path $ServiceRoot "state\automation-service-state.json"
$serviceDirectory = Join-Path $ServiceRoot "service"
$serviceExecutable = Join-Path $serviceDirectory "MomentumHunter.AutomationService.exe"
$releaseRoot = Join-Path $ServiceRoot "opening-runtime"
$projectFile = Join-Path $projectPath "src\MomentumHunter.AutomationService\MomentumHunter.AutomationService.csproj"

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Get-GitValue([string[]]$Arguments) {
    $value = & git -C $projectPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git preflight failed."
    }
    return ($value | Out-String).Trim()
}

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Automation manifest is missing."
}
if (-not (Test-Path -LiteralPath $serviceExecutable -PathType Leaf)) {
    throw "Installed Automation Service executable is missing."
}
if (-not (Test-Path -LiteralPath $projectFile -PathType Leaf)) {
    throw "Automation Service project is missing."
}

$head = Get-GitValue @("rev-parse", "HEAD")
$origin = Get-GitValue @("rev-parse", "origin/master")
$worktree = Get-GitValue @("status", "--porcelain")
if ($head -ne $origin) {
    throw "Canonical master is not synchronized with origin/master."
}
if ($worktree) {
    throw "Canonical checkout is dirty."
}

$service = Get-CimInstance Win32_Service -Filter "Name='$serviceName'"
if (-not $service) {
    throw "Automation Service is not installed."
}
if ($service.StartMode -ne "Auto") {
    throw "Automation Service is not Automatic."
}
if ($service.State -ne "Running") {
    throw "Automation Service is not Running."
}
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$runningJobs = @(
    $state.jobs.PSObject.Properties.Value |
        Where-Object { $_.status -eq "RUNNING" }
)
if ($runningJobs.Count -ne 0) {
    throw "An automation job is running; service update stopped."
}

$plan = [ordered]@{
    status = "READY"
    stage = $Stage
    canonicalHead = $head
    originMaster = $origin
    worktreeClean = $true
    serviceName = $serviceName
    serviceState = $service.State
    serviceStartMode = $service.StartMode
    serviceStartName = $service.StartName
    serviceExecutable = $serviceExecutable
    currentServiceSha256 = Get-FileSha256 $serviceExecutable
    manifestPath = $manifestPath
    currentManifestSha256 = Get-FileSha256 $manifestPath
    runningJobs = 0
    openingRuntimeReleaseRoot = $releaseRoot
    orderTransmission = "UNAVAILABLE"
    mutationPerformed = $false
}

if ($Stage -eq "Plan") {
    $plan | ConvertTo-Json -Depth 5
    exit 0
}
if ($Confirmation -ne $requiredConfirmation) {
    throw "Exact service-update confirmation is required."
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Automation Service update requires an elevated PowerShell session."
}

$temporaryPublish = Join-Path $env:TEMP (
    "momentum-hunter-automation-runtime-" + [guid]::NewGuid().ToString("N")
)
$backupRoot = Join-Path $ServiceRoot (
    "backups\runtime-identity-" + (Get-Date -Format "yyyyMMddTHHmmss")
)
$backupService = Join-Path $backupRoot "service"
$backupManifest = Join-Path $backupRoot "automation-manifest.json"
New-Item -ItemType Directory -Force -Path $temporaryPublish | Out-Null
New-Item -ItemType Directory -Force -Path $backupService | Out-Null

try {
    & dotnet publish $projectFile -c Release -r win-x64 --self-contained false -o $temporaryPublish
    if ($LASTEXITCODE -ne 0) {
        throw "Automation Service publish failed."
    }
    $candidateExecutable = Join-Path $temporaryPublish "MomentumHunter.AutomationService.exe"
    if (-not (Test-Path -LiteralPath $candidateExecutable -PathType Leaf)) {
        throw "Published Automation Service executable is missing."
    }

    Copy-Item -LiteralPath $manifestPath -Destination $backupManifest
    Copy-Item -Path (Join-Path $serviceDirectory "*") -Destination $backupService -Recurse -Force
    Stop-Service -Name $serviceName -Force
    Copy-Item -Path (Join-Path $temporaryPublish "*") -Destination $serviceDirectory -Recurse -Force

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $manifest | Add-Member -NotePropertyName "serviceHostExecutable" -NotePropertyValue $serviceExecutable -Force
    $manifest | Add-Member -NotePropertyName "openingRuntimeReleaseRoot" -NotePropertyValue $releaseRoot -Force
    $temporaryManifest = "$manifestPath.$([guid]::NewGuid().ToString('N')).tmp"
    [System.IO.File]::WriteAllText(
        $temporaryManifest,
        (($manifest | ConvertTo-Json -Depth 8) + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
    $manifestCheck = Get-Content -LiteralPath $temporaryManifest -Raw | ConvertFrom-Json
    if (
        -not $manifestCheck.serviceHostExecutable -or
        -not $manifestCheck.openingRuntimeReleaseRoot -or
        -not $manifestCheck.jobs
    ) {
        throw "Updated Automation manifest did not pass structural validation."
    }
    Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force
    Start-Service -Name $serviceName

    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        $service = Get-CimInstance Win32_Service -Filter "Name='$serviceName'"
        $updatedState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $loadedHost = [string]$updatedState.loaded_service_host_sha256
        $loadedSupervisor = [string]$updatedState.loaded_supervisor_sha256
        $loadedGate = [string]$updatedState.loaded_runtime_identity_module_sha256
    } while (
        (Get-Date) -lt $deadline -and
        (
            $service.State -ne "Running" -or
            $loadedHost -notmatch "^[0-9a-f]{64}$" -or
            $loadedSupervisor -notmatch "^[0-9a-f]{64}$" -or
            $loadedGate -notmatch "^[0-9a-f]{64}$"
        )
    )
    if (
        $service.State -ne "Running" -or
        $loadedHost -ne (Get-FileSha256 $serviceExecutable).ToLowerInvariant() -or
        $loadedSupervisor -notmatch "^[0-9a-f]{64}$" -or
        $loadedGate -notmatch "^[0-9a-f]{64}$"
    ) {
        throw "Updated Automation Service did not report complete loaded identity."
    }

    [ordered]@{
        status = "UPDATED"
        canonicalHead = $head
        serviceState = $service.State
        serviceStartMode = $service.StartMode
        serviceStartName = $service.StartName
        serviceSha256 = Get-FileSha256 $serviceExecutable
        manifestSha256 = Get-FileSha256 $manifestPath
        loadedServiceHostSha256 = $loadedHost
        loadedSupervisorSha256 = $loadedSupervisor
        loadedRuntimeIdentityModuleSha256 = $loadedGate
        backupRoot = $backupRoot
        runningJobs = 0
        orderTransmission = "UNAVAILABLE"
        mutationPerformed = $true
    } | ConvertTo-Json -Depth 5
}
catch {
    try {
        if (Test-Path -LiteralPath $backupManifest -PathType Leaf) {
            Copy-Item -LiteralPath $backupManifest -Destination $manifestPath -Force
        }
        if (Test-Path -LiteralPath $backupService -PathType Container) {
            Copy-Item -Path (Join-Path $backupService "*") -Destination $serviceDirectory -Recurse -Force
        }
        Start-Service -Name $serviceName -ErrorAction SilentlyContinue
    }
    catch {
    }
    throw
}
finally {
    Remove-Item -LiteralPath $temporaryPublish -Recurse -Force -ErrorAction SilentlyContinue
}
