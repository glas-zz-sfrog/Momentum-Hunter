# CEO Console

## Steven's Role
Steven is CEO, product owner, priority setter, and final merge approver. Steven decides what matters, what ships, and when work is accepted into `master` or `main`.

## ChatGPT's Role
ChatGPT acts as CEO Advisor, Chief of Staff, task architect, and reviewer. ChatGPT helps shape requests, clarify acceptance criteria, review outputs, and reduce Steven's project-management load.

## Current Phase
Argus Office v0.1 setup.

## Current Rule
No application code changes during this migration. This scaffold is governance, configuration, and documentation only.

## Operating Model
Many agents may analyze. Builder implements only approved scoped tasks. QA may write tests only when explicitly assigned. Release Scribe updates logs, reports, and checklists. Codex Orchestrator is the single Codex-side front door. Steven approves merges.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next Recommended Action
Ask ChatGPT to convert the highest-priority CEO concern into a single commandbus task using `templates/CEO_REQUEST_TEMPLATE.md`, then have Codex Orchestrator assign Code Mapper for read-only discovery before any implementation.
