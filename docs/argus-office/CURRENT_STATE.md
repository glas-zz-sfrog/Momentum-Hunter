# Current State

## Phase
ARGUS-R002 Extract Gateway / Argus Machine UI Into Dedicated PySide Module.

## Branch
`codex/ARGUS-R002-extract-gateway-machine-ui`

## State Summary
ARGUS-R001 was fast-forward merged into local `master`. ARGUS-R002 extracts Gateway and Argus Machine console UI construction into `momentum_hunter/ui/autonomy_gateway.py`, leaving `app.py` as the stack/routing coordinator for that seam while preserving the existing startup gateway, Steven Desk route, display-only Argus Machine console, placeholder Top 5 candidates, Trade Plan Ladder population, and locked order controls.

## Active Rule
Steven remains final merge approver. Master must not be pushed. This task may change only the Gateway / Argus Machine UI extraction files, focused proof artifacts, and release docs. Scoring, readiness, replay identity, storage/schema, broker/order behavior, alert thresholds, package/dependency files, generated data, market-data/report outputs, live broker code, and execution/risk governor model semantics remain protected.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should manually QA the Gateway and Argus Machine console after R002, then decide whether to fast-forward merge R002 locally or adjust the extraction before moving to R003.
