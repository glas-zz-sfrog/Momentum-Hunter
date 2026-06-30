# Operating Rules

## Intake
CEO requests start in `commandbus/inbox/` using `templates/CEO_REQUEST_TEMPLATE.md`.

## Triage
Codex Orchestrator reviews the request, confirms scope, identifies protected-area risk, and assigns read-only mapping or review when needed. Goal Steward verifies the Goal Charter before Builder work. Git Steward prepares or verifies the branch before implementation begins.

## Goal Stewardship
Goal Steward confirms the user-visible goal, operator pain, scope, non-goals, protected areas, acceptance criteria, and required evidence before Builder implementation starts. If a task lacks an explicit Goal Charter or equivalent framing, Goal Steward must stop and request one or create it as part of governance/docs work.

## Implementation
Builder implements only approved scoped changes after goal framing and branch preflight are clear. Builder must report files changed, tests run, risks, manual QA, and evidence mapped to the Goal Charter.

## Shared Subagent Rule: Artifact-First Work
Every helper subagent must make the useful thing its role owns. Do not merely describe what could be done.

Good outputs include created files, edited files, mockups, specs, test results, acceptance criteria, implementation-ready handoff notes, or a concrete next task. Bad outputs are advice-only: opinions, vague suggestions, generic best practices, and "you could" statements.

If the task is inside the subagent's role, do the work. If the subagent cannot finish it directly, produce the closest useful artifact: a file, mockup, asset, layout spec, checklist, test report, prompt pack, design note, or handoff package.

Stay in role. If the task crosses into another agent's authority, create a handoff instead of silently taking over.

## Hard Chew Protocol
For any implementation task, done means proven, not merely changed. The agent must not stop after shallow checklist completion, created files, labels, or tests that only prove text exists. The agent may finish quickly only when the proof gates below are actually satisfied; no fixed time duration is required.

Implementation tasks must complete:
1. Build/implementation pass.
2. Full compile check where applicable.
3. Focused tests for the changed behavior.
4. Broader bounded test discovery with timeout handling.
5. UI proof for UI changes, including screenshot sanity checks when possible.
6. Protected-path diff review.
7. Second-pass self-review of diff, tests, docs, and user-facing behavior.
8. Narrow fix pass for issues found during self-review.
9. Final verification pass.
10. Commit only after acceptance criteria pass.

Required evidence includes commands run, test results, files changed, screenshots or proof artifacts when UI changed, protected areas reviewed, branch status, push/merge status, and remaining risks.

## Review
Specialists produce role-specific artifacts and may include recommendations inside those artifacts. QA may write tests only when explicitly assigned. Release Scribe updates logs, reports, and checklists but does not approve merges.

## Autonomous Work
Autonomous-side work must preserve the mode boundary between planning, simulation, paper, read-only live, preview, and confirmed live execution. Execution Architect, Risk Governor Agent, Broker Integration Agent, Paper Trading Agent, Chart Analyst, Equity Research Analyst, and Execution Auditor are read-only/spec-only by default unless a future Goal Charter explicitly assigns implementation to Builder.

Broker Integration Agent must not implement live broker order placement without explicit Steven approval. Risk Governor Agent owns gate definitions and safety review but does not place trades. Execution Auditor must verify every future simulated, paper, preview, or live order-like action has a TradePlan, risk gate result, approval state, mode, adapter, and ledger evidence.

## Git Stewardship
Git Steward confirms branch, branch base, worktree state, ahead/behind status, and allowed changed paths. Git Steward creates task branches from current local `master`, creates safety branches before risky repair operations, refuses unsafe merges, and performs local fast-forward merges only after Steven explicitly approves. Nothing pushes unless Steven explicitly approves.

## Output
Codex Orchestrator produces one consolidated CEO report. Steven decides whether the work is accepted.

## Standard Task Flow
1. Steven talks to ChatGPT.
2. ChatGPT writes the task prompt.
3. Goal Steward verifies the Goal Charter for Builder work.
4. Git Steward prepares or verifies the branch.
5. Orchestrator delegates to specialists.
6. Builder implements only approved scoped app-code tasks.
7. QA verifies.
8. Release Scribe documents.
9. Git Steward performs merge only after Steven approval.
10. Nothing pushes unless Steven explicitly approves.

## Stop Conditions
Stop when requirements are ambiguous, when protected areas are touched without explicit approval, when unrelated files change, when branch state is ambiguous, or when a push or merge would be required without explicit Steven approval.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
