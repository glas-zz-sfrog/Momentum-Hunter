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

    [Parameter(Mandatory = $true)]
    [string]$ConfigurationPath,

    [ValidateRange(1, 10)]
    [int]$MaximumAttempts = 5,

    [ValidateRange(1, 60)]
    [int]$RestartDelaySeconds = 2
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$taskId = 'ARGUS-THINKORSWIM-OVERNIGHT-RTD-001'
$runner = Join-Path $ProjectRoot 'tools\run_thinkorswim_rtd_campaign.ps1'
foreach ($path in @($runner, $ConfigurationPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required supervised campaign file is missing: $path"
    }
}

function Write-JsonCreateNew([string]$Path, [object]$Value, [int]$Depth = 10) {
    $parent = Split-Path -Parent $Path
    if ($parent) { [IO.Directory]::CreateDirectory($parent) | Out-Null }
    $payload = ($Value | ConvertTo-Json -Depth $Depth) + "`n"
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
        try {
            $writer.Write($payload)
            $writer.Flush()
            $stream.Flush($true)
        }
        finally { $writer.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Write-JsonAtomic([string]$Path, [object]$Value, [int]$Depth = 10) {
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = "$Path.$PID.tmp"
    $payload = ($Value | ConvertTo-Json -Depth $Depth) + "`n"
    [IO.File]::WriteAllText($temporary, $payload, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

$configuration = Get-Content -Raw -LiteralPath $ConfigurationPath | ConvertFrom-Json
$lastCheckpoint = @($configuration.checkpoints)[-1]
$terminalDeadline = [DateTimeOffset]::Parse($lastCheckpoint.scheduledAtEastern).AddSeconds(
    [int]$configuration.checkpointDurationSeconds + 300
)
$attempt = 0
$resume = $false
$env:MOMENTUM_HUNTER_RTD_SUPERVISOR_PID = [string]$PID

while ($attempt -lt $MaximumAttempts) {
    $attempt++
    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $runner,
        '-ProjectRoot', $ProjectRoot,
        '-CanonicalRoot', $CanonicalRoot,
        '-EvidenceRoot', $EvidenceRoot,
        '-ExpectedSourceHead', $ExpectedSourceHead,
        '-ConfigurationPath', $ConfigurationPath
    )
    if ($resume) { $arguments += '-Resume' }

    $child = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList $arguments -PassThru
    $status = [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        status = 'CHILD_RUNNING'
        observedAt = [DateTimeOffset]::Now.ToString('o')
        supervisorProcessId = $PID
        childProcessId = $child.Id
        attempt = $attempt
        resume = $resume
    }
    $rootDeadline = [DateTimeOffset]::Now.AddSeconds(30)
    while (-not (Test-Path -LiteralPath $EvidenceRoot) -and [DateTimeOffset]::Now -lt $rootDeadline -and -not $child.HasExited) {
        Start-Sleep -Milliseconds 250
        $child.Refresh()
    }
    if (Test-Path -LiteralPath $EvidenceRoot) {
        Write-JsonAtomic (Join-Path $EvidenceRoot 'supervisor-status.json') $status
    }

    $child.WaitForExit()
    $exitCode = $child.ExitCode
    $attemptRecord = [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        supervisorProcessId = $PID
        childProcessId = $child.Id
        attempt = $attempt
        resume = $resume
        exitCode = $exitCode
        completedAt = [DateTimeOffset]::Now.ToString('o')
    }
    if (Test-Path -LiteralPath $EvidenceRoot) {
        Write-JsonCreateNew (Join-Path $EvidenceRoot ("supervisor-attempts\attempt-{0:D2}.json" -f $attempt)) $attemptRecord
    }
    if ($exitCode -eq 0) {
        if (Test-Path -LiteralPath $EvidenceRoot) {
            Write-JsonAtomic (Join-Path $EvidenceRoot 'supervisor-status.json') ([ordered]@{
                schemaVersion = 1
                taskId = $taskId
                status = 'COMPLETE'
                observedAt = [DateTimeOffset]::Now.ToString('o')
                supervisorProcessId = $PID
                attempts = $attempt
            })
        }
        exit 0
    }
    if ([DateTimeOffset]::Now -gt $terminalDeadline) { break }
    $resume = $true
    Start-Sleep -Seconds $RestartDelaySeconds
}

if (Test-Path -LiteralPath $EvidenceRoot) {
    Write-JsonAtomic (Join-Path $EvidenceRoot 'supervisor-status.json') ([ordered]@{
        schemaVersion = 1
        taskId = $taskId
        status = 'FAILED'
        observedAt = [DateTimeOffset]::Now.ToString('o')
        supervisorProcessId = $PID
        attempts = $attempt
        maximumAttempts = $MaximumAttempts
    })
}
exit 1
