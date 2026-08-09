# ARGUS-ROADMAP-003 Parallel Pipeline Roadmap Refactor

## Classification

`PARALLEL_PIPELINE_ROADMAP_READY`

## Reconciled Baseline

- Canonical `master` and `origin/master`: `1d0ca95`, clean and synchronized.
- Installed service: Running/Automatic from canonical checkout.
- Installed manifest: SHA-256
  `E99E65A302B97A5D866071C3C1B37C8519972F8D55966EAC08772A1F6F093B47`.
- Engine Host: Healthy at inspection.
- Opening jobs: 25 enabled/pending, all pinned to `1d0ca95`.
- Shadow jobs: zero enabled; order transmission `UNAVAILABLE`.
- Worktrees: 69 total, 47 clean, 22 dirty; none altered or removed.

## Structural Defects Corrected

1. The old Roadmap used an approximately 860-line `Now` narrative as history,
   hiding actual work selection.
2. Sequential phase language made narrow waits appear to stop the project.
3. Validated unmerged work was mixed with incomplete work.
4. A003 market-hours proof was not separated cleanly from provider-neutral
   allocation, evidence, and offline tooling.
5. No mechanical Ready Queue, Integration Queue, gate scope, or dependency
   graph existed.
6. Worktree concurrency and current-master reconciliation rules were too
   implicit for the observed branch volume.

## New Scheduler

The Roadmap now provides:

- Authority and operating rules.
- Concise Executive Now.
- Seven-milestone board.
- Multi-task Ready Queue.
- Nine durable workstream lanes.
- Scoped Waiting/Gated Queue.
- Evidence-backed Integration Queue.
- Gate Register.
- Directed dependency graph.
- One-record-per-task active inventory.
- Compressed completed-capability summary.
- Scheduling, task-record, branch, priority, and update protocols.

## Key Truth Reconciliation

- A003 harness `7ccbad5` and head `1abb4dd` are not competing identities.
  `1abb4dd` contains `7ccbad5` plus adjudication `94c7c77` and is the exact
  source for the eventual direct proof.
- A003 live acceptance is `WAITING_EXTERNAL_TIME`; project development is
  `ACTIVE`.
- DATA-005B provider-neutral allocation is validated at `046b127`; its separate
  seven-file dirty activation worktree is preserved and gated.
- MONITOR `d2b77c2`, REGIME `f4deb18`, and EVENT `b6e861a` are validated,
  pushed, dormant, and unmerged.
- ROADMAP-002 `bae053b` is validated but divergent; it requires a fresh current-
  master reconciliation rather than rebase or direct merge.
- The 25 scheduled-job pins scope-block canonical integration/installation, not
  isolated feature development.

## Safety Result

No application, tests, package, database/schema, generated data, scoring,
readiness, TradePlan, Risk Governor, provider, account, credential, broker,
order, service, scheduler, Engine Host, Shadow, WPF, or production runtime file
was changed. No provider or account call occurred. No Paper or live order was
submitted. No worktree or branch history was changed beyond creation of the
isolated task branch/worktree.

## Verification

- Twelve required top-level sections are present in directive order.
- Seven milestone records each contain required, satisfied, unsatisfied, and
  critical-path evidence.
- Five Ready tasks, eighteen Waiting tasks, and one task being closed out map
  to twenty-four unique unfinished-task records with exactly one primary lane.
- Every Waiting row has a supported classification plus nonempty gate, scope,
  Blocks, Does NOT block, resume, and While Waiting fields.
- Ready/Waiting queues mechanically agree with the active inventory.
- The dependency graph contains one Mermaid graph with twenty-five directed
  edges; all twelve changed Markdown files have zero missing local references.
- Current branch ancestry, A003 `7ccbad5`/`1abb4dd`, cumulative Alpaca/DATA
  lineage, MONITOR/REGIME/EVENT order, and ROADMAP-002 divergence all match the
  Integration Queue.
- Contradiction scan found and removed the stale market-hours global-block
  alias. Refined credential-pattern scan has zero hits.
- `git diff --check` passes. All twelve changed paths are governance Markdown:
  zero application, test, package, schema, generated-data, or runtime files.
- Canonical `master` remains clean and synchronized at `1d0ca95`; the service
  remains Running/Automatic and the installed manifest hash remains
  `E99E65A302B97A5D866071C3C1B37C8519972F8D55966EAC08772A1F6F093B47`.

No application regression suite is required because no runtime file changed.

## Commit And Integration State

- Implementation commit: `b74f72a Refactor roadmap for parallel pipeline execution`.
- The feature branch is the only backup target; canonical `master` is not
  merged or pushed by this task.
- ROADMAP-003 is `IMPLEMENTED_PENDING_MERGE` until one serialized integration
  window reconciles it against current master and the scheduled-runtime pin.
