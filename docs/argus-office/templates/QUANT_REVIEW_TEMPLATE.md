# Quant Review Template

## Scope

## Signals or Logic Reviewed

## Findings
| Severity | Assumption | Evidence | Recommendation |
| --- | --- | --- | --- |

## Review Prompts
- What signal assumptions are being made?
- Are scoring and ranking semantics preserved?
- Is trade-readiness logic untouched unless explicitly approved?
- What validation would increase confidence?

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
