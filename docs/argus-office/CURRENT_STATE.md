# Current State

## Phase
Argus Office v0.1 setup.

## Branch
`codex/ARGUS-0000-office-scaffold`

## State Summary
The office scaffold defines roles, authority, branch rules, protected areas, task flow, review templates, and release documentation support. This migration does not alter application behavior.

## Active Rule
No application source code, tests, package files, database files, generated data, UI components, scoring logic, replay logic, runtime behavior, or production configs may be changed during this scaffold migration.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Create the first CEO request, place it in `commandbus/inbox/`, and have Argus Orchestrator produce a scoped assignment plan.
