# ARGUS-WORKTREE-HYGIENE-001 Goal Charter - No-Delete Inventory

## Goal Statement

Produce a complete, evidence-backed classification of every registered Momentum
Hunter Git worktree and a staged retirement proposal that reduces ambiguity
without deleting, resetting, stashing, moving, repairing, or pruning anything.

## User Pain / Operator Outcome

Git currently knows dozens of historical worktrees, including clean, dirty,
detached, stacked, superseded, and operationally sensitive checkouts. Steven
needs one trustworthy inventory that distinguishes active work from preserved
history and states exactly which groups could later be retired, which must be
preserved, and which require separate review.

## In Scope

- Inspect all registered worktree paths, branches, HEAD commits, lock/prunable
  metadata, clean/dirty state, ahead/behind relation, and merge containment.
- Identify canonical, installed/operational, active Roadmap, current feature,
  clean historical, dirty historical, detached, missing, and ambiguous groups.
- Record the exact dirty paths without reading or modifying secret values.
- Produce a no-delete inventory report and a staged CEO retirement decision
  plan.
- Update branch/governance evidence and the authoritative scheduler after the
  report is verified.

## Out Of Scope

- No `git worktree remove`, `git worktree prune`, branch deletion, reset, rebase,
  checkout, stash, commit of historical work, file deletion, move, or repair.
- No merge, canonical-master push, service/runtime change, scheduled-job change,
  provider/account/broker call, credential handling, or production-data access.
- No assertion that a clean worktree is safe to retire solely because it is
  clean.
- No automatic retirement approval.

## Protected Areas

Git history, dirty user work, canonical runtime identity, and secrets are
protected. This task is inspection and governance only. Interrupt Steven before
any retirement action, any branch deletion, any operation that would discard or
hide dirty work, or if canonical/installed state is unsafe or contradictory.

## Acceptance Criteria

- Every entry from `git worktree list --porcelain` appears exactly once in the
  inventory.
- Every inventory row includes path, branch/detached state, HEAD, clean/dirty,
  dirty-file count, merged-to-master, remote branch presence, and classification.
- Canonical, operational, current active task, and dirty worktrees are never
  included in an automatic-retirement group.
- Missing/prunable metadata and inaccessible paths are reported honestly.
- The retirement proposal is grouped by consequence and requires a later exact
  Steven approval; this task performs no retirement.
- Canonical `master`, origin identity, installed manifest, and all inspected
  worktrees remain byte/state unchanged except this new docs-only worktree.
- Secret scanning and protected-path review pass.

## Evidence Required

- Canonical branch/status/HEAD/origin identity.
- Raw registered-worktree count and classification totals that sum exactly.
- Per-worktree status and branch-containment evidence.
- Explicit lists for all dirty, detached, missing/prunable, active, and proposed
  retirement groups.
- Hash of the installed service manifest before and after inspection.
- Git diff and secret scans for this task branch.

## Evidence Depth / Hard Chew Requirements

- Collect inventory with machine-readable Git commands rather than parsing
  decorated human output where structured output exists.
- Treat command failure, inaccessible path, malformed porcelain records, and
  branch ambiguity as `NEEDS_REVIEW`, never as safe.
- Cross-check totals independently and prove no registered path is omitted or
  duplicated.
- Review every proposed retirement row for dirty state, current Roadmap use,
  branch containment, remote backup, and operational path collision.
- Perform a second-pass self-review and fix classification/report defects only;
  never fix an inspected worktree.
- Run `git diff --check`, secret scan, protected-path review, and canonical
  nonmutation proof before commit.
- Commit and non-force-push only this docs-only feature branch after proof.

## Smallest Safe Implementation Slice

Create one audit report plus supporting governance entries from read-only Git
evidence. Leave every existing worktree and branch exactly where it is.

## Open CEO Decisions

- Steven must later approve the exact retirement groups before any worktree or
  branch is removed.
- Dirty or ambiguous groups require individual disposition decisions; they may
  not be batch-approved through this report.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove the requested outcome.
- [x] Evidence required is strong enough to verify completion.
