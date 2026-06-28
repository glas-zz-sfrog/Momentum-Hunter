# Current State

## Phase
ARGUS-A002/A003 Gateway Shell + Argus Machine Console Skeleton.

## Branch
`codex/ARGUS-A002-A003-gateway-machine-console-skeleton`

## State Summary
ARGUS-A000 was fast-forward merged into local `master`. ARGUS-A002/A003 implements the first visible two-door product split: Steven Desk opens the existing human-guided dashboard path, and Argus Machine opens a safe display-only autonomous console shell.

## Active Rule
Steven remains final merge approver. Master must not be pushed. This implementation may change only the minimal UI files, focused tests, and Argus Office release docs required for the gateway and console shell. Broker/order behavior, scoring, readiness, replay, alert thresholds, database/schema files, package/dependency files, generated data, market data/report outputs, live broker code, external API integrations, and runtime market data behavior remain protected.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should manually QA the gateway and Argus Machine shell, then decide whether the next implementation should define the TradePlan object/model or the first display-only Risk Governor gates.
