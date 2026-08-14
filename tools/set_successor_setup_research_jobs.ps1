[CmdletBinding()]
param(
    [Parameter(Mandatory)][datetime]$SessionDate,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "",
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$ServiceName = "MomentumHunterAutomation",
    [switch]$EnableSuccessorSetupResearch,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

if (-not $EnableSuccessorSetupResearch) {
    throw "The exact -EnableSuccessorSetupResearch interlock is required."
}
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Successor-setup research requires the Windows Central Standard Time zone."
}
if ($SessionDate.Date -lt (Get-Date).Date) {
    throw "Successor-setup research must begin today or later."
}

$projectPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $PythonExe) {
    $PythonExe = Join-Path $projectPath ".venv\Scripts\python.exe"
}
$pythonPath = (Resolve-Path -LiteralPath $PythonExe).Path
$manifestPath = Join-Path $ServiceRoot "automation-manifest.json"
$statePath = Join-Path $ServiceRoot "state\automation-service-state.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Automation service manifest is missing."
}
if (-not $PlanOnly -and -not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
    throw "Service $ServiceName is not installed."
}

$gitStatus = & git -C $projectPath status --porcelain
if ($LASTEXITCODE -ne 0 -or $gitStatus) {
    throw "The repository must be clean before activating successor-setup research."
}
$gitHead = (& git -C $projectPath rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $gitHead -notmatch "^[0-9a-f]{40}$") {
    throw "The canonical repository HEAD could not be frozen."
}

$state = $null
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $running = @(
        $state.jobs.PSObject.Properties.Value |
            Where-Object { $_.status -eq "RUNNING" }
    )
    if ($running.Count -gt 0) {
        throw "An automation job is running; the manifest was not changed."
    }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$session = $SessionDate.Date
$dateText = $session.ToString("yyyy-MM-dd")
$dateId = $session.ToString("yyyyMMdd")
$openingId = "opening-capture-$dateId"
$pass1Id = "successor-setup-pass1-$dateId"
$pass2Id = "successor-setup-pass2-$dateId"
$opening = @($manifest.jobs | Where-Object { $_.jobId -eq $openingId })
if ($opening.Count -ne 1 -or -not $opening[0].enabled) {
    throw "The same-date enabled opening capture is missing."
}
if ([string]$opening[0].expectedGitHead -ne $gitHead) {
    throw "The opening capture is not pinned to the current canonical Git head."
}
if (@($manifest.jobs | Where-Object { $_.jobId -in @($pass1Id, $pass2Id) }).Count -gt 0) {
    throw "Successor-setup research jobs already exist for this date."
}
if (@($manifest.jobs | Where-Object { $_.kind -eq "shadow_opening" -and $_.enabled }).Count -gt 0) {
    throw "An enabled Shadow job exists; research activation stopped."
}

$pass1At = $session.AddHours(8).AddMinutes(35)
$pass2At = $session.AddHours(15).AddMinutes(5)
$centralZone = [TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
$pass1Offset = [DateTimeOffset]::new(
    $pass1At,
    $centralZone.GetUtcOffset($pass1At)
)
$pass2Offset = [DateTimeOffset]::new(
    $pass2At,
    $centralZone.GetUtcOffset($pass2At)
)
$pass1 = [ordered]@{
    jobId = $pass1Id
    kind = "successor_setup_pass1"
    scheduledAt = $pass1Offset.ToString("o")
    latestStartAt = $pass1Offset.AddMinutes(15).ToString("o")
    enabled = $true
    dependsOnJobId = $openingId
    expectedGitHead = $gitHead
    timeoutSeconds = 600
}
$pass2 = [ordered]@{
    jobId = $pass2Id
    kind = "successor_setup_pass2"
    scheduledAt = $pass2Offset.ToString("o")
    latestStartAt = $pass2Offset.AddMinutes(55).ToString("o")
    enabled = $true
    dependsOnJobId = $pass1Id
    expectedGitHead = $gitHead
    timeoutSeconds = 900
}
$researchRoot = Join-Path $projectPath (
    "MomentumHunterData\data\research\successor-setup-research-20260813-v1"
)
$charterPath = Join-Path $researchRoot "sample-charter.json"
$activationPath = Join-Path $researchRoot "activation.json"

$plan = [ordered]@{
    planOnly = [bool]$PlanOnly
    sessionDate = $dateText
    expectedGitHead = $gitHead
    openingDependency = $openingId
    jobs = @($pass1, $pass2)
    researchRoot = $researchRoot
    charterPath = $charterPath
    activationPath = $activationPath
    retries = 0
    providerCalls = $false
    accountCalls = $false
    orderTransmission = "UNAVAILABLE"
    shadowMutation = $false
    paperMutation = $false
}
if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    exit 0
}

New-Item -ItemType Directory -Path $researchRoot -Force | Out-Null
$activatedAt = (Get-Date).ToString("o")
if (-not (Test-Path -LiteralPath $charterPath -PathType Leaf)) {
    & $pythonPath -B -m momentum_hunter.successor_setup_observer charter `
        --created-at $activatedAt --output $charterPath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "SETUP-002 sample charter creation failed."
    }
}
if (-not (Test-Path -LiteralPath $activationPath -PathType Leaf)) {
    & $pythonPath -B -m momentum_hunter.successor_setup_observer activate `
        --charter $charterPath `
        --activated-at $activatedAt `
        --first-eligible-session-date $dateText `
        --expected-git-head $gitHead `
        --output $activationPath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "SETUP-002 prospective activation failed."
    }
}
& $pythonPath -B -m momentum_hunter.successor_setup_observer validate-activation `
    --charter $charterPath `
    --activation $activationPath `
    --expected-git-head $gitHead `
    --first-eligible-session-date $dateText | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "SETUP-002 activation record validation failed."
}

$manifest.jobs = @($manifest.jobs) + @($pass1, $pass2)
$temporaryManifest = Join-Path $env:TEMP (
    "momentum-hunter-successor-setup-$([guid]::NewGuid().ToString('N')).json"
)
$backupPath = "$manifestPath.$((Get-Date).ToString('yyyyMMddTHHmmss')).bak"
try {
    [System.IO.File]::WriteAllText(
        $temporaryManifest,
        ($manifest | ConvertTo-Json -Depth 10),
        [System.Text.UTF8Encoding]::new($false)
    )
    & $pythonPath -B -m momentum_hunter.automation_supervisor status `
        --manifest $temporaryManifest | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Planned SETUP-002 manifest failed supervisor validation."
    }
    Copy-Item -LiteralPath $manifestPath -Destination $backupPath
    $installPath = "$manifestPath.$([guid]::NewGuid().ToString('N')).tmp"
    Copy-Item -LiteralPath $temporaryManifest -Destination $installPath
    Move-Item -LiteralPath $installPath -Destination $manifestPath -Force

    $observed = @{}
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $current = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            foreach ($jobId in @($pass1Id, $pass2Id)) {
                $receipt = $current.jobs.$jobId
                if ($receipt) {
                    $observed[$jobId] = $receipt.status
                }
            }
            if ($observed.Count -eq 2) {
                break
            }
        }
    }
    if (
        $observed[$pass1Id] -ne "PENDING" -or
        $observed[$pass2Id] -ne "PENDING"
    ) {
        Copy-Item -LiteralPath $backupPath -Destination $manifestPath -Force
        throw "The supervisor did not hot-reload both research jobs as PENDING."
    }

    [ordered]@{
        activated = $true
        serviceName = $ServiceName
        manifestPath = $manifestPath
        previousManifest = $backupPath
        manifestSha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash
        expectedGitHead = $gitHead
        sessionDate = $dateText
        activationStatus = "ACTIVE_PROSPECTIVE_EMPTY"
        pass1Status = $observed[$pass1Id]
        pass2Status = $observed[$pass2Id]
        providerCalls = $false
        accountCalls = $false
        shadowMutation = $false
        paperMutation = $false
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json -Depth 6
}
finally {
    Remove-Item -LiteralPath $temporaryManifest -Force -ErrorAction SilentlyContinue
}
