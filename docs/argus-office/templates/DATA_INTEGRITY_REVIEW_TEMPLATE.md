# Data Integrity Review Template

## Scope

## Findings
| Severity | Area | Finding | Recommendation |
| --- | --- | --- | --- |

## Review Prompts
- Are replay identity rules preserved?
- Are capture IDs handled correctly?
- Are historical snapshots selected correctly?
- Are candidates linked to outcomes correctly?
- Is stale data visible?
- Are silent fallbacks avoided?

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
