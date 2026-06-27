# Security Review Template

## Scope

## Findings
| Severity | Risk | Evidence | Recommendation |
| --- | --- | --- | --- |

## Review Prompts
- Are secrets or API keys exposed?
- Is environment handling safe?
- Is unsafe logging present?
- Are dependency risks introduced?
- Are file writes constrained?
- Could future broker/order execution be affected?

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
