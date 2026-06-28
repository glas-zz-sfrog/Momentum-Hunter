# Current State

## Phase
ARGUS-A004/A005 TradePlan Model and Risk Governor First Gates.

## Branch
`codex/ARGUS-A004-A005-tradeplan-risk-governor`

## State Summary
ARGUS-A002A was fast-forward merged into local `master`. ARGUS-A004/A005 adds the first autonomous planning backbone: a structured `TradePlan` model and pure Risk Governor gate evaluation for complete, incomplete, manual-override, simulation, paper, live-preview, and live modes.

## Active Rule
Steven remains final merge approver. Master must not be pushed. This implementation may change only the new execution/autonomy model area, focused tests, and Argus Office release docs. Broker/order behavior, scoring, readiness, replay, alert thresholds, database/schema files, package/dependency files, generated data, market data/report outputs, live broker code, external API integrations, and runtime market data behavior remain protected.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should review the TradePlan fields and Risk Governor gate names, then decide whether the next task should map Argus Machine placeholder candidates into `TradePlan` objects or refine gate semantics before UI integration.
