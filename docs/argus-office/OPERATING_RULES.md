# Operating Rules

## Intake
CEO requests start in `commandbus/inbox/` using `templates/CEO_REQUEST_TEMPLATE.md`.

## Triage
Codex Orchestrator reviews the request, confirms scope, identifies protected-area risk, and assigns read-only mapping or review when needed. Git Steward prepares or verifies the branch before implementation begins.

## Implementation
Builder implements only approved scoped changes. Builder must report files changed, tests run, risks, and manual QA.

## Review
Specialists may analyze and recommend. QA may write tests only when explicitly assigned. Release Scribe updates logs, reports, and checklists but does not approve merges.

## Git Stewardship
Git Steward confirms branch, branch base, worktree state, ahead/behind status, and allowed changed paths. Git Steward creates task branches from current local `master`, creates safety branches before risky repair operations, refuses unsafe merges, and performs local fast-forward merges only after Steven explicitly approves. Nothing pushes unless Steven explicitly approves.

## Output
Codex Orchestrator produces one consolidated CEO report. Steven decides whether the work is accepted.

## Standard Task Flow
1. Steven talks to ChatGPT.
2. ChatGPT writes the task prompt.
3. Git Steward prepares or verifies the branch.
4. Orchestrator delegates to specialists.
5. Builder implements only approved scoped app-code tasks.
6. QA verifies.
7. Release Scribe documents.
8. Git Steward performs merge only after Steven approval.
9. Nothing pushes unless Steven explicitly approves.

## Stop Conditions
Stop when requirements are ambiguous, when protected areas are touched without explicit approval, when unrelated files change, when branch state is ambiguous, or when a push or merge would be required without explicit Steven approval.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
