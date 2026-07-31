[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$PythonExe = "",
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$ServiceName = "MomentumHunterAutomation"
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$projectPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $PythonExe) {
    $PythonExe = Join-Path $projectPath ".venv\Scripts\python.exe"
}
$pythonPath = (Resolve-Path -LiteralPath $PythonExe).Path
$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$stateDirectory = Join-Path $ServiceRoot "state"
$statePath = Join-Path $stateDirectory "automation-service-state.json"
$baselinePath = Join-Path $stateDirectory "reboot-canary-baseline.json"
foreach ($path in @($manifestPath, $statePath, $baselinePath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required reboot-canary evidence is missing: $path"
    }
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $service) {
    throw "Automation service $ServiceName is not installed."
}
$serviceConfig = Get-CimInstance Win32_Service -Filter (
    "Name='$($ServiceName.Replace("'", "''"))'"
)
$bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$arguments = @(
    "-B",
    "-m",
    "momentum_hunter.automation_reboot_canary",
    "verify",
    "--manifest",
    $manifestPath,
    "--state",
    $statePath,
    "--baseline",
    $baselinePath,
    "--current-boot-time",
    $bootTime.ToString("o"),
    "--service-status",
    $service.Status.ToString(),
    "--service-start-mode",
    $serviceConfig.StartMode
)
Push-Location -LiteralPath $projectPath
try {
    $result = & $pythonPath @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
$result -join [Environment]::NewLine
exit $exitCode
