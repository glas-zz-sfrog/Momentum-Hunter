param([Parameter(Mandatory=$true)][string]$Source)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$t=$null;$e=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Source 'tools/invoke_prechild_automation_retry.ps1'),[ref]$t,[ref]$e)
if ($e.Count) {throw 'ADAPTER_PARSE_FAILED'}
$definition=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Quiesce'},$true))
if ($definition.Count -ne 1) {throw 'EXACT_QUIESCE_DEFINITION_REQUIRED'}
# Execute the exact adapter function only, with inert service/session boundaries.
Invoke-Expression $definition[0].Extent.Text
function Service {$script:serviceReads++; @{State='Stopped';ProcessId=0}}
function Get-Service {
    $s=[pscustomobject]@{}
    $s | Add-Member ScriptMethod WaitForStatus {param($status,$timeout)}
    $s
}
function Stop-Service {throw 'SCM_SIDE_EFFECT_NOT_ALLOWED'}
$ownership=$null
$results=@()
foreach($decision in @('ABORT_RESERVED','COMMIT_RESERVED','COMMITTED')) {
    $serviceReads=0
    $session=[pscustomobject]@{Decision=$decision;AbortCalled=$false}
    $session | Add-Member ScriptMethod ReconcileCommit {return $false}
    $session | Add-Member ScriptMethod Abort {
        $this.AbortCalled=$true
        if ($this.Decision -eq 'COMMIT_RESERVED') {throw 'COMMIT_OUTCOME_UNKNOWN'}
        if ($this.Decision -eq 'COMMITTED') {throw 'PERMANENT_CUSTODY_ALREADY_COMMITTED'}
    }
    $session | Add-Member ScriptMethod MemberPids {return @()}
    $failure=$null
    try {Quiesce} catch {$failure=$_.Exception.Message}
    if (-not $session.AbortCalled) {throw 'NATIVE_ABORT_FENCE_NOT_CALLED'}
    if ($decision -eq 'ABORT_RESERVED') {
        if ($failure -or $serviceReads -ne 2) {throw 'FENCED_QUIESCENCE_NOT_COMPLETED'}
    } elseif (-not $failure -or $serviceReads -ne 0) {throw 'SCM_ACCESSED_AFTER_COMMIT_RESERVATION'}
    $results+=@{decision=$decision;serviceReads=$serviceReads;failure=$failure;status='PASS'}
}
@{status='PASS';actualAdapterFunction=$true;nativeBoundaryIsFixture=$true;cases=$results;realScmOperations=0}|ConvertTo-Json -Depth 10
