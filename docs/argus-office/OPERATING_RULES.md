# Operating Rules

## Intake
CEO requests start in `commandbus/inbox/` using `templates/CEO_REQUEST_TEMPLATE.md`.

## Triage
Codex Orchestrator reviews the request, confirms scope, identifies protected-area risk, and assigns read-only mapping or review when needed. Goal Steward verifies the Goal Charter before Builder work. Git Steward prepares or verifies the branch before implementation begins.

## Goal Stewardship
Goal Steward confirms the user-visible goal, operator pain, scope, non-goals, protected areas, acceptance criteria, and required evidence before Builder implementation starts. If a task lacks an explicit Goal Charter or equivalent framing, Goal Steward must stop and request one or create it as part of governance/docs work.

## Implementation
Builder implements scoped changes authorized by the current task, Roadmap, or standing delegation after goal framing and branch preflight are clear. Builder must report files changed, tests run, risks, manual QA when visual, and evidence mapped to the Goal Charter.

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

## Roadmap Reconciliation
`ROADMAP.md` is the single current-status authority. Before starting substantive work, the Orchestrator reads `Executive Now`, the Ready Queue, and the applicable lane/gate records; Git Steward reconciles any branch, worktree, runtime-pin, or commit mismatch. Before a substantive task is reported complete, implemented pending merge, merged, or waiting, Release Scribe updates the Roadmap from actual Git and verification evidence.

`BRANCH_LEDGER.md` records branch evidence; `TASK_LOG.md` and `CHANGELOG_ARGUS.md` record history. They do not replace the Roadmap's current state or next-action decision.

Momentum Hunter uses parallel pipeline execution. A gate applies only to its
documented development, verification, integration, installation, activation,
Paper, live, or destructive scope. Every waiting task records what it blocks,
what it does not block, its resume evidence, and useful work while waiting.
Global blocked status is allowed only when every unfinished task has been
dependency-evaluated and the Ready Queue is empty.

At most three implementation worktrees are active by default, each in a
different primary lane. One canonical integration lane serializes merge,
runtime installation, and consequential activation. Validated remote-backed
history is not rebased; a newer master requires a fresh reconciliation branch,
recorded source commits, bounded conflict resolution, and complete reverification.

## Deferred Operator Verification
`VERIFICATION_QUEUE.md` is the durable, item-by-item list of Steven's deferred visual/manual checks and anomaly decisions. Every visual change must record the exact screen, action, expected result, forbidden or unchanged behavior, automated evidence, and current manual status. Routine nonvisual work records automated evidence and does not create a Steven approval item.

Automated and manual evidence must remain distinct. `AUTOMATED_PASS` means Codex's build, tests, source review, and available visual proof passed. It does not mean Steven inspected the physical interface. `MANUAL_PENDING` applies to visual or genuinely physical checks and never becomes a pass without Steven's result. Nonvisual work may integrate under standing delegation after Hard Chew proof.

## Autonomous Work
Autonomous-side work must preserve the mode boundary between planning, simulation, paper, read-only live, preview, and confirmed live execution. Execution Architect, Risk Governor Agent, Broker Integration Agent, Paper Trading Agent, Chart Analyst, Equity Research Analyst, and Execution Auditor are read-only/spec-only by default unless a future Goal Charter explicitly assigns implementation to Builder.

Routine read-only brokerage work, OAuth refresh, expected single-account validation/binding, and nontransmitting preview research are standing-authorized when their invariants pass. Broker Integration Agent must interrupt Steven before transmitting, replacing, or cancelling a real order or enabling unattended live execution. Risk Governor Agent owns gate definitions and safety review but does not place trades. Execution Auditor must verify every future simulated, paper, preview, or live order-like action has a TradePlan, risk gate result, approval state, mode, adapter, and ledger evidence.

## Anomaly Interruption
Do not ask Steven to approve expected nonvisual results. Stop and ask a concrete question when observed external state changes the risk or scope.

Examples include:
- More or fewer brokerage accounts than expected, an account ending other than `2573`, a type other than `CASH`, a changed hash, unexpected positions, or broader trading authority. Explain that every unexpectedly authorized account may be exposed to permitted reads and future trade capability.
- Any real order transmission/cancel/replace, unattended-live enablement, money transfer, destructive data operation, database migration, credential revocation/rotation/deletion, provider-app deactivation/deletion, paid service, or ambiguous protected-domain semantic change.
- Secret exposure, failed security proof, remote Git divergence, unexpected changed files, or a test failure that cannot be repaired narrowly without altering the authorized outcome.

Exact CLI confirmation phrases are internal safety interlocks, not recurring CEO approval requests. Codex may satisfy them under standing delegation after proving the documented preconditions.

## Git Stewardship
Git Steward confirms branch, branch base, worktree state, ahead/behind status, and allowed changed paths. Git Steward creates task branches from current local `master`, creates safety branches before risky repair operations, and refuses unsafe merges. Verified nonvisual work may fast-forward into local `master` and receive a non-force backup push under standing delegation. Visual/UI work waits for Steven's manual acceptance. Reset, rebase, branch deletion, force-push, non-fast-forward merge, or remote-divergence resolution always interrupts Steven.

## Output
Codex Orchestrator produces one consolidated CEO report. Steven decides whether the work is accepted.

## Standard Task Flow
1. Steven talks to ChatGPT.
2. ChatGPT writes the task prompt.
3. Goal Steward verifies the Goal Charter for Builder work.
4. Git Steward prepares or verifies the branch.
5. Orchestrator delegates to specialists.
6. Builder implements only scoped app-code tasks authorized by the current task, Roadmap, or standing delegation.
7. QA verifies.
8. Release Scribe reconciles the Roadmap and records historical evidence.
9. Git Steward integrates proven nonvisual work by clean fast-forward; visual work waits for Steven's manual acceptance.
10. Git Steward performs a non-force backup push when the integrated source, tests, protected-path review, and secret scan are clean.

## Stop Conditions
Stop when requirements are ambiguous, the task exceeds standing authority, an anomaly interruption condition is reached, unrelated files change, branch state is ambiguous, or Git integration would require anything other than a clean fast-forward and non-force push.

## Protected Areas
Protected areas require explicit task scope and Hard Chew proof: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior. Do not request a second approval when the exact bounded change is already authorized. Interrupt Steven before semantic expansion, destructive migration, secret exposure/revocation, or real execution.
