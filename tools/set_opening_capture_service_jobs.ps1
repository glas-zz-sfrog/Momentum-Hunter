[CmdletBinding()]
param(
    [datetime]$StartDate = (Get-Date).Date.AddDays(1),
    [ValidateRange(1, 90)]
    [int]$MarketSessions = 30,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "",
    [string]$ServiceRoot = "C:\ProgramData\MomentumHunter\Automation",
    [string]$ServiceName = "MomentumHunterAutomation",
    [switch]$EnableOpeningCaptures,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

if (-not $EnableOpeningCaptures) {
    throw "The exact -EnableOpeningCaptures interlock is required."
}
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Opening captures require the Windows Central Standard Time zone."
}
if ($StartDate.Date -lt (Get-Date).Date) {
    throw "Opening captures must begin today or later."
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
    throw "The repository must be clean before installing opening captures."
}
$gitHead = (& git -C $projectPath rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $gitHead -notmatch '^[0-9a-f]{40}$') {
    throw "The canonical repository HEAD could not be frozen."
}

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

$terminalPaperJobIds = @()
if ($state) {
    $terminalStatuses = @(
        "COMPLETED",
        "FAILED",
        "MISSED",
        "BLOCKED_DEPENDENCY",
        "DISABLED"
    )
    $terminalPaperJobIds = @(
        $state.jobs.PSObject.Properties.Value |
            Where-Object {
                $_.kind -eq "paper_engineering" -and
                $_.status -in $terminalStatuses
            } |
            ForEach-Object { $_.job_id }
    )
}

$temporaryManifest = Join-Path $env:TEMP (
    "momentum-hunter-opening-captures-$([guid]::NewGuid().ToString('N')).json"
)
try {
    $plannerArguments = @(
        "-B",
        "-m",
        "momentum_hunter.automation_opening_capture",
        "--manifest",
        $manifestPath,
        "--output",
        $temporaryManifest,
        "--start-date",
        $StartDate.ToString("yyyy-MM-dd"),
        "--expected-git-head",
        $gitHead,
        "--market-sessions",
        $MarketSessions
    )
    foreach ($terminalJobId in $terminalPaperJobIds) {
        $plannerArguments += @("--terminal-job-id", $terminalJobId)
    }
    $plannerOutput = & $pythonPath @plannerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Opening capture manifest planning failed."
    }
    $summary = ($plannerOutput -join [Environment]::NewLine) | ConvertFrom-Json
    $plannedManifest = Get-Content -LiteralPath $temporaryManifest -Raw | ConvertFrom-Json

    if ($PlanOnly) {
        [ordered]@{
            planOnly = $true
            manifestPath = $manifestPath
            openingCaptureJobs = $summary.openingCaptureJobs
            marketSessionsCovered = $summary.marketSessionsCovered
            firstOpeningCapture = $summary.firstOpeningCapture
            lastOpeningCapture = $summary.lastOpeningCapture
            expectedGitHead = $gitHead
            shadowDatesUseShadowCapture = $summary.shadowDatesUseShadowCapture
            jobs = @(
                $plannedManifest.jobs |
                    Where-Object { $_.kind -eq "opening_capture" }
            )
            selectorArming = "UNAVAILABLE"
            orderTransmission = "UNAVAILABLE"
        } | ConvertTo-Json -Depth 8
        exit 0
    }

    $backupPath = "$manifestPath.$((Get-Date).ToString('yyyyMMddTHHmmss')).bak"
    Copy-Item -LiteralPath $manifestPath -Destination $backupPath
    $installPath = "$manifestPath.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        Copy-Item -LiteralPath $temporaryManifest -Destination $installPath
        Move-Item -LiteralPath $installPath -Destination $manifestPath -Force
    }
    finally {
        Remove-Item -LiteralPath $installPath -Force -ErrorAction SilentlyContinue
    }

    $firstJobId = @(
        $plannedManifest.jobs |
            Where-Object { $_.kind -eq "opening_capture" } |
            Select-Object -First 1
    ).jobId
    $observedStatus = "NOT_OBSERVED"
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline -and $firstJobId) {
        Start-Sleep -Milliseconds 500
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $observed = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            $receipt = $observed.jobs.$firstJobId
            if ($receipt) {
                $observedStatus = $receipt.status
                break
            }
        }
    }
    if ($firstJobId -and $observedStatus -ne "PENDING") {
        throw (
            "The manifest was installed, but the running supervisor did not " +
            "hot-reload the first opening job."
        )
    }

    [ordered]@{
        updated = $true
        serviceName = $ServiceName
        manifestPath = $manifestPath
        previousManifest = $backupPath
        openingCaptureJobs = $summary.openingCaptureJobs
        marketSessionsCovered = $summary.marketSessionsCovered
        firstOpeningCapture = $summary.firstOpeningCapture
        lastOpeningCapture = $summary.lastOpeningCapture
        expectedGitHead = $gitHead
        firstJobStatus = $observedStatus
        selectorArming = "UNAVAILABLE"
        orderTransmission = "UNAVAILABLE"
    } | ConvertTo-Json -Depth 5
}
finally {
    Remove-Item -LiteralPath $temporaryManifest -Force -ErrorAction SilentlyContinue
}
