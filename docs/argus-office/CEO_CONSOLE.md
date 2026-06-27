# CEO Console

## Steven's Role
Steven is CEO, product owner, priority setter, and final merge approver. Steven decides what matters, what ships, and when work is accepted into `master` or `main`.

## ChatGPT's Role
ChatGPT acts as CEO Advisor, Chief of Staff, task architect, and reviewer. ChatGPT helps shape requests, clarify acceptance criteria, review outputs, and reduce Steven's project-management load.

## Current Phase
Argus Office v0.1 Git Steward installation.

## Current Rule
No application code changes during this migration. ARGUS-0005 is governance, configuration, and documentation only.

## Operating Model
Steven talks to ChatGPT, ChatGPT writes the task prompt, Git Steward prepares or verifies the branch, Codex Orchestrator coordinates specialists, Builder implements only approved scoped tasks, QA verifies, Release Scribe documents, and Git Steward performs local fast-forward merges only after Steven approval. Nothing pushes unless Steven explicitly approves.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next Recommended Action
Use Git Steward for branch preflight before the next implementation task. Continue to require Steven approval before any merge or push.
