# Branch Policy

## Default
Use task branches. Keep each task small, scoped, and reversible.

## Merge Authority
Verified nonvisual work may fast-forward into local `master` under standing delegation. Visual/UI work waits for Steven's manual acceptance. If fast-forward is not possible, Git Steward stops and asks Steven how to handle the divergence.

## Push Authority
Git Steward may perform a non-force backup push after verified nonvisual work is integrated and the worktree, protected-path review, and secret scan are clean. Visual/UI work pushes only after manual acceptance. Any remote divergence, force requirement, unexpected commit, or secret risk interrupts Steven.

## Git Steward Duties
Git Steward owns branch safety. Before implementation or merge, Git Steward confirms current branch, branch base, worktree clean/dirty state, ahead/behind versus `origin/master`, and allowed changed paths. Git Steward creates task branches from current local `master` and creates safety branches before risky repair operations.

## Dangerous Operations
No reset, rebase, branch deletion, force-push, non-fast-forward merge, or branch-history rewrite may occur without a concrete Steven decision and a safety branch at the pre-operation HEAD.

## Review Baseline
Compare final changes against the current local branch state. Do not assume `origin/master` is the correct comparison point when local `master` may be ahead of remote.

## Commit Shape
Prefer one focused commit per scoped task after acceptance criteria pass.

## Protected Areas
Protected areas require exact task scope and Hard Chew proof. Do not ask again when the current task or Roadmap already authorizes the bounded change. Interrupt Steven before semantic expansion, destructive migration, secret exposure/revocation, or real broker execution.
