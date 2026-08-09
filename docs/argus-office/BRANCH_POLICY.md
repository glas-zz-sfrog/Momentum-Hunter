# Branch Policy

## Default
Use task branches. Keep each task small, scoped, and reversible.

## Parallel Development Budget
Momentum Hunter permits at most three active implementation worktrees by
default. Each active worktree must have a different primary roadmap lane and
must record its base master commit, task ID, protected paths, dependencies, and
integration prerequisites. Use fewer than three when additional worktrees add
collision or reconciliation risk without useful throughput.

Historical checked-out worktrees do not count as active merely because they
exist. They must remain classified in the Branch Ledger and may not be deleted,
reset, stashed, or repurposed without the applicable safety review.

Parallelism is permission, not a quota. A waiting provider, market-hours,
visual, CEO, destructive, or integration gate blocks only its documented
scope. Unrelated Ready Queue work may continue in another lane.

## Merge Authority
Verified nonvisual work may fast-forward into local `master` under standing delegation. Visual/UI work waits for Steven's manual acceptance. If the original feature branch is not fast-forwardable, do not merge it directly. Use the validated-branch reconciliation process below; interrupt Steven only when bounded current-master reconciliation is unsafe, ambiguous, or requires a prohibited Git operation.

There is exactly one canonical integration lane. Only one candidate is
integrated and installed at a time. Scheduled-runtime Git pins may postpone
canonical integration without preventing isolated development or ordinary
feature-branch backup pushes.

## Push Authority
Git Steward may perform a normal non-force feature-branch backup push after verified nonvisual work passes its proof gates, even when integration is waiting. After integration, Git Steward may also back up `master` when its worktree, protected-path review, and secret scan are clean. Visual/UI work pushes only after manual acceptance. Any remote divergence, force requirement, unexpected commit, or secret risk interrupts Steven.

## Git Steward Duties
Git Steward owns branch safety. Before implementation or merge, Git Steward confirms current branch, branch base, worktree clean/dirty state, ahead/behind versus `origin/master`, and allowed changed paths. Git Steward creates task branches from current local `master` and creates safety branches before risky repair operations.

At each task or gate transition, Git Steward reconciles the Roadmap Ready,
Waiting, and Integration Queues with actual branch/worktree state. A clean
validated branch is not automatically merge-ready, and an unmerged branch is
not automatically incomplete.

## Validated Branch Reconciliation
Do not rebase validated remote-backed history. When `master` advances beyond a
validated branch, create a fresh reconciliation branch from current `master`,
apply the exact validated commits when appropriate, record every source commit,
resolve only bounded conflicts, and rerun the complete verification required by
the task. Cherry-pick preserves content ancestry information, not proof; current-
baseline revalidation is mandatory.

## Dangerous Operations
No reset, rebase, branch deletion, force-push, non-fast-forward merge, or branch-history rewrite may occur without a concrete Steven decision and a safety branch at the pre-operation HEAD.

## Review Baseline
Compare final changes against the current local branch state. Do not assume `origin/master` is the correct comparison point when local `master` may be ahead of remote.

## Commit Shape
Prefer one focused commit per scoped task after acceptance criteria pass.

## Protected Areas
Protected areas require exact task scope and Hard Chew proof. Do not ask again when the current task or Roadmap already authorizes the bounded change. Interrupt Steven before semantic expansion, destructive migration, secret exposure/revocation, or real broker execution.
