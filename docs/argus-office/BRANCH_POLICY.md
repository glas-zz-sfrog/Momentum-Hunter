# Branch Policy

## Default
Use task branches. Keep each task small, scoped, and reversible.

## Merge Authority
Steven is the final merge approver. Git Steward may perform a local fast-forward merge to `master` only after Steven explicitly approves that merge. If fast-forward is not possible, Git Steward stops and reports.

## Push Authority
No agent pushes without explicit Steven approval. Git Steward must report whether anything was pushed.

## Git Steward Duties
Git Steward owns branch safety. Before implementation or merge, Git Steward confirms current branch, branch base, worktree clean/dirty state, ahead/behind versus `origin/master`, and allowed changed paths. Git Steward creates task branches from current local `master` and creates safety branches before risky repair operations.

## Dangerous Operations
No reset, rebase, branch deletion, force-push, non-fast-forward merge, or branch-history rewrite may occur without explicit written approval from Steven and a safety branch at the pre-operation HEAD.

## Review Baseline
Compare final changes against the current local branch state. Do not assume `origin/master` is the correct comparison point when local `master` may be ahead of remote.

## Commit Shape
Prefer one focused commit per approved task after acceptance criteria pass.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
