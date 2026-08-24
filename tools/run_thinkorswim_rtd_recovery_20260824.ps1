[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CanonicalRoot,

    [Parameter(Mandatory = $true)]
    [string]$EvidenceRoot,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedCanonicalHead,

    [ValidateSet('PAPERMONEY', 'LIVE')]
    [string]$RequiredMode = 'PAPERMONEY',

    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$taskId = 'ARGUS-THINKORSWIM-OVERNIGHT-RTD-001'
$recoveryId = if ($RequiredMode -eq 'LIVE') {
    'RTD-OVERNIGHT-LIVE-MARKET-ONLY-20260824'
} else {
    'RTD-OVERNIGHT-RECOVERY-20260824'
}
$symbols = @('SPY', 'QQQ', 'NVDA', 'AAPL', 'MU')
$fields = @(
    'SYMBOL', 'DESCRIPTION', 'LAST', 'BID', 'ASK', 'MARK', 'LAST_SIZE',
    'BID_SIZE', 'ASK_SIZE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME',
    'EXCHANGE'
)
$sampleIntervalSeconds = 2
$checkpointDurationSeconds = 120
$checkpoints = @(
    [ordered]@{
        checkpointId = 'RECOVERY_G_0255_CT'
        scheduledAtCentral = '2026-08-24T02:55:00-05:00'
    },
    [ordered]@{
        checkpointId = 'RECOVERY_H_0305_CT'
        scheduledAtCentral = '2026-08-24T03:05:00-05:00'
    }
)

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '')
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Write-JsonCreateNew([string]$Path, [object]$Value, [int]$Depth = 16) {
    $parent = Split-Path -Parent $Path
    if ($parent) {
        [IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $payload = ($Value | ConvertTo-Json -Depth $Depth) + "`n"
    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    try {
        $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
        try {
            $writer.Write($payload)
            $writer.Flush()
            $stream.Flush($true)
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Write-JsonAtomic([string]$Path, [object]$Value, [int]$Depth = 16) {
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = "$Path.$PID.tmp"
    $payload = ($Value | ConvertTo-Json -Depth $Depth) + "`n"
    [IO.File]::WriteAllText($temporary, $payload, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Invoke-ExcelComCall(
    [scriptblock]$Action,
    [string]$Operation,
    [int]$MaxAttempts = 80,
    [int]$DelayMilliseconds = 250
) {
    $retryable = @('80010001', '8001010A', '800AC472')
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            return & $Action
        }
        catch [Runtime.InteropServices.COMException] {
            $code = $_.Exception.HResult.ToString('X8')
            if ($retryable -contains $code -and $attempt -lt $MaxAttempts) {
                Start-Sleep -Milliseconds $DelayMilliseconds
                continue
            }
            throw "Excel COM operation '$Operation' failed at attempt $attempt with HRESULT 0x$code."
        }
        catch {
            throw "Excel COM operation '$Operation' failed with $($_.Exception.GetType().Name): $($_.Exception.Message)"
        }
    }
    throw "Excel COM operation '$Operation' exhausted its bounded retry loop."
}

function Convert-CellValue([object]$Value) {
    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [datetime]) {
        return $Value.ToString('o')
    }
    if ($Value -is [decimal] -or $Value -is [double] -or $Value -is [single]) {
        return [double]$Value
    }
    if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [int32] -or $Value -is [int64]) {
        return [long]$Value
    }
    return [string]$Value
}

function Get-FormulaManifest {
    $cells = @()
    $row = 2
    foreach ($symbol in $symbols) {
        $column = 2
        foreach ($field in $fields) {
            $cells += [ordered]@{
                row = $row
                column = $column
                symbol = $symbol
                field = $field
                formula = "=RTD(`"tos.rtd`",,`"$field`",`"$symbol`")"
            }
            $column++
        }
        $row++
    }
    return [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        recoveryId = $recoveryId
        symbols = $symbols
        fields = $fields
        sampleIntervalSeconds = $sampleIntervalSeconds
        providerTimestampAvailable = $false
        timestampAuthority = 'LOCAL_OBSERVATION_TIMESTAMP_ONLY'
        cells = $cells
    }
}

function Get-CanonicalState {
    $head = (& git -C $CanonicalRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read canonical Git head.' }
    $origin = (& git -C $CanonicalRoot rev-parse origin/master).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read origin/master.' }
    $status = @(& git -C $CanonicalRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read canonical Git status.' }
    return [ordered]@{
        head = $head
        originMaster = $origin
        clean = ($status.Count -eq 0)
    }
}

function Assert-CanonicalFrozen {
    $state = Get-CanonicalState
    if ($state.head -ne $ExpectedCanonicalHead) {
        throw "Canonical Git changed: expected $ExpectedCanonicalHead, observed $($state.head)."
    }
    if ($state.originMaster -ne $ExpectedCanonicalHead) {
        throw "origin/master changed: expected $ExpectedCanonicalHead, observed $($state.originMaster)."
    }
    if (-not $state.clean) {
        throw 'Canonical checkout is dirty.'
    }
    return $state
}

function Get-ProductionSnapshot {
    $manifest = 'C:\ProgramData\MomentumHunter\Automation\automation-manifest.json'
    $services = @()
    foreach ($name in @(
        'MomentumHunterAutomation',
        'MomentumHunterContinuousRuntime',
        'MomentumHunterContinuousWriter'
    )) {
        $service = Get-CimInstance Win32_Service -Filter "Name='$name'" -ErrorAction SilentlyContinue
        if ($null -ne $service) {
            $services += [ordered]@{
                name = $name
                state = $service.State
                startMode = $service.StartMode
                startName = $service.StartName
                pathName = $service.PathName
            }
        }
    }
    return [ordered]@{
        observedAt = [DateTimeOffset]::Now.ToString('o')
        canonical = Get-CanonicalState
        manifestPath = $manifest
        manifestSha256 = if (Test-Path -LiteralPath $manifest) { Get-Sha256 $manifest } else { $null }
        services = $services
    }
}

function Get-ClientLogTextSince([long]$StartOffset) {
    $path = 'C:\Program Files\thinkorswim\client.log'
    if (-not (Test-Path -LiteralPath $path)) {
        return ''
    }
    $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        if ($stream.Length -lt $StartOffset) {
            $StartOffset = 0
        }
        [void]$stream.Seek($StartOffset, [IO.SeekOrigin]::Begin)
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true, 4096, $true)
        try {
            return $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Wait-ForThinkorswimMode([DateTimeOffset]$Deadline) {
    $stableLiveProcessId = $null
    $stableLiveSince = $null
    while ([DateTimeOffset]::Now -lt $Deadline) {
        $processes = @(Get-Process -Name thinkorswim -ErrorAction SilentlyContinue)
        if ($processes.Count -eq 1) {
            $title = $processes[0].MainWindowTitle
            if ($RequiredMode -eq 'PAPERMONEY' -and $title -like 'Paper@thinkorswim*') {
                return $processes[0]
            }
            $isStableLiveWindowShape = (
                $RequiredMode -eq 'LIVE' -and
                $title -match '(?i)thinkorswim \[build [0-9]+\]' -and
                $title -notlike 'Paper@thinkorswim*' -and
                $title -notlike '*updater*'
            )
            if ($isStableLiveWindowShape) {
                $newLogText = Get-ClientLogTextSince $script:clientLogStartLength
                $liveModeObserved = $newLogText.Contains('liveTrading=true')
                if ($liveModeObserved) {
                    if ($stableLiveProcessId -ne $processes[0].Id) {
                        $stableLiveProcessId = $processes[0].Id
                        $stableLiveSince = [DateTimeOffset]::Now
                    }
                    elseif (([DateTimeOffset]::Now - $stableLiveSince).TotalSeconds -ge 15) {
                        return $processes[0]
                    }
                }
            }
            else {
                $stableLiveProcessId = $null
                $stableLiveSince = $null
            }
            if ($title -and $title -notlike 'Logon to thinkorswim*') {
                if ($RequiredMode -eq 'PAPERMONEY' -or $title -like 'Paper@thinkorswim*') {
                    throw "RECOVERY_BLOCKED_CONFIGURATION_IDENTITY_UNPROVEN: unexpected thinkorswim mode."
                }
            }
        }
        elseif ($processes.Count -gt 1) {
            throw "RECOVERY_BLOCKED_CONFIGURATION_IDENTITY_UNPROVEN: found $($processes.Count) thinkorswim processes."
        }
        Start-Sleep -Seconds 2
    }
    throw "RECOVERY_BLOCKED_CONFIGURATION_IDENTITY_UNPROVEN: $RequiredMode login was not established before the bounded deadline."
}

function New-ExcelSession([object]$FormulaManifest) {
    $existing = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue)
    if ($existing.Count -ne 0) {
        throw "Recovery requires zero pre-existing Excel processes; found $($existing.Count)."
    }
    $excel = $null
    $workbook = $null
    $sheet = $null
    try {
        $excel = New-Object -ComObject Excel.Application
        Invoke-ExcelComCall { $excel.Visible = $false } 'SET_VISIBLE_FALSE' | Out-Null
        Invoke-ExcelComCall { $excel.DisplayAlerts = $false } 'SET_DISPLAY_ALERTS_FALSE' | Out-Null
        Invoke-ExcelComCall { $excel.EnableEvents = $false } 'SET_ENABLE_EVENTS_FALSE' | Out-Null
        Invoke-ExcelComCall { $excel.AskToUpdateLinks = $false } 'SET_ASK_TO_UPDATE_LINKS_FALSE' | Out-Null
        $workbook = Invoke-ExcelComCall { $excel.Workbooks.Add() } 'CREATE_WORKBOOK'
        $sheet = Invoke-ExcelComCall { $workbook.Worksheets.Item(1) } 'GET_WORKSHEET'
        Invoke-ExcelComCall { $sheet.Name = 'MARKET_RTD_ONLY' } 'NAME_WORKSHEET' | Out-Null
        foreach ($cell in @($FormulaManifest.cells)) {
            $row = [int]$cell.row
            $column = [int]$cell.column
            $formula = [string]$cell.formula
            Invoke-ExcelComCall { $sheet.Cells.Item($row, $column).Formula = $formula } "SET_FORMULA_${row}_${column}" | Out-Null
        }
        Invoke-ExcelComCall { $excel.CalculateFull() } 'CALCULATE_FULL' | Out-Null
        Start-Sleep -Seconds 15
        $processes = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue)
        if ($processes.Count -ne 1) {
            throw "Expected exactly one recovery Excel process; found $($processes.Count)."
        }
        return [ordered]@{
            application = $excel
            workbook = $workbook
            sheet = $sheet
            processId = $processes[0].Id
            processStart = $processes[0].StartTime.ToString('o')
        }
    }
    catch {
        try { if ($null -ne $workbook) { $workbook.Close($false) } } catch {}
        try { if ($null -ne $excel) { $excel.Quit() } } catch {}
        throw
    }
}

function Close-ExcelSession([object]$Session) {
    try { Invoke-ExcelComCall { $Session.workbook.Close($false) } 'CLOSE_WORKBOOK' | Out-Null } catch {}
    try { Invoke-ExcelComCall { $Session.application.Quit() } 'QUIT_EXCEL' | Out-Null } catch {}
    foreach ($item in @($Session.sheet, $Session.workbook, $Session.application)) {
        if ($null -ne $item) {
            try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($item) } catch {}
        }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

function Observe-Checkpoint(
    [object]$Session,
    [object]$FormulaManifest,
    [object]$Checkpoint,
    [string]$CheckpointRoot
) {
    [IO.Directory]::CreateDirectory($CheckpointRoot) | Out-Null
    $observationPath = Join-Path $CheckpointRoot 'observations.ndjson'
    $stream = [IO.File]::Open(
        $observationPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
    $started = [DateTimeOffset]::Now
    $deadline = $started.AddSeconds($checkpointDurationSeconds)
    $sampleCount = 0
    try {
        while ([DateTimeOffset]::Now -lt $deadline) {
            $matrix = Invoke-ExcelComCall { ,($Session.sheet.Range('B2', 'P6').Value2) } 'READ_MARKET_MATRIX'
            if ($null -eq $matrix -or $matrix.Rank -ne 2) {
                throw 'Excel market matrix was null or not two-dimensional.'
            }
            $rowLower = $matrix.GetLowerBound(0)
            $columnLower = $matrix.GetLowerBound(1)
            $values = @()
            foreach ($cell in @($FormulaManifest.cells)) {
                $matrixRow = $rowLower + ([int]$cell.row - 2)
                $matrixColumn = $columnLower + ([int]$cell.column - 2)
                $values += [ordered]@{
                    symbol = $cell.symbol
                    field = $cell.field
                    value = Convert-CellValue $matrix[$matrixRow, $matrixColumn]
                }
            }
            $tos = @(Get-Process -Name thinkorswim -ErrorAction SilentlyContinue)
            $sample = [ordered]@{
                schemaVersion = 1
                taskId = $taskId
                recoveryId = $recoveryId
                checkpointId = $Checkpoint.checkpointId
                scheduledAtCentral = $Checkpoint.scheduledAtCentral
                observedAt = [DateTimeOffset]::Now.ToString('o')
                timestampAuthority = 'LOCAL_OBSERVATION_TIMESTAMP_ONLY'
                sampleNumber = $sampleCount + 1
                thinkorswim = if ($tos.Count -eq 1) {
                    [ordered]@{running=$true; processId=$tos[0].Id; windowTitle=$tos[0].MainWindowTitle}
                } else {
                    [ordered]@{running=$false; processCount=$tos.Count}
                }
                values = $values
            }
            $writer.WriteLine(($sample | ConvertTo-Json -Compress -Depth 10))
            $writer.Flush()
            $sampleCount++
            Start-Sleep -Seconds $sampleIntervalSeconds
        }
        $stream.Flush($true)
    }
    finally {
        $writer.Dispose()
        $stream.Dispose()
    }
    $receipt = [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        recoveryId = $recoveryId
        checkpointId = $Checkpoint.checkpointId
        scheduledAtCentral = $Checkpoint.scheduledAtCentral
        startedAt = $started.ToString('o')
        completedAt = [DateTimeOffset]::Now.ToString('o')
        sampleCount = $sampleCount
        observationSha256 = Get-Sha256 $observationPath
    }
    Write-JsonCreateNew (Join-Path $CheckpointRoot 'checkpoint-receipt.json') $receipt
    return $receipt
}

$formulaManifest = Get-FormulaManifest
if ($symbols.Count -ne 5 -or $fields.Count -ne 15 -or @($formulaManifest.cells).Count -ne 75) {
    throw 'Frozen recovery field contract is invalid.'
}
if ($sampleIntervalSeconds -ne 2 -or $checkpointDurationSeconds -ne 120) {
    throw 'Frozen recovery timing contract is invalid.'
}

if ($ValidateOnly) {
    [ordered]@{
        status = 'VALIDATED_NO_EXTERNAL_CONTACT'
        taskId = $taskId
        recoveryId = $recoveryId
        requiredMode = $RequiredMode
        symbols = $symbols.Count
        fields = $fields.Count
        cells = @($formulaManifest.cells).Count
        sampleIntervalSeconds = $sampleIntervalSeconds
        checkpointDurationSeconds = $checkpointDurationSeconds
        checkpoints = $checkpoints
    } | ConvertTo-Json -Depth 8
    exit 0
}

if (Test-Path -LiteralPath $EvidenceRoot) {
    throw "Recovery evidence root already exists: $EvidenceRoot"
}
[IO.Directory]::CreateDirectory($EvidenceRoot) | Out-Null

$scriptPath = $MyInvocation.MyCommand.Path
$productionStart = Get-ProductionSnapshot
$canonicalStart = Assert-CanonicalFrozen
$baseline = [ordered]@{
    schemaVersion = 1
    taskId = $taskId
    recoveryId = $recoveryId
    classification = 'BOUNDED_RECOVERY_AFTER_MANUAL_TOS_INTERRUPTION'
    createdAt = [DateTimeOffset]::Now.ToString('o')
    sourcePath = $scriptPath
    sourceSha256 = Get-Sha256 $scriptPath
    canonicalStart = $canonicalStart
    productionStart = $productionStart
    intendedMode = $RequiredMode
    intendedModeEvidence = if ($RequiredMode -eq 'PAPERMONEY') {
        @(
            'environment-baseline.json windowTitle Paper@thinkorswim',
            'dynamic_schedules_cache.*.papermoney-desktop.schwab.com.xml',
            'workspace.*.tos.demo.xml'
        )
    } else {
        @(
            'CEO mode decision received 2026-08-24',
            'current-launch client.log liveTrading=true required before admission',
            'Paper@thinkorswim title explicitly rejected'
        )
    }
    fieldContract = $formulaManifest
    checkpoints = $checkpoints
    manualIntervention = [ordered]@{
        classification = 'DOCUMENTED_MANUAL_INTERVENTION'
        approximateStart = '2026-08-24T01:14:00-05:00'
        localFileActivityStart = '2026-08-24T01:15:25-05:00'
        localFileActivityEnd = '2026-08-24T01:22:58-05:00'
        excelObserved = $false
        rtdObserverObserved = $false
        rtdObservationsCreated = $false
        effect = 'UNINTERRUPTED_STABILITY_NOT_PROVEN_MANUAL_INTERVENTION'
    }
    elapsedCheckpointAdjudication = @(
        [ordered]@{checkpoint='2026-08-23T18:55:00-05:00';classification='MISSING'},
        [ordered]@{checkpoint='2026-08-23T19:00:00-05:00';classification='MISSING'},
        [ordered]@{checkpoint='2026-08-23T19:05:00-05:00';classification='MISSING'},
        [ordered]@{checkpoint='2026-08-23T20:00:00-05:00';classification='MISSING'},
        [ordered]@{checkpoint='2026-08-23T23:30:00-05:00';classification='MISSING'},
        [ordered]@{checkpoint='2026-08-24T00:30:00-05:00';classification='MISSING'}
    )
}
Write-JsonCreateNew (Join-Path $EvidenceRoot 'recovery-baseline.json') $baseline
Write-JsonCreateNew (Join-Path $EvidenceRoot 'formula-manifest.json') $formulaManifest
Write-JsonAtomic (Join-Path $EvidenceRoot 'recovery-status.json') ([ordered]@{
    taskId=$taskId; recoveryId=$recoveryId; status=("WAITING_FOR_{0}_LOGIN" -f $RequiredMode); observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID
})

$excelSession = $null
try {
    $firstStart = [DateTimeOffset]::Parse($checkpoints[0].scheduledAtCentral).AddSeconds(-60)
    $loginDeadline = $firstStart.AddMinutes(-10)
    $clientLogPath = 'C:\Program Files\thinkorswim\client.log'
    $script:clientLogStartLength = if (Test-Path -LiteralPath $clientLogPath) {
        (Get-Item -LiteralPath $clientLogPath).Length
    } else {
        0
    }
    $tos = Wait-ForThinkorswimMode $loginDeadline
    $tosPath = $tos.Path
    $rtdClsid = (Get-ItemProperty 'Registry::HKEY_CLASSES_ROOT\tos.rtd\CLSID' -ErrorAction Stop).'(default)'
    $rtdPath = (Get-ItemProperty "Registry::HKEY_CLASSES_ROOT\CLSID\$rtdClsid\InprocServer32" -ErrorAction Stop).'(default)'
    $restoration = [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        recoveryId = $recoveryId
        restoredAt = [DateTimeOffset]::Now.ToString('o')
        mode = $RequiredMode
        thinkorswim = [ordered]@{
            processId = $tos.Id
            processStart = $tos.StartTime.ToString('o')
            windowTitle = $tos.MainWindowTitle
            executablePath = $tosPath
            executableSha256 = Get-Sha256 $tosPath
        }
        rtd = [ordered]@{
            progId = 'tos.rtd'
            clsid = $rtdClsid
            serverPath = $rtdPath
            serverSha256 = Get-Sha256 $rtdPath
        }
    }
    Write-JsonCreateNew (Join-Path $EvidenceRoot 'restoration-identity.json') $restoration

    Write-JsonAtomic (Join-Path $EvidenceRoot 'recovery-status.json') ([ordered]@{
        taskId=$taskId; recoveryId=$recoveryId; status='INITIALIZING_EXCEL_RTD'; observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; thinkorswimProcessId=$tos.Id
    })
    $excelSession = New-ExcelSession $formulaManifest
    Write-JsonAtomic (Join-Path $EvidenceRoot 'recovery-status.json') ([ordered]@{
        taskId=$taskId; recoveryId=$recoveryId; status='WAITING_FOR_RECOVERY_CHECKPOINTS'; observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; thinkorswimProcessId=$tos.Id; excelProcessId=$excelSession.processId
    })

    $receipts = @()
    foreach ($checkpoint in $checkpoints) {
        $scheduled = [DateTimeOffset]::Parse($checkpoint.scheduledAtCentral)
        $start = $scheduled.AddSeconds(-60)
        while ([DateTimeOffset]::Now -lt $start) {
            Start-Sleep -Seconds ([Math]::Min(30, [Math]::Max(1, [int]($start - [DateTimeOffset]::Now).TotalSeconds)))
        }
        Write-JsonAtomic (Join-Path $EvidenceRoot 'recovery-status.json') ([ordered]@{
            taskId=$taskId; recoveryId=$recoveryId; status='CHECKPOINT_RUNNING'; checkpointId=$checkpoint.checkpointId; scheduledAtCentral=$checkpoint.scheduledAtCentral; observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; excelProcessId=$excelSession.processId
        })
        $checkpointRoot = Join-Path $EvidenceRoot ("checkpoints\" + $checkpoint.checkpointId)
        $receipts += Observe-Checkpoint $excelSession $formulaManifest $checkpoint $checkpointRoot
    }

    $productionEnd = Get-ProductionSnapshot
    $canonicalEnd = Assert-CanonicalFrozen
    $nonmutation = [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        recoveryId = $recoveryId
        observedAt = [DateTimeOffset]::Now.ToString('o')
        canonicalUnchanged = (($canonicalStart | ConvertTo-Json -Compress -Depth 5) -eq ($canonicalEnd | ConvertTo-Json -Compress -Depth 5))
        manifestUnchanged = ($productionStart.manifestSha256 -eq $productionEnd.manifestSha256)
        serviceDefinitionsUnchanged = (($productionStart.services | ConvertTo-Json -Compress -Depth 6) -eq ($productionEnd.services | ConvertTo-Json -Compress -Depth 6))
        productionStart = $productionStart
        productionEnd = $productionEnd
    }
    Write-JsonCreateNew (Join-Path $EvidenceRoot 'monday-nonmutation-proof.json') $nonmutation
    Write-JsonAtomic (Join-Path $EvidenceRoot 'recovery-status.json') ([ordered]@{
        taskId=$taskId; recoveryId=$recoveryId; status='RECOVERY_OBSERVATION_COMPLETE_PENDING_ADJUDICATION'; observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; checkpointReceipts=$receipts
    })
}
catch {
    $failure = [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        recoveryId = $recoveryId
        status = 'RECOVERY_FAILED'
        observedAt = [DateTimeOffset]::Now.ToString('o')
        errorType = $_.Exception.GetType().Name
        error = $_.Exception.Message
    }
    try { Write-JsonCreateNew (Join-Path $EvidenceRoot 'recovery-failure-receipt.json') $failure } catch {}
    try { Write-JsonAtomic (Join-Path $EvidenceRoot 'recovery-status.json') $failure } catch {}
    throw
}
finally {
    if ($null -ne $excelSession) {
        Close-ExcelSession $excelSession
    }
}
