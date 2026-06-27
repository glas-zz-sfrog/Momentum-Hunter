# Current State

## Phase
Argus Office v0.1 discovery.

## Branch
`codex/ARGUS-0000-office-scaffold`

## State Summary
The office scaffold is in place and ARGUS-0001 produced a read-only Momentum Hunter discovery report. The current recommended next decision is whether to approve ARGUS-0002 as a small Builder task to restore a visible Daily Checklist path in the operator workflow.

## Active Rule
No application source code, tests, package files, database files, generated data, UI components, scoring logic, replay logic, runtime behavior, or production configs were changed during ARGUS-0001. Future work remains recommendation-only until Steven approves a scoped task.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Create an ARGUS-0002 CEO request for the first approved Builder task, likely restoring Daily Checklist visibility, or decide that stale active-monitor/evidence refresh should come first.
