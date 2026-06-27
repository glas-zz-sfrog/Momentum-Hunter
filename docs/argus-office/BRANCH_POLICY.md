# Branch Policy

## Default
Use task branches. Keep each task small, scoped, and reversible.

## Merge Authority
Steven is the final merge approver. No agent merges to `master` or `main`.

## Push Authority
No agent pushes without explicit approval.

## Review Baseline
Compare final changes against the current local branch state. Do not assume `origin/master` is the correct comparison point when local `master` may be ahead of remote.

## Commit Shape
Prefer one focused commit per approved task after acceptance criteria pass.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
