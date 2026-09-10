Set-StrictMode -Version Latest

function Invoke-MHRetryWorkflow {
    param([Parameter(Mandatory=$true)][hashtable]$Plan,
          [Parameter(Mandatory=$true)][hashtable]$Actions)
    # Side effects live in the hash-bound executable adapter. Tests bind only fakes.
    $required=@('Clock','Preflight','Start','Topology','Sample','SaveBinding','Guardian','Stop',
        'PublishReady','ScheduleAck','VerifySchedule','PrepareCommit','Commit','ReconcileCommit','Abort','Record')
    foreach ($name in $required) {if (-not ($Actions[$name] -is [scriptblock])) {throw "WORKFLOW_ADAPTER_MISSING:$name"}}
    if ($Plan.startupSeconds -ne 120 -or $Plan.stabilitySeconds -ne 180 -or $Plan.sampleGapSeconds -ne 15 -or
        $Plan.scheduleAckSeconds -ne 600 -or $Plan.cleanupSeconds -lt 30 -or $Plan.cleanupSeconds -gt 90) {throw 'WORKFLOW_POLICY_MISMATCH'}
    $initial=& $Actions.Clock
    $context=@{phase=-1;binding=$null;prestart=$null;startRequested=$false;commitRequested=$false;
        custody='PRECOMMIT';startupDeadline=$null;lastSample=$null;sequence=0}
    $cutoff=[DateTimeOffset]::Parse($Plan.cutoffAt)
    function Remaining([double]$Cap) {
        $clock=& $Actions.Clock
        $seconds=[Math]::Min($Plan.maximumSeconds-($clock.mono-$initial.mono)-$Plan.cleanupSeconds,
            ($cutoff-$clock.utc).TotalSeconds-$Plan.cleanupSeconds)
        if ($null -ne $context.startupDeadline) {$seconds=[Math]::Min($seconds,$context.startupDeadline-$clock.mono)}
        if ($seconds -le 0) {throw 'WORKFLOW_DEADLINE_EXHAUSTED'}
        return [Math]::Min($Cap,$seconds)
    }
    function Stage([string]$Name,[double]$Cap) {
        $budget=Remaining $Cap
        $started=& $Actions.Clock
        $context.sequence++
        $value=& $Actions[$Name] $context $budget
        $ended=& $Actions.Clock
        if ($ended.mono-$started.mono -ge $budget) {throw "STAGE_DEADLINE_EXHAUSTED:$Name"}
        Remaining 1 | Out-Null
        return $value
    }
    function Validate-Sample($sample,[switch]$AllowStarting) {
        $v=$sample.truth
        if ($v.ready -ne $true -or $v.state -ne 'HEALTHY') {
            if ($AllowStarting -and $null -eq $context.binding -and $v.pending -eq $true -and
                $v.state -in @('STARTING','WAITING_FOR_FIRST_HEARTBEAT')) {return $false}
            throw "WORKFLOW_HEARTBEAT_REJECTED:$($v.state)"
        }
        if ($v.stateVersion -le $context.prestart.observation.state.state_version) {throw 'CROSS_RESTART_VERSION_ROLLBACK'}
        if ($null -eq $context.binding) {$context.binding=$sample.binding}
        if ($v.serviceInstanceId -cne $context.binding.serviceInstanceId -or
            $v.serviceStartedAt -cne $context.binding.serviceStartedAt) {throw 'WORKFLOW_GENERATION_CHANGED'}
        if ($null -ne $context.lastSample) {
            $last=$context.lastSample.truth
            $delta=[DateTimeOffset]::Parse($v.heartbeatAt)-[DateTimeOffset]::Parse($last.heartbeatAt)
            if ($v.stateVersion -lt $last.stateVersion -or $delta.TotalSeconds -lt 0 -or
                ($v.stateVersion -eq $last.stateVersion -and $v.heartbeatAt -cne $last.heartbeatAt)) {throw 'WORKFLOW_HEARTBEAT_REGRESSION'}
        }
        $context.lastSample=$sample
        return $true
    }
    $result=$null
    try {
        for ($phase=0;$phase -lt 2;$phase++) {
            $context.phase=$phase
            $context.prestart=Stage 'Preflight' 60
            $context.binding=$null; $context.lastSample=$null
            $clock=& $Actions.Clock
            $context.startupDeadline=$clock.mono+120
            $context.startRequested=$true
            Stage 'Start' 45 | Out-Null
            $first=$null
            while ($true) {
                Stage 'Topology' 15 | Out-Null
                $sample=Stage 'Sample' 25
                if (Validate-Sample $sample -AllowStarting) {
                    Stage 'SaveBinding' 5 | Out-Null
                    if ($null -eq $first) {$first=$sample.truth}
                    elseif ($sample.truth.stateVersion -gt $first.stateVersion -and
                        [DateTimeOffset]::Parse($sample.truth.heartbeatAt) -gt [DateTimeOffset]::Parse($first.heartbeatAt)) {break}
                }
            }
            $context.startupDeadline=$null
            Stage 'Guardian' 30 | Out-Null
            if ($phase -eq 0) {Stage 'Stop' $Plan.cleanupSeconds | Out-Null; $context.startRequested=$false}
        }
        $first=$null; $firstClock=$null; $priorClock=$null
        do {
            Stage 'Topology' 15 | Out-Null
            $sample=Stage 'Sample' 25
            Validate-Sample $sample | Out-Null
            $clock=& $Actions.Clock
            if ($null -ne $priorClock -and $clock.mono-$priorClock -gt 15) {throw 'STABILITY_OBSERVATION_GAP_EXCEEDED'}
            if ($null -eq $first) {$first=$sample.truth; $firstClock=$clock.mono}
            $priorClock=$clock.mono
        } while ($clock.mono-$firstClock -lt 180)
        if ($sample.truth.stateVersion -le $first.stateVersion -or
            [DateTimeOffset]::Parse($sample.truth.heartbeatAt) -le [DateTimeOffset]::Parse($first.heartbeatAt)) {throw 'STABILITY_DID_NOT_ADVANCE'}
        Stage 'Guardian' 30 | Out-Null
        Stage 'PublishReady' 10 | Out-Null
        $ackClock=(& $Actions.Clock).mono
        do {
            if ((& $Actions.Clock).mono-$ackClock -ge 600) {throw 'GUARDIAN_ACTIVATION_ACK_TIMEOUT'}
            Stage 'Topology' 15 | Out-Null
            $sample=Stage 'Sample' 25
            Validate-Sample $sample | Out-Null
            $context.scheduleAck=Stage 'ScheduleAck' 5
        } while ($null -eq $context.scheduleAck)
        Stage 'VerifySchedule' 20 | Out-Null
        Stage 'Guardian' 30 | Out-Null
        Stage 'Topology' 15 | Out-Null
        Stage 'PrepareCommit' 10 | Out-Null
        $context.commitRequested=$true
        Stage 'Commit' 20 | Out-Null
        $context.custody='COMMITTED_HEALTH_PROVEN_AT_HANDOFF'
        $result=@{status='PASS';custody=$context.custody;restartCount=1;phase=1;executionAuthorityUsed=$false}
    } catch {
        $failure=$_.Exception.Message
        $context.startupDeadline=$null
        $cleanup='NOT_STARTED'
        if ($context.commitRequested) {
            # Durable publication is the authority boundary. Never stop SCM first and
            # discover afterward that permanent custody had already been committed.
            try {
                $commit=& $Actions.ReconcileCommit $context 10
                $context.custody=if ($commit -eq 'COMMITTED') {'COMMITTED_NOT_HEALTH_PROVEN'}
                    elseif ($commit -eq 'ABSENT') {'PRECOMMIT'} else {'COMMIT_OUTCOME_UNKNOWN'}
            } catch {$context.custody='COMMIT_OUTCOME_UNKNOWN'}
        }
        if ($context.startRequested -and $context.custody -eq 'PRECOMMIT') {
            $begin=& $Actions.Clock
            try {
                & $Actions.Abort $context $Plan.cleanupSeconds | Out-Null
                $end=& $Actions.Clock
                if ($end.mono-$begin.mono -ge $Plan.cleanupSeconds) {throw 'CLEANUP_DEADLINE_EXHAUSTED'}
                $cleanup='QUIESCED'
            } catch {$cleanup='UNPROVEN:'+$_.Exception.Message}
        } elseif ($context.custody -ne 'PRECOMMIT') {$cleanup='NO_POSTCOMMIT_MUTATION_AUTHORIZED'}
        $result=@{status='FAIL';error=$failure;custody=$context.custody;cleanup=$cleanup;phase=$context.phase;
            retryAuthorized=$false;postcommitReconciliationRequired=($context.custody -ne 'PRECOMMIT')}
    }
    try {& $Actions.Record $context $result | Out-Null}
    catch {
        $result=@{status='FAIL';error='TERMINAL_EVIDENCE_WRITE_FAILED';originalResult=$result;
            custody=$context.custody;postcommitReconciliationRequired=($context.custody -ne 'PRECOMMIT');retryAuthorized=$false}
    }
    return $result
}
Export-ModuleMember -Function Invoke-MHRetryWorkflow
