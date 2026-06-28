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

## Autonomy: Build The Machine Room Safely

Status: Active

Goal: Momentum Hunter should grow a second major experience, Argus Machine, for autonomous planning, simulation, paper trading, broker awareness, and future execution supervision under strict gates.

Operator Pain: Steven needs to see how the autonomous side will evolve before broker integration begins, without mixing planning language with approved live-trade language.

Acceptance Direction:
- A two-door gateway separates Steven Desk from Argus Machine.
- Argus Machine shows Machine Status, Top 5 Trade Plan Candidates, Selected Candidate Workbench, Trade Plan Ladder, Risk Governor, Order Console, Machine Log, and Execution Ledger concepts.
- TradePlan, Risk Governor, Broker Adapter, and Execution Ledger boundaries exist before any broker work.
- Live execution remains locked until Steven explicitly approves a future live-execution Goal Charter.

## Architecture: Modernize Without A Premature Rewrite

Status: Active

Goal: Momentum Hunter should become easier to modernize and eventually frontend-replaceable without rewriting proven Python engine behavior.

Operator Pain: Steven sees a dated UI and a large `app.py`, but a full rewrite would risk scoring, readiness, replay, storage, and broker safety before the frontend/backend boundary is ready.

Current Evidence:
- ARGUS-R000 found `momentum_hunter/app.py` is 7,188 lines and mixes shell navigation, UI construction, workflow mapping, scanner orchestration, report rendering, formatting, and styling.
- Backend modules already exist for daily workflow, scoring, storage, replay, SQLite, trade planning, evidence, and UI view-state decisions.

Acceptance Direction:
- No full rewrite until the Python engine boundary is explicit.
- PySide6 modernization comes first.
- `app.py` shrinks through small, test-protected extractions.
- Future WinUI, Avalonia, or Tauri work stays optional until R001-R005 prove the boundary.
- Protected trading, replay, storage, scoring, readiness, and broker/order behavior remain untouched unless Steven approves a separate Goal Charter.
