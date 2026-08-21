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

    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$taskId = 'ARGUS-THINKORSWIM-OVERNIGHT-RTD-001'
$allowedFields = @(
    'SYMBOL', 'DESCRIPTION', 'LAST', 'BID', 'ASK', 'MARK', 'LAST_SIZE',
    'BID_SIZE', 'ASK_SIZE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME',
    'EXCHANGE'
)
$allowedSymbols = @('SPY', 'QQQ', 'NVDA', 'AAPL', 'MU')
$expectedCheckpoints = @(
    'A_1955_ET|2026-08-21T19:55:00-04:00',
    'B_2000_ET|2026-08-21T20:00:00-04:00',
    'C_2005_ET|2026-08-21T20:05:00-04:00',
    'D_2100_ET|2026-08-21T21:00:00-04:00',
    'E_0030_ET|2026-08-22T00:30:00-04:00',
    'F_0130_ET|2026-08-22T01:30:00-04:00',
    'G_0355_ET|2026-08-22T03:55:00-04:00',
    'H_0405_ET|2026-08-22T04:05:00-04:00'
)
$forbiddenFieldFragments = @('POSITION', 'P_L', 'ACCOUNT', 'BUYING_POWER', 'ORDER')

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Get-TextSha256([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '')
    }
    finally {
        $sha.Dispose()
    }
}

function ConvertTo-OffsetTimestamp([DateTime]$Value) {
    $offset = [DateTimeOffset]$Value
    return $offset.ToString('o')
}

function Write-JsonCreateNew([string]$Path, [object]$Value, [int]$Depth = 12) {
    $parent = Split-Path -Parent $Path
    if ($parent) {
        [IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $payload = ($Value | ConvertTo-Json -Depth $Depth) + "`n"
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $writer = New-Object IO.StreamWriter($stream, (New-Object Text.UTF8Encoding($false)))
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

function Write-JsonAtomic([string]$Path, [object]$Value, [int]$Depth = 12) {
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = "$Path.$PID.tmp"
    $payload = ($Value | ConvertTo-Json -Depth $Depth) + "`n"
    [IO.File]::WriteAllText($temporary, $payload, (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Get-Git([string]$Root, [string[]]$Arguments) {
    $output = & git -C $Root @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git -C $Root $($Arguments -join ' ')"
    }
    return (($output | Out-String).Trim())
}

function Get-ServiceExecutable([string]$PathName) {
    if ($PathName -match '^"([^"]+)"') {
        return $Matches[1]
    }
    if ($PathName -match '^(\S+)') {
        return $Matches[1]
    }
    throw 'Unable to parse service executable path.'
}

function Get-InstalledProductHead([string]$PathName) {
    if ($PathName -match 'continuous-python-([0-9a-f]{40})') {
        return $Matches[1]
    }
    throw 'Installed continuous product identity was not present in the service path.'
}

function Get-CurrentEnvironment {
    $tosPath = 'C:\Program Files\thinkorswim\thinkorswim.exe'
    $excelPath = 'C:\Program Files\Microsoft Office\Root\Office16\EXCEL.EXE'
    if (-not (Test-Path -LiteralPath $tosPath)) { throw 'thinkorswim executable is unavailable.' }
    if (-not (Test-Path -LiteralPath $excelPath)) { throw 'Desktop Excel executable is unavailable.' }
    $tos = @(Get-Process -Name thinkorswim -ErrorAction SilentlyContinue)
    if ($tos.Count -ne 1) { throw "Exactly one thinkorswim process is required; found $($tos.Count)." }
    $excel = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue)
    if ($excel.Count -ne 0) { throw 'An existing Excel process would violate the one-workbook experiment boundary.' }
    $rtd = Get-ItemProperty 'Registry::HKEY_CLASSES_ROOT\tos.rtd\CLSID' -ErrorAction Stop
    $rtdClsid = $rtd.'(default)'
    $rtdServer = (Get-ItemProperty "Registry::HKEY_CLASSES_ROOT\CLSID\$rtdClsid\InprocServer32" -ErrorAction Stop).'(default)'
    if (-not (Test-Path -LiteralPath $rtdServer)) { throw 'Registered tos.rtd COM server is unavailable.' }
    $tosInstall = Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\9968-4488-2169-7623' -ErrorAction Stop
    return [ordered]@{
        observedAt = [DateTimeOffset]::Now.ToString('o')
        thinkorswim = [ordered]@{
            processId = $tos[0].Id
            processStart = ConvertTo-OffsetTimestamp $tos[0].StartTime
            windowTitle = $tos[0].MainWindowTitle
            executablePath = $tosPath
            executableSha256 = Get-Sha256 $tosPath
            fileVersion = (Get-Item -LiteralPath $tosPath).VersionInfo.FileVersion
            installedDisplayVersion = $tosInstall.DisplayVersion
            installScope = 'ALL_USERS_PROGRAM_FILES'
            sessionId = $tos[0].SessionId
        }
        excel = [ordered]@{
            executablePath = $excelPath
            executableSha256 = Get-Sha256 $excelPath
            fileVersion = (Get-Item -LiteralPath $excelPath).VersionInfo.FileVersion
            installScope = 'ALL_USERS_PROGRAM_FILES'
        }
        rtd = [ordered]@{
            progId = 'tos.rtd'
            clsid = $rtdClsid
            serverPath = $rtdServer
            serverSha256 = Get-Sha256 $rtdServer
            serverFileVersion = (Get-Item -LiteralPath $rtdServer).VersionInfo.FileVersion
            officiallySupportedClient = 'MICROSOFT_EXCEL_DESKTOP'
        }
        interactiveSession = [ordered]@{
            sessionId = $tos[0].SessionId
            requiredByObservedTopology = $true
        }
    }
}

function Assert-Configuration([object]$Configuration) {
    if ($Configuration.taskId -ne $taskId) { throw 'Configuration task identity mismatch.' }
    if (@($Configuration.symbols).Count -ne 5) { throw 'The fixed five-symbol basket is required.' }
    if ((@($Configuration.symbols) -join ',') -ne ($allowedSymbols -join ',')) {
        throw 'The fixed symbol basket changed.'
    }
    if ((@($Configuration.fields) -join ',') -ne ($allowedFields -join ',')) {
        throw 'The fixed market-only field set changed.'
    }
    foreach ($field in @($Configuration.fields)) {
        if ($allowedFields -notcontains $field) { throw "Unsupported RTD field: $field" }
        foreach ($fragment in $forbiddenFieldFragments) {
            if ($field -like "*$fragment*") { throw "Forbidden RTD field: $field" }
        }
    }
    if ($Configuration.sampleIntervalSeconds -lt 1) { throw 'Sample cadence is too aggressive.' }
    if ($Configuration.phaseADurationSeconds -lt 1200) { throw 'Phase A must run for at least 20 minutes.' }
    if ([int]$Configuration.checkpointDurationSeconds -ne 120) { throw 'Checkpoint duration must remain 120 seconds.' }
    if ([int]$Configuration.checkpointLeadSeconds -ne 60) { throw 'Checkpoint lead must remain 60 seconds.' }
    if (@($Configuration.checkpoints).Count -ne 8) { throw 'All eight overnight checkpoints are required.' }
    $ids = @($Configuration.checkpoints | ForEach-Object { $_.checkpointId })
    if (@($ids | Select-Object -Unique).Count -ne 8) { throw 'Checkpoint IDs must be unique.' }
    $actualCheckpoints = @($Configuration.checkpoints | ForEach-Object { "$($_.checkpointId)|$($_.scheduledAtEastern)" })
    if (($actualCheckpoints -join ',') -ne ($expectedCheckpoints -join ',')) {
        throw 'The fixed overnight checkpoint schedule changed.'
    }
}

function New-FormulaManifest([object]$Configuration) {
    $cells = @()
    $row = 2
    foreach ($symbol in @($Configuration.symbols)) {
        $column = 2
        foreach ($field in @($Configuration.fields)) {
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
        providerTimestampAvailable = $false
        timestampAuthority = 'LOCAL_OBSERVATION_TIMESTAMP_ONLY'
        cells = $cells
    }
}

function New-ExcelSession([object]$FormulaManifest) {
    $before = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.AskToUpdateLinks = $false
    $excel.Calculation = -4105
    $workbook = $excel.Workbooks.Add()
    $sheet = $workbook.Worksheets.Item(1)
    $sheet.Name = 'MARKET_RTD_ONLY'
    foreach ($cell in @($FormulaManifest.cells)) {
        $sheet.Cells.Item($cell.row, $cell.column).Formula = $cell.formula
    }
    Start-Sleep -Seconds 15
    $after = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue)
    $newProcess = @($after | Where-Object { $before -notcontains $_.Id })
    if ($newProcess.Count -ne 1) { throw "Expected one experiment Excel process; found $($newProcess.Count)." }
    return [ordered]@{
        application = $excel
        workbook = $workbook
        sheet = $sheet
        processId = $newProcess[0].Id
        processStart = ConvertTo-OffsetTimestamp $newProcess[0].StartTime
    }
}

function Close-ExcelSession([object]$Session) {
    if ($null -eq $Session) { return }
    try { $Session.workbook.Close($false) } catch {}
    try { $Session.application.Quit() } catch {}
    foreach ($name in @('sheet', 'workbook', 'application')) {
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($Session[$name]) } catch {}
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

function Convert-CellValue([object]$Value) {
    if ($null -eq $Value) { return [ordered]@{state='EMPTY'; value=$null} }
    $text = [Convert]::ToString($Value, [Globalization.CultureInfo]::InvariantCulture)
    if ([string]::IsNullOrWhiteSpace($text)) { return [ordered]@{state='EMPTY'; value=$null} }
    if ($text.StartsWith('#')) { return [ordered]@{state='ERROR'; value=$text} }
    return [ordered]@{state='PRESENT'; value=$text}
}

function Observe-Checkpoint(
    [object]$Session,
    [object]$FormulaManifest,
    [string]$CheckpointId,
    [DateTimeOffset]$ScheduledAt,
    [int]$DurationSeconds,
    [int]$SampleIntervalSeconds,
    [string]$CheckpointRoot
) {
    [IO.Directory]::CreateDirectory($CheckpointRoot) | Out-Null
    $observationPath = Join-Path $CheckpointRoot 'observations.ndjson'
    $stream = [IO.File]::Open($observationPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $writer = New-Object IO.StreamWriter($stream, (New-Object Text.UTF8Encoding($false)))
    $started = [DateTimeOffset]::Now
    $deadline = $started.AddSeconds($DurationSeconds)
    $sampleCount = 0
    try {
        while ([DateTimeOffset]::Now -lt $deadline) {
            $values = @()
            foreach ($cell in @($FormulaManifest.cells)) {
                $normalized = Convert-CellValue $Session.sheet.Cells.Item($cell.row, $cell.column).Value2
                $values += [ordered]@{
                    symbol = $cell.symbol
                    field = $cell.field
                    state = $normalized.state
                    value = $normalized.value
                }
            }
            $record = [ordered]@{
                schemaVersion = 1
                taskId = $taskId
                checkpointId = $CheckpointId
                scheduledAtEastern = $ScheduledAt.ToString('o')
                observedAt = [DateTimeOffset]::Now.ToString('o')
                timestampAuthority = 'LOCAL_OBSERVATION_TIMESTAMP_ONLY'
                sampleNumber = $sampleCount + 1
                values = $values
            }
            $writer.WriteLine(($record | ConvertTo-Json -Compress -Depth 8))
            $writer.Flush()
            $sampleCount++
            Start-Sleep -Seconds $SampleIntervalSeconds
        }
        $stream.Flush($true)
    }
    finally {
        $writer.Dispose()
        $stream.Dispose()
    }
    $tos = @(Get-Process -Name thinkorswim -ErrorAction SilentlyContinue)
    $excel = Get-Process -Id $Session.processId -ErrorAction SilentlyContinue
    $receipt = [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        checkpointId = $CheckpointId
        scheduledAtEastern = $ScheduledAt.ToString('o')
        startedAt = $started.ToString('o')
        completedAt = [DateTimeOffset]::Now.ToString('o')
        sampleCount = $sampleCount
        observationSha256 = Get-Sha256 $observationPath
        thinkorswim = if ($tos.Count -eq 1) {[ordered]@{running=$true; processId=$tos[0].Id; windowTitle=$tos[0].MainWindowTitle}} else {[ordered]@{running=$false; processCount=$tos.Count}}
        excel = if ($null -ne $excel) {[ordered]@{running=$true; processId=$excel.Id; cpuSeconds=$excel.CPU; workingSetBytes=$excel.WorkingSet64}} else {[ordered]@{running=$false}}
    }
    Write-JsonCreateNew (Join-Path $CheckpointRoot 'checkpoint-receipt.json') $receipt
    return $receipt
}

function New-ProvenanceBaseline(
    [object]$Configuration,
    [object]$Environment,
    [object]$FormulaManifest,
    [string]$Root
) {
    $canonicalHead = Get-Git $CanonicalRoot @('rev-parse', 'HEAD')
    $originHead = Get-Git $CanonicalRoot @('rev-parse', 'origin/master')
    if ($canonicalHead -ne $originHead) { throw 'Canonical master and origin/master differ.' }
    $sourceHead = Get-Git $ProjectRoot @('rev-parse', 'HEAD')
    if ($sourceHead -ne $ExpectedSourceHead) { throw 'Experiment source HEAD mismatch.' }
    if (Get-Git $ProjectRoot @('status', '--porcelain')) { throw 'Experiment worktree is dirty.' }
    if (Get-Git $CanonicalRoot @('status', '--porcelain')) { throw 'Canonical worktree is dirty.' }
    if ([IO.Path]::GetFullPath($ProjectRoot) -eq [IO.Path]::GetFullPath($CanonicalRoot)) {
        throw 'Experiment and canonical roots must be physically distinct.'
    }

    $automationManifest = 'C:\ProgramData\MomentumHunter\Automation\automation-manifest.json'
    $continuousConfig = 'C:\ProgramData\MomentumHunter\Automation\continuous-deployment.json'
    $continuousManifest = 'C:\ProgramData\MomentumHunter\Automation\continuous-deployment-manifest.json'
    $services = @(Get-CimInstance Win32_Service | Where-Object { $_.Name -in @('MomentumHunterAutomation','MomentumHunterContinuousRuntime','MomentumHunterContinuousWriter') } | Sort-Object Name)
    if ($services.Count -ne 3) { throw 'Production service inventory is incomplete.' }
    foreach ($service in $services) {
        if ($service.State -ne 'Running' -or $service.StartMode -ne 'Auto') { throw "Service $($service.Name) is not Running/Automatic." }
    }
    $runtimeService = $services | Where-Object Name -eq 'MomentumHunterContinuousRuntime'
    $installedHead = Get-InstalledProductHead $runtimeService.PathName
    $serviceRows = @()
    foreach ($service in $services) {
        $exe = Get-ServiceExecutable $service.PathName
        $config = if ($service.Name -eq 'MomentumHunterAutomation') {$automationManifest} else {$continuousConfig}
        $deployment = if ($service.Name -eq 'MomentumHunterAutomation') {$automationManifest} else {$continuousManifest}
        $serviceRows += [ordered]@{
            name = $service.Name
            state = $service.State
            startMode = $service.StartMode
            startName = $service.StartName
            executableSha256 = Get-Sha256 $exe
            configSha256 = Get-Sha256 $config
            deploymentManifestSha256 = Get-Sha256 $deployment
        }
    }

    $sourcePaths = @(
        (Join-Path $ProjectRoot 'tools\run_thinkorswim_rtd_campaign.ps1'),
        (Join-Path $ProjectRoot 'tools\start_thinkorswim_rtd_campaign.ps1'),
        (Join-Path $ProjectRoot 'tools\verify_thinkorswim_rtd_campaign.py'),
        (Join-Path $ProjectRoot 'tools\verify_campaign_provenance.py'),
        $ConfigurationPath,
        (Join-Path $ProjectRoot 'config\thinkorswim-rtd-001-official-capabilities.json')
    )
    $sourceManifest = @($sourcePaths | ForEach-Object {
        $resolved = [IO.Path]::GetFullPath($_)
        $relative = if ($resolved.StartsWith([IO.Path]::GetFullPath($ProjectRoot), [StringComparison]::OrdinalIgnoreCase)) {
            $resolved.Substring([IO.Path]::GetFullPath($ProjectRoot).Length).TrimStart('\')
        } else {
            $resolved
        }
        [ordered]@{path=$relative; sha256=Get-Sha256 $resolved}
    })
    $sourceManifestPayload = $sourceManifest | ConvertTo-Json -Compress -Depth 5
    $process = Get-Process -Id $PID
    $processExecutable = $process.Path
    $draft = [ordered]@{
        schemaVersion = 1
        campaignFrozenIdentity = [ordered]@{
            taskId = $taskId
            sourceGitHead = $sourceHead
            sourceFileManifestSha256 = Get-TextSha256 $sourceManifestPayload
            configurationFingerprint = Get-Sha256 $ConfigurationPath
            executableSha256 = Get-Sha256 (Join-Path $ProjectRoot 'tools\run_thinkorswim_rtd_campaign.ps1')
            evidenceRootFingerprint = Get-TextSha256 ([IO.Path]::GetFullPath($Root).ToUpperInvariant())
            providerRouteAllowlistSha256 = Get-TextSha256 'Excel.Application|tos.rtd|MARKET_FIELDS_ONLY'
            startedAt = ConvertTo-OffsetTimestamp $process.StartTime
            processIdentity = [ordered]@{
                processId = $PID
                executableSha256 = Get-Sha256 $processExecutable
                startedAt = ConvertTo-OffsetTimestamp $process.StartTime
            }
        }
        productionBaseline = [ordered]@{
            canonicalRoot = [IO.Path]::GetFullPath($CanonicalRoot)
            experimentRoot = [IO.Path]::GetFullPath($ProjectRoot)
            rootsDistinct = ([IO.Path]::GetFullPath($CanonicalRoot) -ne [IO.Path]::GetFullPath($ProjectRoot))
            canonicalGitHead = $canonicalHead
            installedProductGitHead = $installedHead
            manifestSha256 = Get-Sha256 $automationManifest
            observedAt = [DateTimeOffset]::Now.ToString('o')
            services = $serviceRows
        }
        sharedResources = @(
            [ordered]@{
                resourceId = 'CANONICAL_GIT_OBJECT_STORE'
                resourceType = 'GIT_REPOSITORY'
                mutable = $true
                owner = 'GIT_STEWARD'
                allowedWriters = @('AUTHORIZED_CANONICAL_GIT_WORK')
                campaignAccess = 'READ_ONLY'
                mutationRules = 'Campaign worktree source must remain frozen; canonical changes require the authorized external change ledger.'
                baselineFingerprint = Get-TextSha256 "$canonicalHead|$originHead"
            },
            [ordered]@{
                resourceId = 'CANONICAL_PYTHON_ENVIRONMENT'
                resourceType = 'PYTHON_INTERPRETER'
                mutable = $true
                owner = 'PRODUCTION_DEPLOYMENT'
                allowedWriters = @('AUTHORIZED_DEPENDENCY_MAINTENANCE')
                campaignAccess = 'READ_ONLY'
                mutationRules = 'Interpreter hash must remain fixed for campaign provenance finalization.'
                baselineFingerprint = Get-Sha256 (Join-Path $CanonicalRoot '.venv\Scripts\python.exe')
            }
        )
        authorizedExternalChanges = @()
        campaignIntegrityObservations = [ordered]@{
            campaignSourceUnchanged = $true
            campaignExecutableUnchanged = $true
            campaignConfigurationUnchanged = $true
            campaignEvidenceValid = $true
            campaignProcessIdentityValid = $true
            externalProductionTouchedCampaignPaths = $false
            undeclaredSharedMutableResource = $false
        }
    }
    Write-JsonCreateNew (Join-Path $Root 'campaign-provenance-draft.json') $draft 16
    $python = Join-Path $CanonicalRoot '.venv\Scripts\python.exe'
    & $python -B (Join-Path $ProjectRoot 'tools\verify_campaign_provenance.py') finalize (Join-Path $Root 'campaign-provenance-draft.json') (Join-Path $Root 'campaign-provenance-start.json')
    if ($LASTEXITCODE -ne 0) { throw 'Campaign provenance finalization failed.' }
    Write-JsonCreateNew (Join-Path $Root 'source-file-manifest.json') ([ordered]@{schemaVersion=1; taskId=$taskId; sourceGitHead=$sourceHead; files=$sourceManifest; manifestSha256=(Get-TextSha256 $sourceManifestPayload)}) 8
    Write-JsonCreateNew (Join-Path $Root 'environment-baseline.json') $Environment 10
    Write-JsonCreateNew (Join-Path $Root 'rtd-formula-manifest.json') $FormulaManifest 10
    Write-JsonCreateNew (Join-Path $Root 'authorized-external-change-ledger-start.json') ([ordered]@{
        schemaVersion = 1
        taskId = $taskId
        status = 'EMPTY_AT_CAMPAIGN_START'
        changes = @()
        rule = 'Any later authorized production change requires a chained provenance record and bounded isolation revalidation before final adjudication.'
    }) 6
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'config\thinkorswim-rtd-001-official-capabilities.json') -Destination (Join-Path $Root 'official-capability-inventory.json')
    Copy-Item -LiteralPath $ConfigurationPath -Destination (Join-Path $Root 'campaign-configuration.json')
}

$configuration = Get-Content -Raw -LiteralPath $ConfigurationPath | ConvertFrom-Json
Assert-Configuration $configuration
$formulaManifest = New-FormulaManifest $configuration

if ($ValidateOnly) {
    [ordered]@{
        status = 'VALIDATED_ONLY'
        taskId = $taskId
        symbols = @($configuration.symbols).Count
        fields = @($configuration.fields).Count
        cells = @($formulaManifest.cells).Count
        accountFields = 0
        orderFields = 0
        excelContacted = $false
        thinkorswimContacted = $false
    } | ConvertTo-Json -Depth 5
    exit 0
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'READY_FOR_UAC: all-users thinkorswim installation requires elevated Excel for the documented RTD path.'
}

if (Test-Path -LiteralPath $EvidenceRoot) { throw 'Evidence root already exists; refusing to overwrite or resume ambiguously.' }
[IO.Directory]::CreateDirectory($EvidenceRoot) | Out-Null
$excelSession = $null
try {
    $environment = Get-CurrentEnvironment
    New-ProvenanceBaseline $configuration $environment $formulaManifest $EvidenceRoot
    Write-JsonAtomic (Join-Path $EvidenceRoot 'campaign-status.json') ([ordered]@{taskId=$taskId; status='BASELINE_FROZEN'; observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID})

    $excelSession = New-ExcelSession $formulaManifest
    Write-JsonAtomic (Join-Path $EvidenceRoot 'campaign-status.json') ([ordered]@{taskId=$taskId; status='PHASE_A_RUNNING'; observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; excelProcessId=$excelSession.processId})
    $phaseRoot = Join-Path $EvidenceRoot 'phase-a-post-0400-et'
    Observe-Checkpoint $excelSession $formulaManifest 'PHASE_A_POST_0400_ET' ([DateTimeOffset]::Now) ([int]$configuration.phaseADurationSeconds) ([int]$configuration.sampleIntervalSeconds) $phaseRoot | Out-Null
    Close-ExcelSession $excelSession
    $excelSession = $null

    Write-JsonAtomic (Join-Path $EvidenceRoot 'campaign-status.json') ([ordered]@{taskId=$taskId; status='WAITING_FOR_TRUE_OVERNIGHT'; observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; nextCheckpoint=$configuration.checkpoints[0].scheduledAtEastern})
    $first = [DateTimeOffset]::Parse($configuration.checkpoints[0].scheduledAtEastern).AddSeconds(-[int]$configuration.checkpointLeadSeconds)
    while ([DateTimeOffset]::Now -lt $first) {
        Start-Sleep -Seconds ([Math]::Min(60, [Math]::Max(1, [int]($first - [DateTimeOffset]::Now).TotalSeconds)))
    }
    $excelSession = New-ExcelSession $formulaManifest
    foreach ($checkpoint in @($configuration.checkpoints)) {
        $scheduled = [DateTimeOffset]::Parse($checkpoint.scheduledAtEastern)
        $start = $scheduled.AddSeconds(-[int]$configuration.checkpointLeadSeconds)
        while ([DateTimeOffset]::Now -lt $start) {
            Start-Sleep -Seconds ([Math]::Min(30, [Math]::Max(1, [int]($start - [DateTimeOffset]::Now).TotalSeconds)))
        }
        $checkpointRoot = Join-Path $EvidenceRoot ("checkpoints\" + $checkpoint.checkpointId)
        Write-JsonAtomic (Join-Path $EvidenceRoot 'campaign-status.json') ([ordered]@{taskId=$taskId; status='CHECKPOINT_RUNNING'; checkpointId=$checkpoint.checkpointId; scheduledAtEastern=$scheduled.ToString('o'); observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; excelProcessId=$excelSession.processId})
        Observe-Checkpoint $excelSession $formulaManifest $checkpoint.checkpointId $scheduled ([int]$configuration.checkpointDurationSeconds) ([int]$configuration.sampleIntervalSeconds) $checkpointRoot | Out-Null
    }
    Write-JsonAtomic (Join-Path $EvidenceRoot 'campaign-status.json') ([ordered]@{taskId=$taskId; status='OBSERVATION_COMPLETE_PENDING_ADJUDICATION'; observedAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID})
}
catch {
    $failure = [ordered]@{
        schemaVersion = 1
        taskId = $taskId
        status = 'FAILED'
        observedAt = [DateTimeOffset]::Now.ToString('o')
        errorType = $_.Exception.GetType().Name
        error = $_.Exception.Message
        accountFields = 0
        orderFields = 0
    }
    if (Test-Path -LiteralPath $EvidenceRoot) {
        if (-not (Test-Path -LiteralPath (Join-Path $EvidenceRoot 'failure-receipt.json'))) {
            Write-JsonCreateNew (Join-Path $EvidenceRoot 'failure-receipt.json') $failure
        }
        Write-JsonAtomic (Join-Path $EvidenceRoot 'campaign-status.json') $failure
    }
    throw
}
finally {
    Close-ExcelSession $excelSession
}
