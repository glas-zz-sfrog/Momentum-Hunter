# Current State

## Phase
Argus Office v0.1 guided workflow design review.

## Branch
`codex/ARGUS-0003-guided-daily-workflow-design`

## State Summary
ARGUS-0003 produced a design-only audit for the Daily Workflow experience. The recommendation is to adopt a Modern Command Cockpit direction, implemented first through a small guided-step improvement to the existing Daily Workflow dialog so current data contracts and quick actions remain protected.

## Active Rule
Steven remains final merge approver. No push or merge has been performed. Future work should remain task-branch scoped and avoid protected areas unless explicitly approved.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should review the ARGUS-0003 design report and decide whether Daily Workflow should remain a guided modal first or become a first-class Dashboard cockpit after the bridge slice. Recommended next Builder task: redesign the existing Daily Workflow dialog into a guided stepper using only current report/context data and existing actions.
