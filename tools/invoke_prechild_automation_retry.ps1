param(
    [Parameter(Mandatory=$true)][string]$Plan,
    [Parameter(Mandatory=$true)][string]$PlanSha256,
    [switch]$ExecuteReviewed
)
# PowerShell 7/.NET 8+; Engine qualification never invokes ExecuteReviewed.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSEdition -ne 'Core' -or [Environment]::Version.Major -lt 8) { throw 'REVIEWED_POWERSHELL_CORE_REQUIRED' }
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
if ((Hash $Plan) -cne $PlanSha256.ToLowerInvariant()) { throw 'RETRY_PLAN_HASH_MISMATCH' }
$p = Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json -AsHashtable
if ($p.schemaVersion -ne 1 -or $p.task -ne 'ARGUS-AUTOMATION-PRECHILD-CONTAINMENT-LAUNCHER-REPAIR-001') { throw 'RETRY_PLAN_SCHEMA' }
$evidence = [IO.Path]::GetFullPath($p.evidenceRoot)
if ($evidence.StartsWith([IO.Path]::GetFullPath($p.canonicalRoot),[StringComparison]::OrdinalIgnoreCase) -or
    $evidence.StartsWith([Environment]::GetFolderPath('CommonApplicationData'),[StringComparison]::OrdinalIgnoreCase)) { throw 'EXTERNAL_EVIDENCE_ROOT_REQUIRED' }
if (@($p.phases).Count -ne 2 -or $p.startupSeconds -ne 120 -or $p.stabilitySeconds -ne 180 -or
    $p.cleanupSeconds -lt 30 -or $p.cleanupSeconds -gt 90 -or $p.maximumSeconds -gt 1800 -or $p.maximumSeconds -lt 600) { throw 'RETRY_BUDGET_CONTRACT' }
$watch = [Diagnostics.Stopwatch]::StartNew()
$cutoff = [DateTimeOffset]::Parse($p.cutoffAt)
$scheduled = [DateTimeOffset]::Parse($p.targetScheduledAt)
if ($cutoff -ge $scheduled) { throw 'CUTOFF_MUST_PRECEDE_OPENING' }
$sequence = 0
$session = $null
$started = $false
$committed = $false
$phaseIndex = -1
$ownership = $null
function Assert-Time([int]$Remaining) {
    if ($Remaining -lt 0 -or $watch.Elapsed.TotalSeconds + $Remaining + $p.cleanupSeconds -ge $p.maximumSeconds -or
        [DateTimeOffset]::Now.AddSeconds($Remaining + $p.cleanupSeconds) -ge $cutoff) { throw 'RETRY_BUDGET_EXHAUSTED' }
}
function Save-New([string]$Name,$Value) {
    if ($Name -notmatch '^[a-zA-Z0-9._-]+$') { throw 'RECEIPT_NAME_INVALID' }
    $path = Join-Path $evidence $Name
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 40))
    $f = [IO.FileStream]::new($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read,4096,[IO.FileOptions]::WriteThrough)
    try { $f.Write($bytes); $f.Flush($true) } finally { $f.Dispose() }
    return $path
}
function Assert-Closure {
    foreach ($file in $p.nativeClosure.GetEnumerator()) { if ((Hash $file.Key) -cne $file.Value) { throw "NATIVE_CLOSURE_DRIFT:$($file.Key)" } }
    foreach ($file in $p.controllerNativeClosure.GetEnumerator()) { if ((Hash $file.Key) -cne $file.Value) { throw "CONTROLLER_CLOSURE_DRIFT:$($file.Key)" } }
    foreach ($file in $p.toolClosure.GetEnumerator()) { if ((Hash $file.Key) -cne $file.Value) { throw "TOOL_CLOSURE_DRIFT:$($file.Key)" } }
    foreach ($phase in $p.phases) { if ((Hash $phase.readonlyConfig) -cne $phase.readonlyConfigSha256) { throw 'PHASE_CONFIG_DRIFT' } }
    if ((Hash $PSCommandPath) -cne $p.toolClosure[$PSCommandPath]) { throw 'CONTROLLER_SCRIPT_UNBOUND' }
    if (-not $p.controllerNativeClosure.ContainsKey($p.nativeAssembly) -or -not $p.toolClosure.ContainsKey($p.readonlyAdapter)) { throw 'EXECUTABLE_CONTRACT_INCOMPLETE' }
}
Assert-Time 600
Assert-Closure
[Reflection.Assembly]::LoadFrom($p.nativeAssembly) | Out-Null
function Native([string[]]$Arguments,[double]$Seconds,[string]$Executable=$p.observerPython) {
    Assert-Time $Seconds
    $script:sequence++
    $info = [Diagnostics.ProcessStartInfo]::new($Executable)
    $info.WorkingDirectory=$evidence; $info.UseShellExecute=$false
    foreach ($arg in $Arguments) { $info.ArgumentList.Add($arg) }
    $info.Environment['PYTHONDONTWRITEBYTECODE']='1'
    $info.Environment['GIT_OPTIONAL_LOCKS']='0'
    $info.Environment['GIT_TERMINAL_PROMPT']='0'
    $target = [MomentumHunter.AutomationService.WindowsContainedProcess]::CreateSuspended($info,$null,$null)
    $bound = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($Seconds))
    $stdout = $target.StandardOutput.ReadToEndAsync()
    $stderr = $target.StandardError.ReadToEndAsync()
    try {
        $target.Resume($null)
        $target.WaitForExitAsync($bound.Token).GetAwaiter().GetResult()
        if ($target.ExitCode -ne 0) { throw "READONLY_CHILD_EXIT:$($target.ExitCode)" }
    } finally {
        $target.Abort()
        $remaining = @($target.MemberPids()).Count
        try {
            if (-not $stdout.Wait(10000) -or -not $stderr.Wait(10000)) { throw 'BOUNDED_TRANSCRIPT_DRAIN_FAILED' }
            $script:LastNativeStdout=$stdout.Result
            Save-New ('native-{0:D4}.json' -f $script:sequence) @{identity=$target.Identity;remaining=$remaining;stdout=$stdout.Result;stderr=$stderr.Result} | Out-Null
        } finally {$target.Dispose(); $bound.Dispose()}
        if ($remaining -ne 0) { throw 'READONLY_CHILD_QUIESCENCE_FAILED' }
    }
}
function Observe([string]$Action,[int]$Phase,[string]$OwnershipPath='',[double]$Seconds=25) {
    $config=$p.phases[$Phase]
    $name=('observation-{0:D4}-{1}.json' -f ($script:sequence+1),$Action)
    $output=Join-Path $evidence $name
    $arguments=@('-B',$p.readonlyAdapter,$Action,'--config',$config.readonlyConfig,'--config-sha256',$config.readonlyConfigSha256,'--output',$output)
    if ($OwnershipPath) { $arguments += @('--ownership',$OwnershipPath,'--ownership-sha256',(Hash $OwnershipPath)) }
    Native $arguments $Seconds
    $result=Get-Content -LiteralPath $output -Raw | ConvertFrom-Json -AsHashtable
    if ($result.status -ne 'PASS') { throw "READONLY_OBSERVATION_REJECTED:$name" }
    return $result
}
function Service {
    Get-CimInstance Win32_Service -OperationTimeoutSec 5 -Filter "Name='MomentumHunterAutomation'"
}
function Assert-ServiceDefinition([string]$Expected) {
    $s=Service
    if ($s.PathName -cne $Expected -or $s.StartName -cne $p.serviceUser -or $s.StartMode -ne 'Auto') { throw 'SCM_DEFINITION_DRIFT' }
    return $s
}
function Change-Selector([string]$Before,[string]$After) {
    $s=Assert-ServiceDefinition $Before
    if ($s.State -ne 'Stopped' -or $s.ProcessId -ne 0) { throw 'SELECTOR_TRANSITION_REQUIRES_STOPPED' }
    # Exact pre-reviewed binary-path transition only; no credential/start-mode/failure-action edits.
    $r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=$After} -OperationTimeoutSec 5
    if ($r.ReturnValue -ne 0) { throw 'SCM_SELECTOR_CHANGE_REJECTED' }
    Assert-ServiceDefinition $After | Out-Null
}
function Check-Topology([double]$Seconds=15) {
    $bound=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($Seconds))
    try { $session.CheckAsync($rules,$bound.Token).GetAwaiter().GetResult() } finally {$bound.Dispose()}
}
function Quiesce {
    if ($null -ne $session -and $session.ReconcileCommit()) {throw 'POSTCOMMIT_SCM_MUTATION_NOT_AUTHORIZED'}
    try {
        $s=Service
        if ($s.State -ne 'Stopped' -and $null -ne $ownership -and $s.ProcessId -gt 0) {
            $actual=[MomentumHunter.AutomationService.ProcessTopologyIdentity]::Capture([int]$s.ProcessId,[long]$ownership.launcherCreatedFileTime)
            if ($actual.Pid -ne $ownership.binding.wrapperProcessId) { throw 'SCM_REPLACEMENT_NOT_OWNED' }
            Stop-Service -Name MomentumHunterAutomation -NoWait
        }
    } finally {if ($null -ne $session) {$session.Abort()}}
    (Get-Service MomentumHunterAutomation).WaitForStatus([ServiceProcess.ServiceControllerStatus]::Stopped,[TimeSpan]::FromSeconds(30))
    if ((Service).ProcessId -ne 0 -or ($null -ne $session -and @($session.MemberPids()).Count -ne 0)) { throw 'QUIESCENCE_UNPROVEN' }
}
if (-not $ExecuteReviewed) {
    if (-not (Test-Path -LiteralPath $evidence -PathType Container)) { New-Item -ItemType Directory -Path $evidence | Out-Null }
    $current=Observe 'preflight' 0
    Save-New 'DRESS-INTERCEPT.json' @{status='PASS';productionMutation=$false;productionStart=$false;
        selected=$p.phases[0];currentInput=$current;prechildMechanism='JOB_LIST_SUSPENDED_VERIFY_RESUME';
        note='Proposed selector/adoption must be separately admitted; no SCM mutation performed.'} | Out-Null
    return
}
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'EXPLICIT_ELEVATED_INTEGRATION_REQUIRED' }
if ($p.acceptedCandidateCommit -notmatch '^[0-9a-f]{40}$' -or $p.acceptedCandidateTree -notmatch '^[0-9a-f]{40}$' -or
    $p.acceptedPackageSha256 -notmatch '^[0-9a-f]{64}$' -or $p.astraDisposition -ne 'ACCEPT_PRECHILD_CONTAINMENT_AND_RETRY_CONTROLLER') { throw 'ADMITTED_HANDOFF_REQUIRED' }
if (-not (Test-Path -LiteralPath $evidence -PathType Container)) { New-Item -ItemType Directory -Path $evidence | Out-Null }
Save-New 'production-attempt-intent.json' @{at=[DateTimeOffset]::UtcNow.ToString('o');planSha256=$PlanSha256;attemptsAuthorized=1;restartAuthorized=1} | Out-Null
Import-Module (Join-Path $PSScriptRoot 'automation_retry_workflow.psm1') -Force
try {
Native @('-B',(Join-Path $PSScriptRoot 'validate_prechild_retry_plan.py'),'--plan',$Plan,'--plan-sha256',$PlanSha256,'--package',$p.acceptedPackagePath) 60
if ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -cne $p.serviceSid) {throw 'CONTROLLER_SERVICE_PRINCIPAL_MISMATCH'}
Native @('/query','/status') 15 (Join-Path $env:SystemRoot 'System32\w32tm.exe')
$clockText=$script:LastNativeStdout
if ($clockText -notmatch 'Leap Indicator:\s*0\b' -or $clockText -notmatch 'Stratum:\s*[1-9]\b' -or
    $clockText -notmatch 'Last Successful Sync Time:\s*([^\r\n]+)') {throw 'CLOCK_SYNCHRONIZATION_UNPROVEN'}
$sync=[DateTime]::Parse($Matches[1].Trim(),[Globalization.CultureInfo]::GetCultureInfo('en-US'))
if (([DateTime]::Now-$sync).TotalHours -gt 24 -or $sync -gt [DateTime]::Now.AddMinutes(1)) {throw 'CLOCK_SYNC_STALE_OR_FUTURE'}
} catch {
    Save-New 'production-terminal-result.json' @{status='FAIL';stage='PRE_MUTATION_PREFLIGHT';
        error=$_.Exception.Message;custody='NOT_STARTED';productionMutation=$false;productionStart=$false} | Out-Null
    throw
}
function Owner-File($c) {
    if ($null -ne $c.binding) {$script:ownership.binding=$c.binding}
    $c.ownerPath=Save-New ('ownership-{0}-{1:D4}.json' -f $c.phase,$c.sequence) $script:ownership
    return $c.ownerPath
}
$actions=@{}
$actions.Clock={@{mono=$watch.Elapsed.TotalSeconds;utc=[DateTimeOffset]::UtcNow}}
$actions.Preflight={param($c,$budget)
    if ($c.phase -eq 0) {Observe 'preflight' 0 '' $budget}
    else {Observe 'restart-preflight' 1 $c.ownerPath $budget}
}
$actions.Start={param($c,$budget)
    $phase=$p.phases[$c.phase]
    $prior=if ($c.phase -eq 0) {$p.installedServiceDefinition} else {$p.phases[0].serviceDefinition}
    $info=[Diagnostics.ProcessStartInfo]::new($p.pythonExecutable)
    $info.WorkingDirectory=$p.canonicalRoot; $info.UseShellExecute=$false
    foreach ($arg in $p.pythonArguments) {$info.ArgumentList.Add($arg)}
    $files=[Collections.Generic.Dictionary[string,string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in $p.launchStaticFiles.GetEnumerator()) {$files.Add($file.Key,$file.Value.ToUpperInvariant())}
    $lifetime=[Math]::Min($p.maximumSeconds-$watch.Elapsed.TotalSeconds-$p.cleanupSeconds,
        ($cutoff-[DateTimeOffset]::UtcNow).TotalSeconds-$p.cleanupSeconds)
    $script:session=[MomentumHunter.AutomationService.RetryControllerSession]::new($phase.launchContract,$info,
        $p.serviceSid,0,$files,[TimeSpan]::FromSeconds($lifetime))
    $script:ownership=$null
    $script:rules=[Collections.Generic.List[MomentumHunter.AutomationService.RuntimeTopologyRule]]::new()
    foreach ($r in $p.topologyRules) {$script:rules.Add([MomentumHunter.AutomationService.RuntimeTopologyRule]::new(
        $r.role,$r.executable,$r.sha256.ToUpperInvariant(),$r.commandLine,$r.parentRole,$r.minimum,$r.maximum))}
    $step=[Diagnostics.Stopwatch]::StartNew()
    function Left([double]$cap) {
        $remaining=$budget-$step.Elapsed.TotalSeconds
        if ($remaining -le 0) {throw 'START_STAGE_DEADLINE'}
        [Math]::Min($cap,$remaining)
    }
    Change-Selector $prior $phase.serviceDefinition
    $launchRequestedAt=[DateTime]::UtcNow
    Native @('start','MomentumHunterAutomation') (Left 15) (Join-Path $env:SystemRoot 'System32\sc.exe')
    $s=Assert-ServiceDefinition $phase.serviceDefinition
    if ($s.ProcessId -le 0) {throw 'SCM_LAUNCHER_PID_UNAVAILABLE'}
    $birth=(Get-Process -Id $s.ProcessId).StartTime.ToUniversalTime().ToFileTimeUtc()
    $launcher=[MomentumHunter.AutomationService.ProcessTopologyIdentity]::Capture([int]$s.ProcessId,[long]$birth)
    if ($birth -lt $launchRequestedAt.ToFileTimeUtc() -or $launcher.Executable -ine $p.hostExecutable -or
        $launcher.ExecutableSha256.ToLowerInvariant() -cne $p.nativeClosure[$p.hostExecutable] -or
        $launcher.CommandLine -cne $phase.serviceDefinition -or $launcher.SessionId -ne 0 -or
        $launcher.UserSid -cne $p.serviceSid) {throw 'SCM_LAUNCHER_IDENTITY_REJECTED'}
    $script:ownership=@{launcherCreatedFileTime=$birth;binding=@{wrapperProcessId=$launcher.Pid;
        wrapperCreatedAt=[DateTime]::FromFileTimeUtc($birth).ToString('o');preStartStateSha256=$c.prestart.observation.sha256;
        epochId=$c.prestart.epoch.epochId};previousServiceInstanceId=$c.prestart.observation.state.service_instance_id}
    $bound=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds((Left 25)))
    try {$session.AdmitAsync($launcher,$bound.Token).GetAwaiter().GetResult()} finally {$bound.Dispose()}
    Check-Topology (Left 15)
    $supervisors=@($session.MemberPids() | ForEach-Object {$session.InspectMember($_)} |
        Where-Object {$_.Executable -ieq $p.basePythonExecutable -and $_.ParentPid -eq $session.Target.TargetPid})
    if ($supervisors.Count -ne 1) {throw 'BASE_SUPERVISOR_IDENTITY_UNPROVEN'}
    $script:ownership.supervisorCreatedAt=[DateTime]::FromFileTimeUtc($supervisors[0].CreatedFileTime).ToString('o')
}
$actions.Topology={param($c,$budget) Check-Topology $budget}
$actions.Sample={param($c,$budget) Observe 'sample' $c.phase (Owner-File $c) $budget}
$actions.SaveBinding={param($c,$budget) Owner-File $c | Out-Null}
$actions.Guardian={param($c,$budget) Observe 'guardian' $c.phase (Owner-File $c) $budget | Out-Null}
$actions.Stop={param($c,$budget)
    Quiesce
    Save-New 'one-controlled-restart.json' @{firstGeneration=$ownership;quiescence='PASS'} | Out-Null
    $session.Dispose();$script:session=$null
}
$actions.PublishReady={param($c,$budget)
    $cfg=Get-Content -LiteralPath $p.phases[1].readonlyConfig -Raw | ConvertFrom-Json -AsHashtable
    $expect=Get-Content -LiteralPath $cfg.expectationsPath -Raw | ConvertFrom-Json -AsHashtable
    $expect.automationRuntime=$c.binding
    $expect.services.MomentumHunterAutomation.PathName=$p.phases[1].serviceDefinition
    $c.expectationsPath=Save-New 'second-generation-guardian-expectations.json' $expect
    $c.expectationsSha256=Hash $c.expectationsPath
    $script:ownership.pendingGuardianSlots=$p.requiredGuardianSlots
    $c.guardianRequests=@()
    foreach ($slot in $p.requiredGuardianSlots) {
        $argv=@('-B',(Join-Path $p.canonicalRoot 'tools\check_automation_preopen.py'),'--session-date',$p.sessionDate,
            '--manifest',$cfg.manifestPath,'--state',$cfg.statePath,'--continuous',$cfg.continuousPath,
            '--canonical',$p.canonicalRoot,'--expected-canonical',$cfg.canonicalHead,
            '--expected-manifest-sha256',$cfg.staticFiles[$cfg.manifestPath],
            '--expected-continuous-sha256',$cfg.staticFiles[$cfg.continuousPath],
            '--expectations',$c.expectationsPath,'--expected-expectations-sha256',$c.expectationsSha256,
            '--output-root',(Join-Path $evidence ('guardian-'+$slot.name)))
        $arguments=($argv | ForEach-Object {[MomentumHunter.AutomationService.WindowsContainedProcess]::Quote($_)}) -join ' '
        $c.guardianRequests+=@{name=$slot.name;path=$slot.path;atUtc=$slot.atUtc;executable=$p.observerPython;
            arguments=$arguments;workingDirectory=$p.canonicalRoot;principalSid=$p.serviceSid;logonType=$slot.logonType;
            expectationsPath=$c.expectationsPath;expectationsSha256=$c.expectationsSha256;readOnly=$true;occurrences=1}
    }
    $c.readyRequest=Save-New 'forward-gates-awaiting-schedule.json' @{status='AWAITING_PARENT_GUARDIAN_REGISTRATION';
        candidate=$p.acceptedCandidateCommit;planSha256=$PlanSha256;binding=$c.binding;guardianTasks=$c.guardianRequests;
        scheduleAckPath=$p.scheduleAckPath;providerContact=$false;executionAuthorityUsed=$false}
    $c.readyRequestSha256=Hash $c.readyRequest
}
$actions.ScheduleAck={param($c,$budget)
    if (-not (Test-Path -LiteralPath $p.scheduleAckPath)) {return $null}
    [MomentumHunter.AutomationService.RetryLaunchGate]::ValidateJson([IO.File]::ReadAllBytes($p.scheduleAckPath))
    $ack=Get-Content -LiteralPath $p.scheduleAckPath -Raw | ConvertFrom-Json -AsHashtable
    if ($ack.status -ne 'PASS' -or $ack.planSha256 -cne $PlanSha256 -or
        $ack.readyRequestSha256 -cne $c.readyRequestSha256 -or $ack.expectationsSha256 -cne $c.expectationsSha256) {
        throw 'PARENT_GUARDIAN_ACK_NOT_BOUND_TO_READY_GENERATION'
    }
    return $ack
}
$actions.VerifySchedule={param($c,$budget)
    $verified=@()
    foreach ($slot in $c.guardianRequests) {
        $task=Get-ScheduledTask -TaskPath $slot.path -TaskName $slot.name
        $xml=Export-ScheduledTask -TaskPath $slot.path -TaskName $slot.name
        $sha=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($xml))).ToLowerInvariant()
        $records=@($c.scheduleAck.tasks | Where-Object {$_.name -ceq $slot.name -and $_.path -ceq $slot.path})
        if ($records.Count -ne 1 -or $records[0].definitionSha256 -cne $sha) {throw 'REGISTERED_GUARDIAN_XML_MISMATCH'}
        [xml]$doc=$xml
        $triggers=@($doc.SelectNodes("/*[local-name()='Task']/*[local-name()='Triggers']/*"))
        if ($triggers.Count -ne 1 -or $triggers[0].LocalName -ne 'TimeTrigger' -or
            $triggers[0].SelectSingleNode("*[local-name()='Repetition']") -or
            [DateTimeOffset]::Parse($triggers[0].StartBoundary).UtcDateTime -ne [DateTimeOffset]::Parse($slot.atUtc).UtcDateTime) {throw 'GUARDIAN_NOT_EXACTLY_ONCE'}
        $user=$task.Principal.UserId
        $sid=if ($user -like 'S-1-*') {$user} else {([Security.Principal.NTAccount]::new($user)).Translate([Security.Principal.SecurityIdentifier]).Value}
        $actionsRead=@($task.Actions)
        if (-not $task.Settings.Enabled -or $sid -cne $slot.principalSid -or [string]$task.Principal.LogonType -cne $slot.logonType -or
            $actionsRead.Count -ne 1 -or $actionsRead[0].Execute -ine $slot.executable -or
            $actionsRead[0].Arguments -cne $slot.arguments -or $actionsRead[0].WorkingDirectory -ine $slot.workingDirectory -or
            (Get-ScheduledTaskInfo -InputObject $task).NextRunTime.ToUniversalTime() -ne [DateTimeOffset]::Parse($slot.atUtc).UtcDateTime) {
            throw 'GUARDIAN_ACTUAL_ACTION_PRINCIPAL_OR_OCCURRENCE_MISMATCH'
        }
        $verified+=@{name=$slot.name;path=$slot.path;definitionSha256=$sha}
    }
    if ($verified.Count -ne @($c.scheduleAck.tasks).Count) {throw 'EXTRA_GUARDIAN_ACK_RECORD'}
    $script:ownership.verifiedGuardianTasks=$verified
    Save-New 'registered-guardian-readback.json' @{status='PASS';tasks=$verified;expectationsSha256=$c.expectationsSha256} | Out-Null
}
$actions.PrepareCommit={param($c,$budget)
    Assert-Time 25
    Assert-Closure
    if ((Hash $c.expectationsPath) -cne $c.expectationsSha256) {throw 'FINAL_GUARDIAN_EXPECTATIONS_DRIFT'}
    Save-New 'all-precommit-gates-proven.json' @{status='PASS';at=[DateTimeOffset]::UtcNow.ToString('o');
        binding=$c.binding;planSha256=$PlanSha256;restartCount=1;custody='PRECOMMIT';executionAuthorityUsed=$false} | Out-Null
}
$actions.Commit={param($c,$budget)
    Assert-Time ([int][Math]::Ceiling($budget))
    $bound=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($budget))
    try {$session.CommitPermanentAsync($bound.Token).GetAwaiter().GetResult()} finally {$bound.Dispose()}
}
$actions.ReconcileCommit={param($c,$budget)
    if ($session.ReconcileCommit()) {'COMMITTED'} else {'ABSENT'}
}
$actions.Abort={param($c,$budget) Quiesce}
$actions.Record={param($c,$result) Save-New 'production-terminal-result.json' $result | Out-Null}
try {
    $result=Invoke-MHRetryWorkflow -Plan $p -Actions $actions
    $result | ConvertTo-Json -Depth 30
    if ($result.status -ne 'PASS') {throw 'RETRY_WORKFLOW_NOT_ACCEPTED'}
} finally {if ($null -ne $session) {$session.Dispose()}}
