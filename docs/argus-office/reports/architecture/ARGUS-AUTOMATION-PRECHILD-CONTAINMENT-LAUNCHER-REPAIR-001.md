# Pre-child Containment And Retry Controller

Task: ARGUS-AUTOMATION-PRECHILD-CONTAINMENT-LAUNCHER-REPAIR-001

Base canonical: `a5dfbccbb3a77a78bb80412d30f06e610ccecd43`.
Branch: `codex/ARGUS-AUTOMATION-PRECHILD-CONTAINMENT-LAUNCHER-REPAIR-001`.
Status: implementation under qualification, not canonical, not deployed.
Shared Roadmap/ledger/log remain Integration-owned and are not edited here.

## Actual Launch Boundary

SCM is the Automation host's OS parent. The external retry controller is an
admission/custody owner, not its process parent. Before this repair the host used
`Process.Start` to start the configured venv Python with `-B -m
momentum_hunter.automation_supervisor run --manifest <installed manifest>`, in
the canonical repository directory. Python could execute and create descendants
before an external controller's enumeration/assignment. The predecessor's
disposable Windows race evidence is preserved separately; attaching after return
cannot establish a before-first-instruction invariant.

The changed host keeps the existing executable arguments and environment policy:
inherit service environment, set UTF-8/service mode/loaded host hash, remove
OPENAI_API_KEY and CODEX_API_KEY. No environment values, provider authentication,
strategy, scoring, order, or account behavior are changed by this task.

## Native Contract

`WindowsContainedProcess` creates a fresh unnamed inner Job, sets
KILL_ON_JOB_CLOSE with no breakaway permission, and calls CreateProcess with
PROC_THREAD_ATTRIBUTE_JOB_LIST and CREATE_SUSPENDED. Assignment is atomic with
creation; there is no separately exposed post-create/pre-assign window. The
only inherited handles are the explicit stdin/stdout/stderr allowlist. The Job,
process and primary-thread handles are not inherited by the target.

The creator retains native process/thread handles, verifies PID, creation FILETIME,
image path/hash, SID, session, native Job membership and expected parent/command
line, then resumes exactly once. Failure before resume kills the Job without
executing target user code. Polling in tests or exit/topology observation does
not establish containment; kernel assignment does.

References:
- https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs
- https://learn.microsoft.com/en-us/windows/desktop/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
- https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

The boundary covers native process-tree descendants, including detached,
grandchild and ordinary native/Python CreateProcess descendants. It is not a
hostile same-SID sandbox or an administrator-resistance claim. Broker-created
non-descendants (for example WMI-created processes) are not Job descendants and
are not claimed contained. No WMI process creation, task creation, remote process
creation, injection, or hidden broker execution is introduced. WMI usage in the
new controller is read-only process/service metadata or the separately gated
Integration-owned SCM selector operation.

## Retry Lifetime

1. Controller creates outer Job O and a random identity-bound local pipe/contract.
2. Actual host starts trusted CLR/bootstrap code only, opens the exclusive
   contract-owner file, locks and hashes the full declared static input set,
   proves controller PID/birth/executable/hash/SID and authenticates the pipe PID.
3. Controller proves the exact waiting host, enrolls it in O, verifies O contains
   exactly that host, and sends ADMIT. No Python exists before this exchange.
4. Host creates target in fresh inner Job I using atomic JOB_LIST and suspension.
   Target also inherits O from its admitted host. Controller independently checks
   target identity/topology and O membership before RESUME.
5. Only the controller holds O before permanent custody publication. Controller
   death closes O and kills the admitted host/family; host death closes I and
   kills its target/family. No precommit borrowed O alias is retained by the host.
6. Missing, malformed, stale, wrong-user/session, duplicate-owner, expired, drifted,
   torn or partial admission evidence denies Python. Automatic SCM re-entry does
   not create a new admission; without a live valid handshake it fails closed.

The configured venv is a redirector. The observed test topology is host -> venv
Python -> base Python, with one exact conhost child of the venv. Each role binds
parent role, image/hash, command, birth, native membership, SID/session and min/max
cardinality. A process name or aggregate count is never sufficient. Churn during
inspection rejects or waits only within a bounded observation deadline; it cannot
create an uncontained child.

## Permanent Handoff Boundary

Permanent publication is the durable authority linearization point. It happens
only after both starts, controlled restart, live identity/heartbeat progression,
observed stability, current inputs and final Guardian/task binding pass. The host
publishes a write-once receipt, then borrows O, then sends COMMITTED. Publication
precedes borrowing so a precommit host alias cannot defeat controller-death
revocation.

There is an unavoidable distinction between publication and acknowledgement:
- PRECOMMIT: on failure, revoke the owned family and prove quiescence.
- COMMIT_OUTCOME_UNKNOWN: do not retry or claim rollback/success; preserve and
  require Integration reconciliation.
- COMMITTED_NOT_HEALTH_PROVEN: valid publication without a proven ACK/healthy
  transfer. Do not request an ordinary precommit SCM stop. Do not claim continuity.
- COMMITTED_HEALTH_PROVEN_AT_HANDOFF: all precommit gates plus exact COMMITTED
  acknowledgement passed. The receipt, not an optional summary, is primary
  custody evidence.

Controller death between publication and Job borrowing can terminate the accepted
instance. A later accepted-selector restart creates a fresh contained family; it
does not claim uninterrupted survival. Postcommit failures are not silently
reclassified as precommit aborts. This task does not grant independent postcommit
service repair/retry authority. The failed/unknown result stays non-green.

## Controller And Adoption

The actual PowerShell executable adapter uses the testable
`automation_retry_workflow.psm1` orchestration. The production entrypoint does not
accept injected test adapters. Tests call the orchestration with inert effects
and a virtual clock, separately from actual Windows native/host tests.

Before SCM mutation, the controller requires the accepted package hash, its exact
candidate commit/tree and Astra disposition, candidate ancestry in adopted
canonical, exact packaged source/import closure, exact installed/controller native
closures, unused two-phase selectors, full launch static inputs, SID, authorized
Opening loaded-byte binding and reviewed Guardian slots. A current-input dress
proposal deliberately lacks these adoption fields and cannot execute.

The owning Integration task must create the adopted plan from its actual accepted
post-adoption environment. Do not relabel the old captured manifest or copy guessed
hashes. Host apphost identity alone is insufficient: a managed DLL can change
without changing the apphost. Both directories and all native DLL/EXE/JSON bytes
are independently bound to the package before the first selector change.

Startup is 120 seconds from the original phase start, never reset after a slow
step. State version must exceed the prestart floor in each new instance. Once
bound, instance/start cannot be rebound. Stability requires at least 180 seconds
between healthy observations, monotonic version/heartbeat consistency, and at most
15 seconds between stability observations. Sampling does not prove every instant
between observations. Every forward stage receives remaining workflow/startup
budget; cleanup has its separate declared bound. Late work is rejected rather
than extending accepted thresholds.

After second-generation readiness the controller writes immutable bound Guardian
expectations and a parent-registration request. Integration owns actual scheduled
task registration. The controller admits only reviewed future slots, then reads
actual task XML, action/arguments, principal, once-only trigger and next-run UTC,
and checks linkage to the exact second-generation expectations/request hashes.
It rechecks Guardian health after readback. Registration is not claimed execution.

## Proof Inventory

External evidence root:
`F:/ArgusQualification/Automation/ARGUS-AUTOMATION-PRECHILD-CONTAINMENT-LAUNCHER-REPAIR-001-20260909`.

Native proof families include first-action marker before/after verified resume,
immediate Python/native/multiple/grandchild/churn/parent-exit, breakaway rejection,
creator death at every exposed stage, controller death before admission and with a
live family, target death, concurrent spawn/abort, spawn during topology validation,
unrelated same-executable survival, stale-birth rejection, wrong-parent/args/hash/
SID/session/population, invalid static contracts, and permanent fresh restart.

A-C/F/G/M use explicit native creation/resume barriers. C's separate assignment
interval is eliminated by JOB_LIST, not covered by a fabricated event. D uses a
real kernel active-process-limit assignment failure in a disposable outer Job;
an earlier assumption that terminating a Job permanently prevents future admission
was false and its failed test is retained. E checks native foreign-Job membership
and exact identity rejection. H/I/J/K/L/N use child-race, topology, readiness,
explicit abort, controller-death and target-death cases. Overlapping test runs must
not be summed as independent cases. Final TRX/JSON inventory supplies exact counts.

Current-input captures bind 507 selected files plus service/task identities and
strict static-directory membership. The native read-only dress selects the actual
installed inputs without changing the stopped Automation service. A separate
copied-state rehearsal preserves the exact epoch and tests 08:34/08:35/08:39/
08:40-inclusive/08:41/failure with restart and duplicate prevention. Its executor,
runtime-gate result and Engine Host probe are explicit harmless doubles, not market
or physical release-acceptance evidence.

Physical host qualification so far uses the actual built service executable in
the existing interactive user session, not a newly installed Session-0 SCM service.
The production adapter requires actual Session 0 and fails closed on a mismatch.
Actual installed adoption/start/readiness remain Integration-owned and are not
claimed by this Engine package.

## Protected State And Next Gate

No canonical/master advancement, production retry, provider request, production
service/task/config/state mutation, Opening/Continuous/Observer change, or Paper/
execution authority is authorized here. Disposable files/processes and task branch
build outputs are separate. The SDK's first-use development certificate side
effect is disclosed in the external design record; it is not concealed as global
machine nonmutation. Subsequent builds disable SDK certificate initialization.

Full-suite, package/source/binary equivalence and fresh frozen detect-only Astra
review must all finish before a production-retry-ready handoff. This source report
does not itself assert those unfinished gates or authorize integration.
