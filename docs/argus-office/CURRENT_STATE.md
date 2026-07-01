# Current State

## Phase
ARGUS-A014/A015C Simulation Cockpit and Auditor Gate Hardening.

## Branch
`codex/ARGUS-A006-A015-argus-machine-simulation`

## State Summary
Argus Machine now has a simulation-only cockpit that separates FakeBroker orders, simulated positions, and ledger-backed fills/events. The console displays an Execution Auditor paper advancement gate with `PASS`, `WARN`, or `BLOCK` status tied to selected TradePlan, RiskResult, Ledger, and FakeBroker evidence. Paper and live controls remain locked; no paper broker, live broker, credentials, API keys, schema changes, or runtime market-data changes were added.

## Active Rule
Steven remains final merge approver. Master must not be pushed. This branch remains simulation-only. Scoring, readiness, replay identity, storage/schema, alert thresholds, package/dependency files, generated data, market-data/report outputs, paper broker code, live broker code, credentials, and real broker/order behavior remain protected.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should manually QA the Argus Machine simulation cockpit and auditor gate. If accepted, Git Steward can prepare a local merge path for the simulation foundation; paper broker work should remain deferred until a separate approved paper-track task.
