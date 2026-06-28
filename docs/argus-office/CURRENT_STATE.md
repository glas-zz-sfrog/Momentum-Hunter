# Current State

## Phase
ARGUS-A000 autonomous platform foundation.

## Branch
`codex/ARGUS-A000-autonomous-platform-foundation`

## State Summary
ARGUS-0005 and ARGUS-0005A governance were fast-forward merged into local `master`. ARGUS-A000 creates the autonomous-side foundation for a future two-door product: Steven Desk for human-guided operations and Argus Machine for autonomous planning, simulation, paper trading, broker awareness, and future gated execution.

## Active Rule
Steven remains final merge approver. Master must not be pushed. This task is docs/config/planning only and must not modify app code, tests, packages, database/schema files, generated data, broker/order behavior, or runtime behavior.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should review ARGUS-A000, then approve ARGUS-A001 as a docs-only product spec review before Builder starts the gateway shell.
