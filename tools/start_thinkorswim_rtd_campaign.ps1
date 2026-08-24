[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$CanonicalRoot,

    [Parameter(Mandatory = $true)]
    [string]$EvidenceRoot,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedSourceHead,

    [switch]$UseElevation
)

$ErrorActionPreference = 'Stop'
$runner = Join-Path $ProjectRoot 'tools\run_thinkorswim_rtd_campaign.ps1'
$configuration = Join-Path $ProjectRoot 'config\thinkorswim-rtd-001.json'
foreach ($path in @($runner, $configuration)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required campaign file is missing: $path" }
}

$command = @"
& '$runner' -ProjectRoot '$ProjectRoot' -CanonicalRoot '$CanonicalRoot' -EvidenceRoot '$EvidenceRoot' -ExpectedSourceHead '$ExpectedSourceHead' -ConfigurationPath '$configuration'
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
$start = @{
    FilePath = 'powershell.exe'
    WindowStyle = 'Hidden'
    ArgumentList = @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded)
    PassThru = $true
}
if ($UseElevation) {
    $start.Verb = 'RunAs'
}
$process = Start-Process @start
[ordered]@{
    status = if ($UseElevation) {'UAC_LAUNCH_REQUESTED'} else {'CURRENT_USER_LAUNCH_REQUESTED'}
    taskId = 'ARGUS-THINKORSWIM-OVERNIGHT-RTD-001'
    launcherProcessId = $process.Id
    evidenceRoot = $EvidenceRoot
    elevationRequested = [bool]$UseElevation
} | ConvertTo-Json -Depth 4
