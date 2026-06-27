# Operating Rules

## Intake
CEO requests start in `commandbus/inbox/` using `templates/CEO_REQUEST_TEMPLATE.md`.

## Triage
Codex Orchestrator reviews the request, confirms scope, identifies protected-area risk, and assigns read-only mapping or review when needed.

## Implementation
Builder implements only approved scoped changes. Builder must report files changed, tests run, risks, and manual QA.

## Review
Specialists may analyze and recommend. QA may write tests only when explicitly assigned. Release Scribe updates logs, reports, and checklists but does not approve merges.

## Output
Codex Orchestrator produces one consolidated CEO report. Steven decides whether the work is accepted.

## Stop Conditions
Stop when requirements are ambiguous, when protected areas are touched without explicit approval, when unrelated files change, or when a push or merge would be required.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
