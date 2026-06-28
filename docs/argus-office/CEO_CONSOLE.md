# CEO Console

## Steven's Role
Steven is CEO, product owner, priority setter, and final merge approver. Steven decides what matters, what ships, and when work is accepted into `master` or `main`.

## ChatGPT's Role
ChatGPT acts as CEO Advisor, Chief of Staff, task architect, and reviewer. ChatGPT helps shape requests, clarify acceptance criteria, review outputs, and reduce Steven's project-management load.

## Current Phase
ARGUS-A000 autonomous platform foundation.

## Current Rule
ARGUS-A000 is docs/config/planning only. It may define the autonomous roadmap and agent roles, but it must not change app code, tests, packages, database/schema files, generated data, broker/order behavior, or runtime behavior.

## Operating Model
Steven talks to ChatGPT, ChatGPT writes the task prompt, Goal Steward verifies the Goal Charter, Git Steward prepares or verifies the branch, Codex Orchestrator coordinates specialists, Builder implements only approved scoped tasks, QA verifies, Release Scribe documents, and Git Steward performs local fast-forward merges only after Steven approval. Nothing pushes unless Steven explicitly approves.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next Recommended Action
Review ARGUS-A000, then run ARGUS-A001 as a docs-only product spec review before Builder starts ARGUS-A002 Gateway Shell.
