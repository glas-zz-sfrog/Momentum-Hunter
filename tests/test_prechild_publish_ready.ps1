param([Parameter(Mandatory=$true)][string]$Source,
      [Parameter(Mandatory=$true)][string]$Assembly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $Source 'tools/automation_retry_workflow.psm1') -Force
[Reflection.Assembly]::LoadFrom($Assembly) | Out-Null
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Source 'tools/invoke_prechild_automation_retry.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) {throw 'ADAPTER_PARSE_FAILED'}
foreach($name in @('Save-New','Hash')) {
    $definitions=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
    if($definitions.Count -ne 1) {throw 'EXACT_FUNCTION_REQUIRED'}
    Invoke-Expression $definitions[0].Extent.Text
}
$actions=@{}
foreach($name in @('PublishReady','ScheduleAck','VerifySchedule')) {
    $definitions=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq ('$actions.'+$name)},$true))
    if($definitions.Count -ne 1) {throw 'EXACT_ACTION_REQUIRED'}
    Invoke-Expression $definitions[0].Extent.Text
}
# Only test-owned filesystem data and inert SCM/scheduler boundaries are used.
function Start-Service {throw 'REAL_SERVICE_ACTION_FORBIDDEN'}
function Stop-Service {throw 'REAL_SERVICE_ACTION_FORBIDDEN'}
function Register-ScheduledTask {throw 'REAL_SCHEDULE_ACTION_FORBIDDEN'}
function Get-ScheduledTask {param($TaskPath,$TaskName) $script:fakeTask}
function Export-ScheduledTask {param($TaskPath,$TaskName) $script:fakeXml}
function Get-ScheduledTaskInfo {param($InputObject) @{NextRunTime=[DateTimeOffset]::Parse($p.requiredGuardianSlots[0].atUtc).LocalDateTime}}
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class TestWindowsArgumentParser {
    [DllImport("shell32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern IntPtr CommandLineToArgvW(string text, out int count);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr memory);
    public static string[] Parse(string text) {
        int count; var memory=CommandLineToArgvW(text,out count);
        if(memory==IntPtr.Zero) throw new InvalidOperationException("ARGV_PARSE_FAILED");
        try {var args=new string[count]; for(int i=0;i<count;i++)
            args[i]=Marshal.PtrToStringUni(Marshal.ReadIntPtr(memory,i*IntPtr.Size)); return args;}
        finally {LocalFree(memory);}
    }
}
'@
$results=@()
$argumentsToTest=@('','plain','two words','quote"value','C:\space path\','backslash\"quote','C:\tail\\')
foreach($argument in $argumentsToTest) {
    $quoted=[MomentumHunter.AutomationService.WindowsContainedProcess]::Quote($argument)
    $parsed=[TestWindowsArgumentParser]::Parse('fixture.exe '+$quoted)
    if($parsed.Count -ne 2 -or $parsed[1] -cne $argument) {throw 'NATIVE_ARGUMENT_ROUNDTRIP_FAILED'}
    $results+=@{case='argument-roundtrip';value=$argument;status='PASS'}
}
$nulRejected=$false
try {[MomentumHunter.AutomationService.WindowsContainedProcess]::Quote("bad$([char]0)value") | Out-Null} catch {$nulRejected=$true}
if(-not $nulRejected) {throw 'NUL_ARGUMENT_ACCEPTED'}
$results+=@{case='nul-rejected';status='PASS'}
$evidence=Join-Path ([IO.Path]::GetTempPath()) ('MH-Prechild-PublishReady-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($evidence) | Out-Null
$expectPath=Join-Path $evidence 'fixture-expectations.json'
$configPath=Join-Path $evidence 'fixture-config.json'
$canonical='C:\inert canonical with spaces'
$manifest='C:\inert input\manifest.json';$continuous='C:\inert input\continuous.json'
$expect=@{automationRuntime=@{};services=@{MomentumHunterAutomation=@{PathName='old fixture selector'}}}
$cfg=@{expectationsPath=$expectPath;manifestPath=$manifest;statePath='C:\inert input\state.json';continuousPath=$continuous;
    canonicalHead=('a'*40);staticFiles=@{$manifest=('b'*64);$continuous=('c'*64)}}
[IO.File]::WriteAllText($expectPath,($expect|ConvertTo-Json -Depth 20))
[IO.File]::WriteAllText($configPath,($cfg|ConvertTo-Json -Depth 20))
$p=@{phases=@(@{},@{readonlyConfig=$configPath;serviceDefinition='new fixture selector'});
    canonicalRoot=$canonical;sessionDate='2026-09-10';observerPython='C:\inert python\python.exe';serviceSid='S-1-5-18';
    requiredGuardianSlots=@(@{name='test-only';path='\inert\';atUtc='2026-09-10T13:00:00Z';logonType='ServiceAccount'});
    acceptedCandidateCommit=('d'*40);scheduleAckPath=(Join-Path $evidence 'fixture-ack.json')}
$PlanSha256='e'*64;$ownership=@{};$c=@{binding=@{serviceInstanceId='synthetic-exact-generation'}}
& $actions.PublishReady $c 25
if($c.guardianRequests.Count -ne 1) {throw 'REQUEST_COUNT'}
$request=$c.guardianRequests[0]
$argv=[TestWindowsArgumentParser]::Parse('fixture.exe '+$request.arguments)
if($argv.Count -ne 25 -or $argv[1] -cne '-B' -or $argv[2] -cne (Join-Path $canonical 'tools\check_automation_preopen.py')) {throw 'ACTUAL_GUARDIAN_ARGUMENTS_INVALID'}
foreach($pair in @(@('--manifest',$manifest),@('--canonical',$canonical),@('--expectations',$c.expectationsPath),@('--expected-expectations-sha256',$c.expectationsSha256))) {
    $index=[Array]::IndexOf($argv,$pair[0]); if($index -lt 0 -or $argv[$index+1] -cne $pair[1]) {throw 'ARGUMENT_VALUE_NOT_PRESERVED'}
}
$saved=ConvertFrom-MHRetryJson ([IO.File]::ReadAllText($c.readyRequest))
$savedExpect=ConvertFrom-MHRetryJson ([IO.File]::ReadAllText($c.expectationsPath))
if($saved.status -cne 'AWAITING_PARENT_GUARDIAN_REGISTRATION' -or $saved.providerContact -or $saved.executionAuthorityUsed -or
   $savedExpect.automationRuntime.serviceInstanceId -cne $c.binding.serviceInstanceId -or -not $request.readOnly -or $request.occurrences -ne 1) {throw 'PUBLICATION_BINDING_FAILED'}
$results+=@{case='actual-publish-ready';status='PASS'}
$duplicateRejected=$false
try {& $actions.PublishReady @{binding=$c.binding} 25} catch {$duplicateRejected=$true}
if(-not $duplicateRejected) {throw 'EVIDENCE_OVERWRITE_ALLOWED'}
$results+=@{case='write-once-publication';status='PASS'}
if($null -ne (& $actions.ScheduleAck $c 25)) {throw 'MISSING_ACK_NOT_PENDING'}
$fakeXml='<Task><Triggers><TimeTrigger><StartBoundary>2026-09-10T13:00:00Z</StartBoundary></TimeTrigger></Triggers></Task>'
$fakeTask=@{Principal=@{UserId=$p.serviceSid;LogonType='ServiceAccount'};Settings=@{Enabled=$true};Actions=@(@{
    Execute=$request.executable;Arguments=$request.arguments;WorkingDirectory=$request.workingDirectory})}
function Make-Ack {
    @{status='PASS';planSha256=$PlanSha256;readyRequestSha256=$c.readyRequestSha256;expectationsSha256=$c.expectationsSha256;
      tasks=@(@{name=$request.name;path=$request.path;definitionSha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($script:fakeXml))).ToLowerInvariant()})}
}
$ack=Make-Ack
[IO.File]::WriteAllText($p.scheduleAckPath,($ack|ConvertTo-Json -Depth 20))
$c.scheduleAck=& $actions.ScheduleAck $c 25
& $actions.VerifySchedule $c 25
$results+=@{case='actual-ack-and-schedule-readback';status='PASS'}
$originalArguments=$fakeTask.Actions[0].Arguments
$publicationEvidence=$evidence
foreach($case in @('ack-hash','duplicate-json','repeat-trigger','wrong-time','disabled-task','changed-arguments','extra-ack-record')) {
    $evidence=Join-Path $publicationEvidence $case
    [IO.Directory]::CreateDirectory($evidence) | Out-Null
    $fakeXml='<Task><Triggers><TimeTrigger><StartBoundary>2026-09-10T13:00:00Z</StartBoundary></TimeTrigger></Triggers></Task>'
    $fakeTask.Settings.Enabled=$true;$fakeTask.Actions[0].Arguments=$originalArguments
    if($case -eq 'repeat-trigger') {$fakeXml=$fakeXml.Replace('</TimeTrigger>','<Repetition><Interval>PT1H</Interval></Repetition></TimeTrigger>')}
    if($case -eq 'wrong-time') {$fakeXml=$fakeXml.Replace('13:00','14:00')}
    if($case -eq 'disabled-task') {$fakeTask.Settings.Enabled=$false}
    if($case -eq 'changed-arguments') {$fakeTask.Actions[0].Arguments+=' unauthorized'}
    $ack=Make-Ack
    if($case -eq 'ack-hash') {$ack.planSha256='f'*64}
    if($case -eq 'extra-ack-record') {$ack.tasks+=@{name='extra';path='\inert\';definitionSha256='f'*64}}
    $json=$ack|ConvertTo-Json -Depth 20
    if($case -eq 'duplicate-json') {$json='{"status":"PASS","status":"PASS"}'}
    [IO.File]::WriteAllText($p.scheduleAckPath,$json)
    $expected=@{'ack-hash'='PARENT_GUARDIAN_ACK_NOT_BOUND_TO_READY_GENERATION';'duplicate-json'='DUPLICATE_JSON_FIELD';
        'repeat-trigger'='GUARDIAN_NOT_EXACTLY_ONCE';'wrong-time'='GUARDIAN_NOT_EXACTLY_ONCE';
        'disabled-task'='GUARDIAN_ACTUAL_ACTION_PRINCIPAL_OR_OCCURRENCE_MISMATCH';
        'changed-arguments'='GUARDIAN_ACTUAL_ACTION_PRINCIPAL_OR_OCCURRENCE_MISMATCH';'extra-ack-record'='EXTRA_GUARDIAN_ACK_RECORD'}[$case]
    $diagnostic=''
    try {$c.scheduleAck=& $actions.ScheduleAck $c 25; & $actions.VerifySchedule $c 25} catch {$diagnostic=$_.Exception.Message}
    if($diagnostic -notlike ('*'+$expected+'*')) {throw "NEGATIVE_NOT_EXACT:$case : $diagnostic"}
    $results+=@{case=$case;status='PASS'}
}
@{status='PASS';actualAdapterActions=@('PublishReady','ScheduleAck','VerifySchedule');cases=$results;
  assemblySha256=(Hash $Assembly);evidenceRoot=$publicationEvidence;realScmOperations=0;realProviderCalls=0}|ConvertTo-Json -Depth 20
