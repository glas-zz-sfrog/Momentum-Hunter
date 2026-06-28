# Current State

## Phase
ARGUS-R001 App.py Responsibility Map and Extraction Targets.

## Branch
`codex/ARGUS-R001-app-py-responsibility-map`

## State Summary
ARGUS-R000 was fast-forward merged into local `master`. ARGUS-R001 maps the 7,188-line `momentum_hunter/app.py` by responsibility, ranks extraction targets, and recommends Gateway / Argus Machine UI as the first safe implementation extraction.

## Active Rule
Steven remains final merge approver. Master must not be pushed. This task is docs/analysis only and may change only the requested Argus Office architecture/report/log/changelog files. Production app code, tests, package files, database/schema files, generated data, scoring, readiness, replay, broker/order behavior, execution behavior, and runtime behavior remain protected.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should review the R001 map and approve whether R002 should extract Gateway / Argus Machine UI into a dedicated PySide module.
