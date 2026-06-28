# Goal Charter Template

## Goal Statement

## User Pain / Operator Outcome

## In Scope
-

## Out Of Scope
-

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Acceptance Criteria
-

## Evidence Required
-

## Evidence Depth / Hard Chew Requirements
For implementation tasks, define what would prove the goal beyond shallow completion. Include:
- Compile/check command required, if applicable.
- Focused tests required for the changed behavior.
- Broader bounded test discovery required, with timeout handling.
- UI proof required for UI changes, including screenshot sanity checks when possible.
- Protected-path diff review required.
- Second-pass self-review of diff, tests, docs, and user-facing behavior.
- Narrow fix pass for self-review findings.
- Final verification pass before commit.
- Required final evidence: commands run, test results, files changed, proof artifacts, protected areas reviewed, branch status, push/merge status, and remaining risks.

Do not accept completion merely because files were created, labels exist, or tests only prove the presence of text.

## Smallest Safe Implementation Slice

## Open CEO Decisions
-

## Goal Steward Review
- [ ] Goal statement is concrete.
- [ ] Operator outcome is clear.
- [ ] Scope and non-goals are explicit.
- [ ] Protected areas are named.
- [ ] Acceptance criteria prove the requested outcome.
- [ ] Evidence required is strong enough to verify completion.
