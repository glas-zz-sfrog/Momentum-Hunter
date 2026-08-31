# Parallel Workstream Governance

## Authority

This contract governs Momentum Hunter parallel development. The machine-readable
registry is `PARALLEL_WORKSTREAM_LANES.json`. The Roadmap remains authoritative
for current priority and next work. If these records disagree, stop before
implementation and reconcile them through the Integration Steward.

Established invariants:

```text
MASTER = ACCEPTED INTEGRATION ONLY
MASTER_INTEGRATION_ONLY = YES
PRODUCTION_CHECKOUT_PERMANENTLY_ON_MASTER = YES
REVIEWED_HEAD_IMMUTABLE = YES
OBSERVER-AUTHORIZED-RELEASE-BINDING-001 = DEFERRED_NOT_IMPLEMENTED
```

## Canonical And Worktree Model

The production checkout is permanently on `master`. It is an accepted integration
trunk, not a development or test lane. Product work occurs only on a short-lived
task branch in one of three persistent AppData worktrees:

| Lane | Persistent worktree | Purpose |
| --- | --- | --- |
| `SCIENCE` | `C:\Users\steve\AppData\Local\MomentumHunter\worktrees\LANE-SCIENCE` | Statistics, replay, evidence corpora, outcomes, and anti-hindsight research |
| `OPENING_ENGINE` | `C:\Users\steve\AppData\Local\MomentumHunter\worktrees\LANE-OPENING-ENGINE` | Opening/runtime identity, providers, environment qualification, and engine infrastructure |
| `GUI` | `C:\Users\steve\AppData\Local\MomentumHunter\worktrees\LANE-GUI` | WPF, Command Center, read models, layouts, charts, and operator presentation |

An idle lane is detached at accepted canonical. A task receives a new `codex/`
branch and records an immutable `BASE_CANONICAL_SHA`. Completing a task does not
turn that branch into a permanent lane branch. A later task begins from the newest
accepted canonical after the lane returns to clean detached idle state.

## Task Admission

Before implementation, the task record must contain every field listed by
`ACTIVE_TASK_RECORD_CONTRACT.REQUIRED_FIELDS` in the registry. `OWNED_PATHS` and
`PROTECTED_PATHS` are exact task declarations; lane defaults are boundaries, not
permission to edit every file in a category.

The start report must establish:

```text
LANE
TASK_ID
BASE_CANONICAL_SHA
BRANCH
WORKTREE
MASTER_CLEAN
MASTER_LOCAL_ORIGIN_SYNC
LANE_WORKTREE_CLEAN
OWNED_PATHS_DECLARED
PROTECTED_PATHS_DECLARED
SHARED_RUNTIME_MUTATION_AUTHORIZED
SERVICE_MUTATION_AUTHORIZED
SCHEDULER_MUTATION_AUTHORIZED
CROSS_LANE_DEPENDENCY
SAFE_TO_IMPLEMENT_IN_PARALLEL
```

Unless a directive explicitly says otherwise, shared runtime, service, scheduler,
approved-environment, provider-authentication, Paper, Shadow, broker, account,
position, and order mutation are prohibited.

## Ownership And Shared Contracts

Each lane owns only the exact paths declared by its active task. Every task runs
an owned-path and protected-path diff at admission and closeout. A protected-path
change stops the task.

No lane independently owns a DTO, persistence schema, provider contract, runtime
API, or identity semantic shared with another lane. If such a change is required,
set `CROSS_LANE_CONTRACT_CHANGE_REQUIRED = YES`, stop that portion, and create a
separate serialized contract task from accepted canonical. That task identifies
and tests every affected lane before integration.

## Frozen Bases And Reviewed Heads

An active task keeps its original base while another lane advances `master`.
Do not rebase it, merge newer `master`, or pull another lane into it. Reconciliation
belongs to integration.

Once a review package is sealed or a head is formally frozen, that head is
immutable. Do not amend, rebase, rewrite, force-push, or append executable, test,
tool, or runtime bytes. A later executable change creates a new candidate and, when
the task class requires it, a new package and second-eye review.

## External-State Isolation

Git isolation is necessary but insufficient. Every task receives unique evidence,
temporary runtime, and package roots derived from its lane, task ID, and frozen
head. Checkpoints, package staging, build outputs, writer ownership, and scheduler
identities must also be task namespaced. Cross-lane reuse is read-only and must be
declared.

No lane mutates the shared approved Python environment. A dependency change stops
the lane and becomes a separate serialized environment-qualification task. No
lane restarts, reinstalls, repoints, or mutates a production service or live
scheduler unless its directive explicitly grants that authority.

## Package Gates

- `SCIENCE`: a new autonomous/statistical natural-runtime claim requires a
  sanitized second-eye ZIP.
- `OPENING_ENGINE`: a new executable/runtime/environment identity or natural-
  runtime claim requires a sanitized second-eye ZIP.
- `GUI`: screenshots and Steven's precise manual visual acceptance normally
  suffice; a ZIP is required only when explicitly directed.
- Governance-only worktree setup requires no ZIP when executable, test, tool,
  and runtime bytes are unchanged.
- Exact conflict-free integration of already reviewed bytes requires no new ZIP.
  Executable, test, or tool conflict resolution requires new review.

## Serialized Integration Train

Parallel implementation is allowed; parallel integration is not. MH - Engines,
acting as Integration Steward, admits one accepted lane at a time:

1. Verify current `master` clean and synchronized.
2. Verify the exact accepted source head and second-eye decision when required.
3. Create a disposable integration worktree from current `master`.
4. Integrate the exact accepted lineage without changing its reviewed bytes.
5. Classify all conflicts. Any executable, test, or tool conflict stops the train.
6. Run equivalence checks and the applicable Hard Chew.
7. Advance local `master` and `origin/master` only after every gate passes.
8. Return the lane to clean detached idle state at the new accepted canonical.

Builders cannot merge their own work. `ROADMAP.md`, `BRANCH_LEDGER.md`, and
`TASK_LOG.md` are Integration-Steward-owned by default; builders use unique task
reports and external evidence unless an explicit exception is declared.

## Task Closeout

Every task returns:

```text
LANE
TASK_ID
BASE_CANONICAL_SHA
FINAL_HEAD
OWNED_PATH_DIFF
PROTECTED_PATH_DIFF
CROSS_LANE_SEMANTICS_CHANGED
MASTER_CHANGED_BY_BUILDER
PRODUCTION_CHECKOUT_CHANGED
SERVICE_STATE_CHANGED
SCHEDULER_STATE_CHANGED
PACKAGE_REQUIRED
PACKAGE_STATUS
SECOND_EYE_STATUS
READY_FOR_INTEGRATION
BUILDER_MERGE_AUTHORIZED = NO
```

The Integration Steward updates shared governance only after accepted integration.
