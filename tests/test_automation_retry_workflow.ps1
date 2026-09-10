param([Parameter(Mandatory=$true)][string]$Source)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $Source 'tools\automation_retry_workflow.psm1') -Force

function Case([string]$Mode,[string]$Expected,[string]$ErrorPattern='') {
    $s=@{mono=0.0;utc=[DateTimeOffset]::Parse('2026-09-10T05:00:00Z');version=10;starts=0;stops=0;aborts=0;
        commits=0;durable=$false;reads=0;startMono=0.0;stable=@();published=$false;trace=[Collections.Generic.List[string]]::new();mode=$Mode}
    $a=@{}
    $a.Clock={@{mono=$s.mono;utc=$s.utc.AddSeconds($s.mono)}}.GetNewClosure()
    $a.Preflight={param($c,$b)
        $s.trace.Add('Preflight'+$c.phase); $s.mono+=1
        if ($s.mode -eq 'preflight-fail') {throw 'ADOPTED_INPUT_MISMATCH'}
        @{observation=@{state=@{state_version=$s.version}}}
    }.GetNewClosure()
    $a.Start={param($c,$b)
        $s.starts++;$s.reads=0;$s.startMono=$s.mono;$s.trace.Add('Start'+$c.phase)
        if ($s.mode -eq 'start-fail') {throw 'SCM_FIXTURE_FAILURE'}
        if ($s.mode -eq 'start-timeout') {$s.mono+=$b;return}
        $s.mono+=if ($s.mode -like 'boundary-*') {30} else {5}
    }.GetNewClosure()
    $a.Topology={param($c,$b)
        $s.trace.Add('Topology');$s.mono+=1
        if ($s.mode -eq 'topology-fail') {throw 'WRONG_PARENT'}
    }.GetNewClosure()
    $a.Sample={param($c,$b)
        $s.reads++;$s.trace.Add('Sample');$s.version++
        $s.mono+=if ($s.mode -like 'boundary-*') {10} else {5}
        if ($s.mode -like 'boundary-*' -and $null -ne $c.startupDeadline) {
            if ($s.reads -le 6) {return @{truth=@{ready=$false;pending=$true;state='STARTING'}}}
            if ($s.reads -eq 8) {$s.mono=$s.startMono+[double]$s.mode.Substring(9)}
        }
        $instance='generation-'+$c.phase
        $started='2026-09-10T05:00:0'+$c.phase+'Z'
        $binding=@{serviceInstanceId=$instance;serviceStartedAt=$started;minimumStateVersion=$s.version}
        $v=@{ready=$true;state='HEALTHY';serviceInstanceId=$instance;serviceStartedAt=$started;
            stateVersion=$s.version;heartbeatAt=$s.utc.AddSeconds($s.mono).ToString('o')}
        if ($c.phase -eq 1 -and $s.mode -eq 'restart-rollback') {$v.stateVersion=1}
        if ($null -eq $c.startupDeadline -and -not $s.published) {
            $s.stable+=,$s.mono
            if ($s.stable.Count -eq 2) {
                switch ($s.mode) {
                    'generation-change' {$v.serviceInstanceId='foreign'}
                    'start-change' {$v.serviceStartedAt='2026-09-10T05:00:09Z'}
                    'same-version-new-heartbeat' {$v.stateVersion=$c.lastSample.truth.stateVersion}
                    'stability-stale' {$v.ready=$false;$v.state='STALE'}
                    'stability-gap' {$s.mono+=11}
                }
            }
        }
        @{truth=$v;binding=$binding}
    }.GetNewClosure()
    $a.SaveBinding={param($c,$b) $s.trace.Add('SaveBinding')}.GetNewClosure()
    $a.Guardian={param($c,$b)
        $s.trace.Add('Guardian');$s.mono+=1
        if ($s.mode -eq 'guardian-fail') {throw 'GUARDIAN_NOT_GREEN'}
        if ($s.published -and $s.mode -eq 'post-schedule-stale') {throw 'FINAL_GUARDIAN_STALE'}
    }.GetNewClosure()
    $a.Stop={param($c,$b) $s.trace.Add('Stop');$s.stops++;$s.mono+=1}.GetNewClosure()
    $a.PublishReady={param($c,$b) $s.trace.Add('PublishReady');$s.published=$true;$s.mono+=1}.GetNewClosure()
    $a.ScheduleAck={param($c,$b)
        $s.trace.Add('ScheduleAck');$s.mono+=1
        if ($s.mode -eq 'ack-timeout') {return $null}
        @{instance=$c.binding.serviceInstanceId}
    }.GetNewClosure()
    $a.VerifySchedule={param($c,$b)
        $s.trace.Add('VerifySchedule');$s.mono+=1
        if ($s.mode -eq 'wrong-guardian-binding') {throw 'GUARDIAN_BOUND_TO_OLD_GENERATION'}
    }.GetNewClosure()
    $a.PrepareCommit={param($c,$b) $s.trace.Add('PrepareCommit');$s.mono+=1}.GetNewClosure()
    $a.Commit={param($c,$b)
        $s.trace.Add('Commit');$s.commits++;$s.mono+=1
        if ($s.mode -eq 'commit-absent') {throw 'COMMIT_SEND_FAILED'}
        $s.durable=$true
        if ($s.mode -in @('ack-lost','commit-unknown')) {throw 'COMMIT_ACK_LOST'}
    }.GetNewClosure()
    $a.ReconcileCommit={param($c,$b)
        $s.trace.Add('ReconcileCommit')
        if ($s.mode -eq 'commit-unknown') {return 'UNKNOWN'}
        if ($s.durable) {return 'COMMITTED'} else {return 'ABSENT'}
    }.GetNewClosure()
    $a.Abort={param($c,$b)
        $s.trace.Add('Abort');$s.aborts++;$s.mono+=1
        if ($s.mode -eq 'cleanup-fail') {throw 'CLEANUP_FIXTURE_FAILURE'}
    }.GetNewClosure()
    $a.Record={param($c,$r) $s.trace.Add('Record');if ($s.mode -eq 'record-fail') {throw 'DISK_FIXTURE_FAILURE'}}.GetNewClosure()
    $plan=@{startupSeconds=120;stabilitySeconds=180;sampleGapSeconds=15;scheduleAckSeconds=600;
        cleanupSeconds=60;maximumSeconds=1800;cutoffAt='2026-09-10T06:00:00Z'}
    $r=Invoke-MHRetryWorkflow -Plan $plan -Actions $a
    if ($r.status -ne $Expected) {throw "$Mode expected $Expected; actual $($r | ConvertTo-Json -Compress)"}
    if ($ErrorPattern -and $r.error -notmatch $ErrorPattern) {throw "$Mode wrong error: $($r.error)"}
    if ($s.starts -gt 2 -or $s.commits -gt 1) {throw "EXCESS_AUTHORITY:$Mode"}
    if ($Expected -eq 'PASS') {
        if ($s.starts -ne 2 -or $s.stops -ne 1 -or $s.aborts -ne 0 -or $s.commits -ne 1 -or
            $s.stable[-1]-$s.stable[0] -lt 180) {throw "INCOMPLETE_WORKFLOW:$Mode"}
    }
    if ($Mode -in @('ack-lost','commit-unknown','record-fail') -and $s.aborts -ne 0) {throw 'POSTCOMMIT_ROLLBACK_OCCURRED'}
    if ($Mode -eq 'ack-lost' -and $r.custody -ne 'COMMITTED_NOT_HEALTH_PROVEN') {throw 'DURABLE_COMMIT_MISCLASSIFIED'}
    if ($Mode -eq 'commit-unknown' -and $r.custody -ne 'COMMIT_OUTCOME_UNKNOWN') {throw 'UNKNOWN_COMMIT_MISCLASSIFIED'}
    if ($Mode -eq 'preflight-fail' -and $s.starts -ne 0) {throw 'PREMUTATION_GATE_BYPASSED'}
    @{case=$Mode;status='PASS';workflow=$r;starts=$s.starts;stops=$s.stops;aborts=$s.aborts;
        virtualSeconds=$s.mono;trace=$s.trace.ToArray();realSideEffects=$false}
}

$results=@(
    Case 'normal' 'PASS'
    Case 'boundary-119.999' 'PASS'
    Case 'boundary-120' 'FAIL' 'DEADLINE'
    Case 'boundary-120.001' 'FAIL' 'DEADLINE'
    Case 'preflight-fail' 'FAIL' 'INPUT_MISMATCH'
    Case 'start-fail' 'FAIL' 'SCM_FIXTURE_FAILURE'
    Case 'start-timeout' 'FAIL' 'DEADLINE'
    Case 'topology-fail' 'FAIL' 'WRONG_PARENT'
    Case 'guardian-fail' 'FAIL' 'GUARDIAN_NOT_GREEN'
    Case 'restart-rollback' 'FAIL' 'VERSION_ROLLBACK'
    Case 'generation-change' 'FAIL' 'GENERATION_CHANGED'
    Case 'start-change' 'FAIL' 'GENERATION_CHANGED'
    Case 'same-version-new-heartbeat' 'FAIL' 'HEARTBEAT_REGRESSION'
    Case 'stability-stale' 'FAIL' 'HEARTBEAT_REJECTED'
    Case 'stability-gap' 'FAIL' 'OBSERVATION_GAP'
    Case 'wrong-guardian-binding' 'FAIL' 'OLD_GENERATION'
    Case 'post-schedule-stale' 'FAIL' 'GUARDIAN_STALE'
    Case 'ack-timeout' 'FAIL' 'ACK_TIMEOUT'
    Case 'commit-absent' 'FAIL' 'COMMIT_SEND_FAILED'
    Case 'ack-lost' 'FAIL' 'COMMIT_ACK_LOST'
    Case 'commit-unknown' 'FAIL' 'COMMIT_ACK_LOST'
    Case 'record-fail' 'FAIL' 'EVIDENCE_WRITE_FAILED'
)
@{status='PASS';cases=$results.Count;results=$results;realScmOperations=0;realProviderCalls=0} | ConvertTo-Json -Depth 20
