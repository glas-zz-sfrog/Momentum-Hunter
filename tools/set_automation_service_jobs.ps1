[CmdletBinding()]
param(
    [Parameter(Mandatory)][datetime]$ShadowRunAt,
    [Parameter(Mandatory)][string]$ExpectedGitHead,
    [Parameter(Mandatory)][string]$ProofBundlePath,
    [Parameter(Mandatory)][string]$TaskDefinitionPath,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "",
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$ServiceName = "MomentumHunterAutomation",
    [string]$CodexPromptPath = "",
    [switch]$EnableShadowOpening,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Resolve-CodexExecutable {
    $nativePackageExecutable = Join-Path $env:APPDATA (
        "npm\node_modules\@openai\codex\node_modules\" +
        "@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\" +
        "bin\codex.exe"
    )
    if (Test-Path -LiteralPath $nativePackageExecutable -PathType Leaf) {
        return (Resolve-Path -LiteralPath $nativePackageExecutable).Path
    }
    $command = Get-Command codex.exe -ErrorAction SilentlyContinue
    if (
        $command -and
        $command.Source -notlike "$env:ProgramFiles\WindowsApps\*"
    ) {
        return $command.Source
    }
    return ""
}

if (-not $EnableShadowOpening) {
    throw "The exact -EnableShadowOpening interlock is required."
}
if ($ShadowRunAt -le (Get-Date)) {
    throw "The Shadow opening must be scheduled in the future."
}
if ($ShadowRunAt.ToString("HH:mm:ss") -ne "08:35:00") {
    throw "The Shadow opening must be scheduled at exactly 08:35:00 local time."
}
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "The Shadow opening requires the Windows Central Standard Time zone."
}
if ($ExpectedGitHead -notmatch "^[0-9a-fA-F]{40}$") {
    throw "ExpectedGitHead must be a full 40-character Git SHA."
}

$projectPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $PythonExe) {
    $PythonExe = Join-Path $projectPath ".venv\Scripts\python.exe"
}
$pythonPath = (Resolve-Path -LiteralPath $PythonExe).Path
$proofPath = (Resolve-Path -LiteralPath $ProofBundlePath).Path
$definitionPath = (Resolve-Path -LiteralPath $TaskDefinitionPath).Path
$projectPrefix = $projectPath.TrimEnd("\") + "\"
foreach ($path in @($proofPath, $definitionPath)) {
    if (-not $path.StartsWith(
        $projectPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Proof and launch definition must remain inside the repository."
    }
}
if (-not (Test-Path -LiteralPath $proofPath -PathType Container)) {
    throw "The selector proof bundle is missing."
}
if (-not (Test-Path -LiteralPath $definitionPath -PathType Leaf)) {
    throw "The frozen launch definition is missing."
}
$currentHead = (& git -C $projectPath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $currentHead -ne $ExpectedGitHead.ToLowerInvariant()) {
    throw "Current Git HEAD does not match ExpectedGitHead."
}
$gitStatus = & git -C $projectPath status --porcelain
if ($LASTEXITCODE -ne 0 -or $gitStatus) {
    throw "The repository must be clean before installing an opening manifest."
}

$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$stateDirectory = Join-Path $ServiceRoot "state"
$powershellPath = (
    "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
)
$engineStateDirectory = Join-Path (
    [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData
    )
) "MomentumHunter\python-engine-host"
$codexPath = Resolve-CodexExecutable
$jobs = @(
    [ordered]@{
        jobId = "shadow-opening-$($ShadowRunAt.ToString('yyyyMMdd'))"
        kind = "shadow_opening"
        scheduledAt = $ShadowRunAt.ToString("o")
        latestStartAt = $ShadowRunAt.AddSeconds(5).ToString("o")
        enabled = $true
        expectedGitHead = $ExpectedGitHead.ToLowerInvariant()
        proofBundlePath = $proofPath
        taskDefinitionPath = $definitionPath
        timeoutSeconds = 1800
    }
)
if ($CodexPromptPath) {
    if (-not $codexPath) {
        throw "Codex review was requested but the Codex CLI is unavailable."
    }
    $promptPath = (Resolve-Path -LiteralPath $CodexPromptPath).Path
    if (-not $promptPath.StartsWith(
        $projectPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "The Codex review prompt must remain inside the repository."
    }
    $jobs += [ordered]@{
        jobId = "shadow-review-$($ShadowRunAt.ToString('yyyyMMdd'))"
        kind = "codex_review"
        scheduledAt = $ShadowRunAt.AddMinutes(15).ToString("o")
        latestStartAt = $ShadowRunAt.AddMinutes(45).ToString("o")
        enabled = $true
        dependsOnJobId = "shadow-opening-$($ShadowRunAt.ToString('yyyyMMdd'))"
        promptPath = $promptPath
        timeoutSeconds = 900
    }
}
$manifest = [ordered]@{
    schemaVersion = 1
    repositoryRoot = $projectPath
    pythonExecutable = $pythonPath
    powershellExecutable = $powershellPath
    codexExecutable = $codexPath
    stateDirectory = $stateDirectory
    engineHostStateDirectory = $engineStateDirectory
    expectedAccountEnding = "2573"
    expectedAccountType = "INDIVIDUAL_CASH"
    pollIntervalSeconds = 1
    jobs = $jobs
}
$plan = [ordered]@{
    manifestPath = $manifestPath
    serviceName = $ServiceName
    shadowOpeningEnabled = $true
    shadowRunAt = $ShadowRunAt.ToString("o")
    expectedGitHead = $ExpectedGitHead.ToLowerInvariant()
    proofBundlePath = $proofPath
    taskDefinitionPath = $definitionPath
    codexReviewEnabled = [bool]$CodexPromptPath
    jobs = $jobs
    orderTransmission = "UNAVAILABLE"
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    exit 0
}
if (-not (Test-IsAdministrator)) {
    throw "Updating the service manifest requires elevated PowerShell."
}
if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
    throw "Service $ServiceName is not installed."
}
if (-not (Test-Path -LiteralPath $ServiceRoot -PathType Container)) {
    throw "Automation service root is missing."
}

$backupPath = if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    "$manifestPath.$((Get-Date).ToString('yyyyMMddTHHmmss')).bak"
}
else {
    ""
}
if ($backupPath) {
    Copy-Item -LiteralPath $manifestPath -Destination $backupPath
}
$temporaryManifest = "$manifestPath.$([guid]::NewGuid().ToString('N')).tmp"
$manifest | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $temporaryManifest -Encoding utf8
Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force
Restart-Service -Name $ServiceName
$service = Get-Service -Name $ServiceName
$service.WaitForStatus(
    [System.ServiceProcess.ServiceControllerStatus]::Running,
    [TimeSpan]::FromSeconds(30)
)

[ordered]@{
    updated = $true
    serviceName = $ServiceName
    status = $service.Status.ToString()
    manifestPath = $manifestPath
    previousManifest = $backupPath
    shadowRunAt = $ShadowRunAt.ToString("o")
    codexReviewEnabled = [bool]$CodexPromptPath
    orderTransmission = "UNAVAILABLE"
} | ConvertTo-Json -Depth 5
