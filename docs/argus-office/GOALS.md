# Argus Goals

This file records durable product and operating goals that should survive individual task branches.

## Daily Workflow: Make The Next Light Click

Status: Active

Goal: Momentum Hunter's Daily Workflow should make the operator's next required action obvious, including the dependency that must be satisfied to make the next light click.

Operator Pain: Steven should not have to infer sequence, blockers, readiness meaning, stale-data risk, or watchlist prerequisites from scattered buttons and audit tables.

Current Evidence:
- ARGUS-0003 produced the guided Daily Workflow design report.
- ARGUS-0004 added the first guided modal stepper bridge.
- ARGUS-0006 identified follow-up quality issues around stale data, no-candidates, no-watchlist, incomplete plans, readiness diagnostic states, and button/state mismatch.

Acceptance Direction:
- Trust blockers dominate normal workflow actions.
- Capture missing, stale data, no candidates, unreviewed candidates, no watchlist, incomplete plans, and readiness gates use distinct language.
- The UI shows one next required action and explains why it is next.
- Existing scoring, readiness, replay, alert, storage, and runtime semantics stay protected unless Steven explicitly approves a separate change.

## Governance: Goal Charter Before Builder

Status: Active

Goal: Future Builder tasks should start from an explicit Goal Charter so implementation, tests, and acceptance evidence all point at the same desired outcome.

Acceptance Direction:
- Task prompts or office docs identify goal, operator pain, scope, non-goals, protected areas, acceptance criteria, and evidence required.
- Goal Steward verifies the charter before Builder implementation begins.
- Completion reports map verification back to the charter instead of redefining success around what was easiest to implement.
