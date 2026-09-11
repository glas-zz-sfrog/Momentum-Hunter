# Writer Liveness Policy 005

Status: IMPLEMENTED_PENDING_MERGE; Engine branch only, no integration authority.

## Task Charter And Registry

- LANE: OPENING_ENGINE
- TASK_ID: ARGUS-CONTINUOUS-WRITER-LIVENESS-POLICY-005
- BASE_CANONICAL_SHA: a5dfbccbb3a77a78bb80412d30f06e610ccecd43 (observed production; not imported)
- TASK_BASE_HEAD / OPENING_HEAD: 462ba2f2d7e0df9eb1eb42bd16f1de152d16d418
- TASK_BASE_TREE / OPENING_TREE: 023f7e0d46eaff503b8f9eb9e9cb75d1654a43ab
- BRANCH: codex/ARGUS-CONTINUOUS-WRITER-LIVENESS-POLICY-005
- WORKTREE: C:/Users/steve/AppData/Local/MomentumHunter/worktrees/LANE-OPENING-ENGINE
- OWNED_PATHS: continuous writer/client/runtime liveness code, their focused tests, this report, task proof tooling
- PROTECTED_PATHS: canonical; frozen composite; Science six files; GUI; installed state; services; schedulers; providers/auth; strategy; execution
- ALLOWED_CAPABILITIES: offline local/disposable tests, read-only protected-state checks, branch commit/push, review packaging
- PROHIBITED_CAPABILITIES: providers, broker/account/positions/orders, production writes, tracing, reboot, activation, integration
- EVIDENCE_ROOT: F:/ArgusQualification/Engine/ARGUS-CONTINUOUS-WRITER-LIVENESS-POLICY-005-20260910
- TEMP_RUNTIME_ROOT: disposable TEMP children only
- PACKAGE_ROOT: task evidence root / packages
- PACKAGE_GATE: sanitized self-contained frozen second-eye packet
- SECOND_EYE_GATE: fresh independent Astra against final frozen bytes
- MERGE_GATE: separate Integration authorization; NO MERGE in this task

## Policy Contract

The 0.500-second threshold is a fixed health signal. The former local client
threshold (default 1 second, scale 0.5, live qualification 2) returned SLOW even
after successful persistence. It was a mixed performance/qualification/liveness
gate, not a durability requirement. The compatibility argument remains readable
as a legacy diagnostic budget; it cannot override the fixed health threshold or
turn a verified durable acknowledgement into failure.

Successful ACKs are reconciled against their exact immutable ACK/record before
resolving the pending intent. Missing, contradictory or corrupt evidence cannot
be accepted on latency grounds. Legacy SLOW results without a verified ACK remain
uncertain writes subject to retry and liveness protection.

Use the existing bounded evidence queue and a writer-specific horizon of two
configured broad-discovery cadences plus configured housekeeping. This is bound
to the immutable fingerprinted runtime configuration, not changing per-tick
scheduling hints (default 300+300+30 = 630 seconds; configured 60+60+30 = 150).
The separate pipeline watchdog retains its existing resolved-cadence behavior.
No separate queue or arbitrary new timeout. A complete writer horizon with
no successful writer progress fails closed. A full horizon with aged pending
evidence, no net queue reduction, and arrivals at least equal to successful
drains is sustained backpressure and fails closed. Approaching the existing
capacity (one free slot or less) warns immediately; capacity rejection remains
explicit. Repeated rejected arrivals spanning the same horizon fail even when a
moving head is young or burst drains briefly empty the queue. Rejection history
rolls to a new episode only when a new recorded rejection follows a full quiet
horizon. Completion/empty-queue observations cannot erase the rejection anchors
or reinterpret earlier admission timestamps. Dormant anchors alone do not fail
an otherwise healthy empty queue. Admitted
and offered rates are separate. Progressing catch-up is not failed merely for
one latency sample.

Health retains latency counts, bounded recent samples, consecutive slow ACKs,
queue peak/age, arrivals/drains, and recovery duration. Checkpoints retain writer
monitor state so restart does not erase a pending head's liveness history.
Restoration rejects missing/invalid monitor fields, contradictory terminal state,
queue/count mismatch, and future observation clocks. A legacy absent monitor
starts from the original pending request time; new terminal flags cannot use
that legacy path. Correctness and liveness terminal categories remain distinct.
Rejection anchors are cross-checked against retained fingerprinted rejected-
admission decisions, including connected earlier observations. Clearing or
advancing an anchor contrary to those records fails restore. Missing diagnostic
history is not invented; a legacy monitor uses only the retained suffix and
those counters are a lower bound, not reconstructed lifetime statistics.
The production host publishes FAILED and exits nonzero on terminal writer failure;
restart restores the hold, it does not regain admission authority.

The new read-only receipt primitive validates the actual opened Windows handle
(regular file, one link, exact final path) under existing pinned parent handles
before reading any bytes. It reads both exact ACK bytes and the record hash.
A bounded pair of already-flushed handles (one record plus ACK) remains open for
immediate readback. A metadata-only canonical-path open must still match the
retained file identity; deletion, replacement, aliases and corruption fail.
Old/reopened receipts use the full secure-read fallback. Eviction/close releases
every retained handle. This changes post-commit handle cleanup, not WriteFile,
FlushFileBuffers, hard-link commit, record/ACK encoding, replay or owner locking.
Reads do not establish power-loss survival. The added full data-open cost caused
an observed scale regression; handle reuse is a bounded synchronous optimization,
not a payload cache or another queue. No budget was increased.

Development V1 was NOT ACCEPTED: it exceeded the unchanged scale write budget,
and preliminary independent Astra found sustained-capacity and malformed-restore
gaps. Those receipts/reproductions remain preserved externally. The revised
candidate requires new qualification and independent review, not relabeling V1.

This is logical bounded detection between synchronous I/O calls, not preemption
of a hung Windows FlushFileBuffers. The production socket's existing five-second
operation timeout remains; this task does not claim a new OS kill/watchdog or
power-loss guarantee.

## Acceptance

Directive matrix A-S, one 1.044-second durable ACK followed by single-digit-ms
writes, bounded persistent failure, physical 4,300-record correctness/throughput,
production-class equivalence, full suite, F1/V2 reconciliation, protected-state
nonmutation and independent Astra are required before branch closeout.

## Final Frozen-Source Qualification

Executable/test freeze: candidate-v13; 1,110 exact source entries; source manifest
SHA-256 CFBD35FE1608DFE232E96F21AA706CF2964BC08C2FEEE354C89D9AAFD5491DC3.
Only this unique report changed after that source freeze. Final commit/tree,
remote proof, advisory acceptance and package custody are recorded externally;
they must not be inferred from this in-commit report alone.

- Full discovery: PASS, 3,235 tests, 1,130.783 seconds, all 238 modules reconciled.
- One expected Windows symlink-privilege skip; zero failures/errors. Separate
  physical writer reparse/alias tests executed successfully.
- Focused writer/native/runtime checks: 64 PASS. Disposable frozen-composite
  F1/V2 regression: 125 PASS; reconciliation has no content conflicts.
- Compileall, source-byte custody, bounded secret scan and static commit/flush
  preservation checks: PASS. No PowerShell or C# source changed.
- 4,300-record write: 40.6942785 / 120 seconds; reopen: 70.9629014 / 120 seconds.
- Actual ACK health: two >500ms, both >1s, maximum 1.3269346 seconds; p50 8.359ms,
  p95 9.3503ms, p99 10.2921ms. Tail latency remains WARNING, not hidden.
- Measured-service-time queue model: peak 86, oldest maximum age 2.374315s,
  complete spike-to-baseline recovery 3.471794s; successful drain 110.775676/s
  versus declared arrivals 35.833333/s. This is not installed production load.
- Fresh Astra source and external-helper reviews have zero unresolved material
  findings; final advisory acceptance additionally requires exact Git binding
  and protected/primary-custody receipts. Original findings remain preserved.

Earlier full V2 failed its native fixture and unchanged write budget. V7 and V11
full PASS results do not qualify later bytes. Review found and closed sustained
capacity, restore-history, mixed-clock and cadence/restart defects. Final V13
alone supplies the final full-suite result; no timeout was raised or failure
relabelled. All prior receipts remain in the external evidence root.

The running Automation Service naturally advances its state and recovery
admission-head receipts. The precommit static classifier's false result is
preserved; a separate read-only proof verifies admitted generation hashes,
heartbeat/version progression and stable source/service/jobs/claims. Final
configuration comparison excludes only these two exact mutable receipt paths,
retains their observed hashes, and does not claim a frozen host history.

No Science, GUI, canonical, installed configuration, service, scheduler, provider,
authentication, Paper, Shadow or execution change was performed. No canonical
merge is authorized. Integration owns the next combined foundation qualification;
production installation/activation and any power-loss proof remain separate.
