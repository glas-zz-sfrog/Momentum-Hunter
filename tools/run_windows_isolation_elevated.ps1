[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$ProjectRoot,
    [Parameter(Mandatory = $true)] [string]$CanonicalRoot,
    [Parameter(Mandatory = $true)] [string]$OutputPath,
    [Parameter(Mandatory = $true)] [string]$RunId,
    [Parameter(Mandatory = $true)] [string]$GitExecutable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "The physical distinct-principal proof requires an elevated process."
}
if ($RunId -notmatch '^[a-f0-9]{16}$') {
    throw "RunId must be exactly sixteen lowercase hexadecimal characters."
}

$actorSource = Join-Path $ProjectRoot "tools\windows_isolation_actor.ps1"
if (-not (Test-Path -LiteralPath $actorSource -PathType Leaf)) {
    throw "The physical proof actor is missing."
}
$testBase = "C:\MomentumHunterIsolationProof"
$toolBase = "C:\MomentumHunterIsolationProofTools"
$controlBase = "C:\MomentumHunterIsolationProofControl"
$testRoot = Join-Path $testBase $RunId
$toolRoot = Join-Path $toolBase $RunId
$controlRoot = Join-Path $controlBase $RunId
$actorPath = Join-Path $toolRoot "actor.ps1"
$manifestPath = "C:\ProgramData\MomentumHunter\Automation\automation-manifest.json"
$taskPrefix = "Momentum Hunter Isolation Proof $RunId"
$createdTasks = [Collections.Generic.List[string]]::new()
$actorPayload = $null
$result = [ordered]@{
    schemaVersion = 1
    profile = "continuous-windows-isolation-elevated-proof-v1"
    authority = "TEST_ONLY_NO_RUNTIME_AUTHORITY"
    runId = $RunId
    startedAt = [DateTimeOffset]::UtcNow.ToString("o")
    elevatedIdentity = [ordered]@{
        name = $identity.Name
        sid = $identity.User.Value
        processId = $PID
        administrator = $true
    }
    testRoot = $testRoot
    writerPrincipal = "NT AUTHORITY\LOCAL SERVICE"
    writerSid = "S-1-5-19"
    actors = [ordered]@{}
    handleDuplication = [ordered]@{}
    acl = [ordered]@{}
    productionBefore = [ordered]@{}
    productionAfter = [ordered]@{}
    startOrder = [ordered]@{
        writerFirst = "PROCESS_LAUNCHED_AND_TERMINATED"
        nonwriterFirst = "ACCESS_PROBE_LAUNCHED_AND_TERMINATED"
        simultaneous = "NOT_PROVEN_NO_INSTALLED_RUNTIME_PROCESS"
        delayedWriter = "LOGICAL_RUNTIME_BACKPRESSURE_ONLY"
    }
    cleanup = [ordered]@{}
    error = $null
}

function Get-Sha256Hex {
    param([byte[]]$Bytes)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($Bytes)
        return ([BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
}

function Remove-DisposableProofTree {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    & takeown.exe /F $Path /R /D Y | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not take ownership of disposable proof path $Path."
    }
    & icacls.exe $Path `
        /grant "*$($identity.User.Value):(OI)(CI)F" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant cleanup access to disposable proof path $Path."
    }
    & cmd.exe /d /c rd /s /q $Path
    if ((Test-Path -LiteralPath $Path) -or $LASTEXITCODE -ne 0) {
        throw "Could not remove disposable proof path $Path."
    }
}

function Remove-OrphanedProofRuns {
    param([string[]]$Bases)
    foreach ($base in $Bases) {
        if (-not (Test-Path -LiteralPath $base -PathType Container)) {
            continue
        }
        & takeown.exe /F $base /R /D Y | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not take ownership of disposable proof base $base."
        }
        & icacls.exe $base `
            /grant "*$($identity.User.Value):(OI)(CI)F" /T /C | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not grant cleanup access to disposable proof base $base."
        }
        foreach ($child in Get-ChildItem -LiteralPath $base -Directory -Force) {
            if ($child.Name -notmatch '^[a-f0-9]{16}$') {
                throw "Unexpected item exists beneath disposable proof base $base."
            }
            Remove-DisposableProofTree -Path $child.FullName
        }
    }
}

function Get-ProductionState {
    $service = Get-CimInstance Win32_Service -Filter "Name='MomentumHunterAutomation'"
    $manifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash
    $head = (& $GitExecutable -C $CanonicalRoot rev-parse HEAD).Trim()
    $status = (& $GitExecutable -C $CanonicalRoot status --short)
    return [ordered]@{
        serviceState = $service.State
        serviceStartMode = $service.StartMode
        serviceAccount = $service.StartName
        serviceProcessId = $service.ProcessId
        manifestSha256 = $manifestHash
        gitHead = $head
        gitClean = [string]::IsNullOrWhiteSpace(($status -join ""))
    }
}

function Write-CanonicalResult {
    param([string]$Path, [object]$Value)
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $value.fingerprint = ""
    $without = $Value | ConvertTo-Json -Depth 20 -Compress
    $hash = Get-Sha256Hex -Bytes ([Text.Encoding]::ASCII.GetBytes($without))
    $value.fingerprint = $hash
    $json = $Value | ConvertTo-Json -Depth 20 -Compress
    [IO.File]::WriteAllText(
        $Path,
        $json + "`n",
        [Text.UTF8Encoding]::new($false)
    )
}

function New-SeedRoot {
    param([string]$Path)
    [IO.Directory]::CreateDirectory($Path) | Out-Null
    foreach ($name in @(
        "seed.txt",
        "rename-source.txt",
        "delete-source.txt",
        "committed.json",
        "committed-delete.json",
        "partial.tmp",
        "readable.txt"
    )) {
        [IO.File]::WriteAllText(
            (Join-Path $Path $name),
            $name,
            [Text.Encoding]::ASCII
        )
    }
}

function Register-ProofTask {
    param(
        [string]$Name,
        [string]$Arguments,
        [ValidateSet("LocalService", "Limited", "Highest")]
        [string]$IdentityMode
    )
    $action = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -Argument $Arguments
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddHours(6)
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
        -MultipleInstances IgnoreNew `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries
    if ($IdentityMode -eq "LocalService") {
        $taskPrincipal = New-ScheduledTaskPrincipal `
            -UserId "NT AUTHORITY\LOCAL SERVICE" `
            -LogonType ServiceAccount `
            -RunLevel Limited
    } else {
        $runLevel = if ($IdentityMode -eq "Highest") { "Highest" } else { "Limited" }
        $taskPrincipal = New-ScheduledTaskPrincipal `
            -UserId $identity.Name `
            -LogonType Interactive `
            -RunLevel $runLevel
    }
    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $taskPrincipal `
        -Force | Out-Null
    $createdTasks.Add($Name)
}

function Quote-PowerShellLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function New-ActorTaskArguments {
    param(
        [string]$Command,
        [string]$LogPath
    )
    $wrapped = (
        "& { " + $Command + " } *> " + (Quote-PowerShellLiteral $LogPath) +
        "; if (`$LASTEXITCODE) { exit `$LASTEXITCODE }"
    )
    $encoded = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($wrapped)
    )
    return "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand $encoded"
}

function Get-ActorInvocationPrefix {
    if (-not $actorPayload) {
        throw "The disposable actor payload is not initialized."
    }
    return (
        "`$actorBytes=[Convert]::FromBase64String(" +
        (Quote-PowerShellLiteral $actorPayload) + ");" +
        "`$actorMemory=[IO.MemoryStream]::new(`$actorBytes);" +
        "`$actorGzip=[IO.Compression.GZipStream]::new(" +
        "`$actorMemory,[IO.Compression.CompressionMode]::Decompress);" +
        "`$actorReader=[IO.StreamReader]::new(`$actorGzip,[Text.Encoding]::UTF8);" +
        "`$actorBlock=[scriptblock]::Create(`$actorReader.ReadToEnd());" +
        "`$actorReader.Dispose();`$actorGzip.Dispose();`$actorMemory.Dispose();" +
        "[Array]::Clear(`$actorBytes,0,`$actorBytes.Length);" +
        "& `$actorBlock"
    )
}

function Wait-ProofTask {
    param([string]$Name, [int]$TimeoutSeconds = 120)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $sawRun = $false
    do {
        $task = Get-ScheduledTask -TaskName $Name
        $info = Get-ScheduledTaskInfo -TaskName $Name
        if ($task.State -in @("Running", "Queued") -or
            $info.LastRunTime.Year -gt 2000) {
            $sawRun = $true
        }
        if ($sawRun -and $task.State -notin @("Running", "Queued")) {
            return [ordered]@{
                state = [string]$task.State
                lastTaskResult = $info.LastTaskResult
                lastRunTime = $info.LastRunTime.ToUniversalTime().ToString("o")
            }
        }
        if ([DateTime]::UtcNow -ge $deadline) {
            throw "Temporary proof task $Name timed out."
        }
        Start-Sleep -Milliseconds 100
    } while ($true)
}

function Invoke-AccessTask {
    param(
        [string]$Suffix,
        [string]$IdentityMode,
        [string]$ActorRoot,
        [string]$ActorLabel
    )
    $taskName = "$taskPrefix $Suffix"
    $actorResult = Join-Path $controlRoot "$Suffix.json"
    $actorLog = Join-Path $controlRoot "$Suffix-output.txt"
    $command = (
        (Get-ActorInvocationPrefix) +
        " -Mode AccessMatrix -ResultPath " + (Quote-PowerShellLiteral $actorResult) +
        " -Root " + (Quote-PowerShellLiteral $ActorRoot) +
        " -ActorLabel " + (Quote-PowerShellLiteral $ActorLabel)
    )
    $arguments = New-ActorTaskArguments -Command $command -LogPath $actorLog
    Register-ProofTask -Name $taskName -Arguments $arguments -IdentityMode $IdentityMode
    Start-ScheduledTask -TaskName $taskName
    $taskResult = Wait-ProofTask -Name $taskName
    if (-not (Test-Path -LiteralPath $actorResult -PathType Leaf)) {
        $actorOutput = if (Test-Path -LiteralPath $actorLog) {
            (Get-Content -Raw -LiteralPath $actorLog).Trim()
        } else {
            "NOT_CREATED"
        }
        throw (
            "Temporary proof actor $ActorLabel did not create a result; " +
            "task state=$($taskResult.state), result=$($taskResult.lastTaskResult), " +
            "output=$actorOutput."
        )
    }
    $proof = Get-Content -Raw -LiteralPath $actorResult | ConvertFrom-Json
    if ($proof.profile -eq "continuous-windows-isolation-actor-failure-v1") {
        throw "Temporary proof actor $ActorLabel failed: $($proof.error.message)"
    }
    return [ordered]@{
        task = $taskResult
        proof = $proof
    }
}

function Invoke-DuplicateTask {
    param(
        [string]$Suffix,
        [string]$IdentityMode,
        [object]$Target
    )
    $taskName = "$taskPrefix $Suffix"
    $actorResult = Join-Path $controlRoot "$Suffix.json"
    $actorLog = Join-Path $controlRoot "$Suffix-output.txt"
    $command = (
        (Get-ActorInvocationPrefix) +
        " -Mode DuplicateHandle -ResultPath " + (Quote-PowerShellLiteral $actorResult) +
        " -TargetProcessId $($Target.processId)" +
        " -TargetHandle $($Target.handle)" +
        " -ExpectedSha256 $($Target.expectedSha256)"
    )
    $arguments = New-ActorTaskArguments -Command $command -LogPath $actorLog
    Register-ProofTask -Name $taskName -Arguments $arguments -IdentityMode $IdentityMode
    Start-ScheduledTask -TaskName $taskName
    $taskResult = Wait-ProofTask -Name $taskName
    if (-not (Test-Path -LiteralPath $actorResult -PathType Leaf)) {
        $actorOutput = if (Test-Path -LiteralPath $actorLog) {
            (Get-Content -Raw -LiteralPath $actorLog).Trim()
        } else {
            "NOT_CREATED"
        }
        throw (
            "Temporary duplicate-handle actor $Suffix did not create a result; " +
            "task state=$($taskResult.state), result=$($taskResult.lastTaskResult), " +
            "output=$actorOutput."
        )
    }
    $proof = Get-Content -Raw -LiteralPath $actorResult | ConvertFrom-Json
    if ($proof.profile -eq "continuous-windows-isolation-actor-failure-v1") {
        throw "Temporary duplicate-handle actor $Suffix failed: $($proof.error.message)"
    }
    return [ordered]@{
        task = $taskResult
        proof = $proof
    }
}

try {
    Remove-OrphanedProofRuns -Bases @($testBase, $toolBase, $controlBase)
    if ((Test-Path -LiteralPath $testRoot) -or
        (Test-Path -LiteralPath $toolRoot) -or
        (Test-Path -LiteralPath $controlRoot)) {
        throw "A test path for this run already exists."
    }
    $result.productionBefore = Get-ProductionState
    foreach ($path in @($testRoot, $toolRoot, $controlRoot)) {
        [IO.Directory]::CreateDirectory($path) | Out-Null
    }
    Copy-Item -LiteralPath $actorSource -Destination $actorPath
    $actorBytes = [IO.File]::ReadAllBytes($actorPath)
    $actorMemory = [IO.MemoryStream]::new()
    $actorGzip = [IO.Compression.GZipStream]::new(
        $actorMemory,
        [IO.Compression.CompressionMode]::Compress,
        $true
    )
    try {
        $actorGzip.Write($actorBytes, 0, $actorBytes.Length)
    } finally {
        $actorGzip.Dispose()
        [Array]::Clear($actorBytes, 0, $actorBytes.Length)
    }
    $actorPayload = [Convert]::ToBase64String($actorMemory.ToArray())
    $actorMemory.Dispose()
    $writerRoot = Join-Path $testRoot "writer"
    $limitedRoot = Join-Path $testRoot "limited"
    $highestRoot = Join-Path $testRoot "highest"
    $handleRoot = Join-Path $testRoot "handle"

    & icacls.exe $testBase /inheritance:r `
        /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-19:(OI)(CI)RX" `
        "*S-1-5-32-545:(OI)(CI)RX" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Test base ACL configuration failed." }
    & icacls.exe $toolBase /inheritance:r `
        /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-19:(OI)(CI)RX" `
        "*S-1-5-32-545:(OI)(CI)RX" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Test tool base ACL configuration failed." }
    & icacls.exe $controlBase /inheritance:r `
        /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-19:(OI)(CI)M" `
        "*S-1-5-32-545:(OI)(CI)M" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Test control base ACL configuration failed." }
    & icacls.exe $testRoot /inheritance:r `
        /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-19:(OI)(CI)M" `
        "*S-1-5-32-545:(OI)(CI)RX" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Test root ACL configuration failed." }
    & icacls.exe $testRoot /setowner "*S-1-5-18" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Test root ownership configuration failed." }
    & icacls.exe $toolRoot /inheritance:r `
        /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-19:(OI)(CI)RX" `
        "*S-1-5-32-545:(OI)(CI)RX" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Test tool ACL configuration failed." }
    & icacls.exe $controlRoot /inheritance:r `
        /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-19:(OI)(CI)M" `
        "*S-1-5-32-545:(OI)(CI)M" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Test control ACL configuration failed." }
    $result.acl = [ordered]@{
        testBase = (& icacls.exe $testBase) -join "`n"
        toolBase = (& icacls.exe $toolBase) -join "`n"
        controlBase = (& icacls.exe $controlBase) -join "`n"
        testRoot = (& icacls.exe $testRoot) -join "`n"
        toolRoot = (& icacls.exe $toolRoot) -join "`n"
        controlRoot = (& icacls.exe $controlRoot) -join "`n"
    }
    foreach ($path in @($writerRoot, $limitedRoot, $highestRoot, $handleRoot)) {
        New-SeedRoot -Path $path
    }

    $writerActor = Invoke-AccessTask `
        -Suffix "Writer" `
        -IdentityMode LocalService `
        -ActorRoot $writerRoot `
        -ActorLabel "DEDICATED_WRITER_LOCAL_SERVICE"
    $result.actors.localServiceWriter = $writerActor.proof

    $limitedActor = Invoke-AccessTask `
        -Suffix "Limited" `
        -IdentityMode Limited `
        -ActorRoot $limitedRoot `
        -ActorLabel "WPF_ENGINE_HOST_LIMITED_EQUIVALENT"
    $result.actors.limitedNonwriter = $limitedActor.proof

    $handleTask = "$taskPrefix HandleTarget"
    $handleControl = Join-Path $controlRoot "handle-control.json"
    $handleRelease = Join-Path $controlRoot "handle-release"
    $handleResult = Join-Path $controlRoot "handle-target-result.json"
    $handleLog = Join-Path $controlRoot "HandleTarget-output.txt"
    $handleCommand = (
        (Get-ActorInvocationPrefix) +
        " -Mode HandleTarget -ResultPath " + (Quote-PowerShellLiteral $handleResult) +
        " -Root " + (Quote-PowerShellLiteral $handleRoot) +
        " -ControlPath " + (Quote-PowerShellLiteral $handleControl) +
        " -ReleasePath " + (Quote-PowerShellLiteral $handleRelease) +
        " -TimeoutSeconds 120"
    )
    $handleArguments = New-ActorTaskArguments `
        -Command $handleCommand `
        -LogPath $handleLog
    Register-ProofTask `
        -Name $handleTask `
        -Arguments $handleArguments `
        -IdentityMode LocalService
    Start-ScheduledTask -TaskName $handleTask
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while (-not (Test-Path -LiteralPath $handleControl)) {
        if ([DateTime]::UtcNow -ge $deadline) {
            throw "LocalService handle target did not become ready."
        }
        Start-Sleep -Milliseconds 100
    }
    $handleTarget = Get-Content -Raw -LiteralPath $handleControl |
        ConvertFrom-Json
    $limitedDuplicate = Invoke-DuplicateTask `
        -Suffix "DuplicateLimited" `
        -IdentityMode Limited `
        -Target $handleTarget
    $result.handleDuplication.limitedNonwriter = $limitedDuplicate.proof
    $highestDuplicate = Invoke-DuplicateTask `
        -Suffix "DuplicateHighest" `
        -IdentityMode Highest `
        -Target $handleTarget
    $result.handleDuplication.highIntegrityNonwriter = $highestDuplicate.proof
    New-Item -ItemType File -Path $handleRelease | Out-Null
    $handleTaskResult = Wait-ProofTask -Name $handleTask
    $result.handleDuplication.target = [ordered]@{
        identity = $handleTarget.identity
        task = $handleTaskResult
        released = Test-Path -LiteralPath $handleResult
    }

    $highestActor = Invoke-AccessTask `
        -Suffix "Highest" `
        -IdentityMode Highest `
        -ActorRoot $highestRoot `
        -ActorLabel "ENGINE_HOST_HIGH_INTEGRITY_EQUIVALENT"
    $result.actors.highIntegrityNonwriter = $highestActor.proof
} catch {
    $result.error = [ordered]@{
        type = $_.Exception.GetType().Name
        message = $_.Exception.Message
        scriptStackTrace = $_.ScriptStackTrace
    }
} finally {
    foreach ($taskName in $createdTasks) {
        try {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
        } catch {
            $result.cleanup["task:$taskName"] = "FAILED:$($_.Exception.GetType().Name)"
        }
    }
    foreach ($path in @($testRoot, $toolRoot, $controlRoot)) {
        try {
            if (Test-Path -LiteralPath $path) {
                Remove-DisposableProofTree -Path $path
            }
            $result.cleanup["path:$path"] = -not (Test-Path -LiteralPath $path)
        } catch {
            $result.cleanup["path:$path"] = "FAILED:$($_.Exception.GetType().Name)"
        }
    }
    foreach ($base in @($testBase, $toolBase, $controlBase)) {
        try {
            if ((Test-Path -LiteralPath $base) -and
                -not (Get-ChildItem -LiteralPath $base -Force | Select-Object -First 1)) {
                & takeown.exe /F $base /D Y | Out-Null
                & icacls.exe $base /grant "*$($identity.User.Value):F" | Out-Null
                Remove-Item -LiteralPath $base -Force
            }
        } catch {
            $result.cleanup["base:$base"] = "FAILED:$($_.Exception.GetType().Name)"
        }
    }
    try {
        $result.productionAfter = Get-ProductionState
    } catch {
        $result.productionAfter = [ordered]@{
            inspectionError = $_.Exception.GetType().Name
        }
    }
    $result.finishedAt = [DateTimeOffset]::UtcNow.ToString("o")
    Write-CanonicalResult -Path $OutputPath -Value $result
}

if ($result.error) {
    exit 1
}
