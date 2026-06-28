# Refractor Roadmap

This file intentionally keeps the directive spelling `REFRACTOR_ROADMAP.md`. The work described is a refactor roadmap.

## Roadmap Decision
Use five small tasks to move from architecture decision to executable modernization. No task may rewrite Momentum Hunter wholesale.

## ARGUS-R001 - App.py Responsibility Map and Extraction Targets

Goal ID: `ARGUS-R001`

Branch name: `codex/ARGUS-R001-app-py-responsibility-map`

Allowed files:
- `docs/argus-office/reports/architecture/**`
- `docs/argus-office/architecture/**`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`

Protected files:
- `momentum_hunter/**`
- `tests/**`
- package/dependency files
- database/schema files
- generated data

Implementation allowed: no.

Tests required:
- `git diff --check`
- changed-path check confirming docs only

Stop conditions:
- Any code file would need to change.
- The responsibility map cannot identify line ranges and seams.

Acceptance criteria:
- Line-range responsibility map for `app.py`.
- Extraction target list ranked by risk.
- Test inventory for each target.
- No production behavior changed.

Push policy: push feature branch only.

Merge policy: Steven approval only.

## ARGUS-R002 - Extract Gateway / Argus Machine UI into Dedicated Module

Goal ID: `ARGUS-R002`

Branch name: `codex/ARGUS-R002-extract-gateway-machine-ui`

Allowed files:
- `momentum_hunter/app.py`
- `momentum_hunter/ui/**`
- `tests/test_autonomy_gateway.py`
- Argus Office release docs

Protected files:
- scoring, readiness, replay, storage/schema, broker/order, generated data, package files

Implementation allowed: yes.

Tests required:
- compile check for `momentum_hunter tests`
- `tests/test_autonomy_gateway.py`
- focused UI screenshot sanity if visual output changes
- `git diff --check`

Stop conditions:
- Any broker/order behavior appears.
- Object names or safety labels are lost without explicit approval.
- Gateway no longer opens both Steven Desk and Argus Machine.

Acceptance criteria:
- Gateway and Argus Machine builders move out of `app.py`.
- Existing behavior and safety locks remain.
- Tests prove the gateway routes and locked order controls.

Push policy: push feature branch only.

Merge policy: Steven approval only.

## ARGUS-R003 - Extract Daily Workflow UI Builder from App.py

Goal ID: `ARGUS-R003`

Branch name: `codex/ARGUS-R003-extract-daily-workflow-ui`

Allowed files:
- `momentum_hunter/app.py`
- `momentum_hunter/ui/**`
- `momentum_hunter/daily_workflow.py` only if pure report DTOs need import adjustments
- `tests/test_daily_workflow.py`
- Argus Office release docs

Protected files:
- scoring, readiness semantics, replay, storage/schema, broker/order, generated data, package files

Implementation allowed: yes.

Tests required:
- compile check for `momentum_hunter tests`
- `tests/test_daily_workflow.py`
- pure view-model tests if new Daily Workflow mapper is created
- `git diff --check`

Stop conditions:
- Step statuses, blocker language, or next-action order changes unintentionally.
- Readiness Gate semantics change.
- Workflow action buttons become no-ops.

Acceptance criteria:
- Daily Workflow UI builders and step view mapping leave `app.py`.
- Existing labels/statuses remain unless explicitly changed.
- Tests prove next-action, blockers, no-candidates/no-watchlist/incomplete plan states.

Push policy: push feature branch only.

Merge policy: Steven approval only.

## ARGUS-R004 - Create Momentum Hunter Design System / Theme Layer

Goal ID: `ARGUS-R004`

Branch name: `codex/ARGUS-R004-design-system-theme-layer`

Allowed files:
- `momentum_hunter/app.py`
- `momentum_hunter/ui/**`
- focused GUI tests
- screenshot proof artifacts under `docs/argus-office/reports/releases/**`
- Argus Office release docs

Protected files:
- engine behavior, scoring, readiness, replay, storage/schema, broker/order, package files

Implementation allowed: yes.

Tests required:
- compile check for `momentum_hunter tests`
- focused GUI tests for screens touched
- screenshot sanity checks for UI changes
- `git diff --check`

Stop conditions:
- Visual polish changes break workflow clarity.
- Theme changes make warning/locked/live/paper states ambiguous.
- Text overlaps or buttons become unreadable.

Acceptance criteria:
- Reusable theme tokens exist.
- Common status pills, banners, cards, and locked controls exist.
- Gateway or Argus Machine demonstrates the new system.
- Screenshot proof confirms nonblank, expected panels visible.

Push policy: push feature branch only.

Merge policy: Steven approval only.

## ARGUS-R005 - Define Backend Engine Boundary for Future Frontend Rewrite

Goal ID: `ARGUS-R005`

Branch name: `codex/ARGUS-R005-backend-engine-boundary`

Allowed files:
- `docs/argus-office/architecture/**`
- optional pure DTO/view-model modules only if separately approved by Steven
- focused tests only if implementation is approved

Protected files:
- scoring, readiness, replay identity, schema/migrations, broker/order, package files, generated data

Implementation allowed: no by default; yes only with explicit Steven approval in the task prompt.

Tests required:
- docs-only: `git diff --check` and changed-path check
- if implementation approved: compile check and focused DTO/service tests

Stop conditions:
- The task starts building a second frontend.
- The task creates broker/order behavior.
- The boundary would mutate scoring or readiness semantics.

Acceptance criteria:
- Service/DTO boundary documented.
- Frontend command list documented.
- Protected no-command list documented.
- Clear prerequisites for WinUI/Avalonia/Tauri evaluation.

Push policy: push feature branch only.

Merge policy: Steven approval only.
