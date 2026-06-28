# Extraction Targets

## Recommendation
Start with `ARGUS-R002 - Extract Gateway / Argus Machine UI into dedicated PySide module`.

This gives Momentum Hunter a clean page-module pattern without touching production behavior. It also removes a visible autonomous-side UI island from `app.py` and prepares the Trade Plan Ladder for a later real view model.

## First 10 Ranked Targets

| Rank | Target | Proposed Module | Safety | Value | Primary Tests |
| ---: | --- | --- | --- | --- | --- |
| 1 | Gateway / Argus Machine UI | `momentum_hunter/ui/argus_machine.py` | High | High | `tests.test_autonomy_gateway` |
| 2 | Argus placeholder candidates and ladder row mapping | `momentum_hunter/ui/argus_machine.py` or later `argus_machine_view_model.py` | High | High | `tests.test_autonomy_gateway` |
| 3 | Daily Workflow step/next-action view model | `momentum_hunter/ui/daily_workflow_view_model.py` | Medium/High | High | `tests.test_daily_workflow` plus pure tests |
| 4 | Daily Workflow widget builder | `momentum_hunter/ui/daily_workflow_page.py` | Medium | High | `tests.test_daily_workflow` |
| 5 | Design-system/theme layer | `momentum_hunter/ui/theme.py` | Medium | High | focused GUI tests plus screenshot sanity |
| 6 | Common PySide components | `momentum_hunter/ui/components.py` | High | Medium | compileall plus touched GUI tests |
| 7 | Replay/story views | `momentum_hunter/ui/replay_views.py` | Medium | Medium | replay/navigation tests |
| 8 | Research report panels | `momentum_hunter/ui/report_panels.py` | Medium | Medium | report panel focused tests if existing, compileall |
| 9 | Watchlist Center view model | `momentum_hunter/ui/watchlist_center_view_model.py` | Medium/Low | High | watchlist/daily workflow tests |
| 10 | Evidence Console view model/service adapter | `momentum_hunter/ui/evidence_console.py` plus service adapter | Medium/Low | High | active monitor dashboard/evidence tests |

## R002 Target Detail
Move:
- `ARGUS_MACHINE_PLACEHOLDER_CANDIDATES`
- `_build_gateway_page`
- `_build_gateway_choice`
- `_build_argus_machine_console_page`
- `_build_argus_machine_status_bar`
- `_build_argus_top5_panel`
- `_build_argus_workbench_panel`
- `_build_argus_trade_plan_ladder_panel`
- `_build_argus_risk_governor_panel`
- `_build_argus_order_console_panel`
- `_build_argus_machine_log_panel`
- `_clear_argus_trade_plan_ladder`
- `_select_argus_machine_candidate`

Keep on `MomentumHunterWindow` or thin wrappers:
- `show_gateway`
- `open_steven_desk`
- `open_argus_machine_console`

Reason: these route through app stacks and status updates. They can stay as shell methods while builders move out.

## R002 Proposed File Shape

```text
momentum_hunter/
  app.py
  ui/
    __init__.py
    argus_machine.py
```

Possible functions in `argus_machine.py`:
- `build_gateway_page(window) -> QWidget`
- `build_gateway_choice(title, subtitle, detail, safety, callback) -> QWidget`
- `build_argus_machine_console_page(window) -> QWidget`
- `clear_trade_plan_ladder(window) -> None`
- `select_machine_candidate(window, candidate) -> None`
- `ladder_rows_for_candidate(candidate) -> list[tuple[str, str]]`

## R002 Acceptance Criteria
- `app.py` delegates Gateway/Argus Machine builders to `momentum_hunter/ui/argus_machine.py`.
- Gateway opens both Steven Desk and Argus Machine.
- Argus Machine keeps Simulation Lab, no broker connected, live trading locked, preview-only Risk Governor, disabled order controls, Top 5 candidate rows, and ladder population.
- Existing object names used by tests remain findable.
- No scoring, readiness, replay, storage/schema, package, generated-data, broker/order, or runtime behavior changes.

## First 5 Extraction Tasks

### ARGUS-R002 - Extract Gateway / Argus Machine UI Into Dedicated PySide Module
Branch: `codex/ARGUS-R002-extract-gateway-machine-ui`

Allowed files:
- `momentum_hunter/app.py`
- `momentum_hunter/ui/**`
- `tests/test_autonomy_gateway.py`
- `docs/argus-office/reports/releases/**`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`

Protected files:
- scoring, readiness, replay identity, storage/schema, broker/order, package/dependency files, generated data

Tests:
- compileall for `momentum_hunter tests`
- `tests.test_autonomy_gateway`
- screenshot sanity if visible layout changes
- `git diff --check`

Stop conditions:
- safety labels disappear
- order controls become enabled
- object names break
- route behavior changes
- protected files change

Acceptance criteria:
- Gateway/Argus builders live outside `app.py`.
- Behavior and tests are unchanged.

### ARGUS-R003 - Extract Daily Workflow UI Builder
Branch: `codex/ARGUS-R003-extract-daily-workflow-ui`

Allowed files:
- `momentum_hunter/app.py`
- `momentum_hunter/ui/**`
- `tests/test_daily_workflow.py`
- release docs

Protected files:
- scoring, readiness semantics, replay, storage/schema, broker/order, package/dependency files, generated data

Tests:
- compileall
- `tests.test_daily_workflow`
- pure view-model tests if a mapper is added
- `git diff --check`

Stop conditions:
- next required action order changes unexpectedly
- blocker/dependency wording regresses
- quick actions become no-ops
- readiness semantics change

Acceptance criteria:
- Daily Workflow widget builders and step view mapping leave `app.py`.
- Existing states remain proven.

### ARGUS-R004 - Create Design System / Theme Layer
Branch: `codex/ARGUS-R004-design-system-theme-layer`

Allowed files:
- `momentum_hunter/app.py`
- `momentum_hunter/ui/**`
- focused GUI tests
- screenshot artifacts under release docs
- release docs

Protected files:
- engine behavior, scoring, readiness, replay, storage/schema, broker/order, package/dependency files

Tests:
- compileall
- focused GUI tests for screens touched
- screenshot proof
- `git diff --check`

Stop conditions:
- warning/locked/live/paper visual states become ambiguous
- text overlaps
- button affordances degrade
- protected behavior changes

Acceptance criteria:
- reusable theme tokens and common components exist
- one isolated screen demonstrates the new system

### ARGUS-R005 - Define Backend Engine Boundary DTOs
Branch: `codex/ARGUS-R005-backend-engine-boundary-dtos`

Allowed files:
- docs by default
- optional pure DTO/view-model modules only with explicit approval
- focused tests only if implementation is approved

Protected files:
- scoring, readiness, replay identity, schema/migrations, broker/order, package/dependency files, generated data

Tests:
- docs-only checks by default
- compileall and DTO/service tests only if implementation is approved

Stop conditions:
- a second frontend starts
- broker/order behavior appears
- scoring/readiness/replay semantics mutate

Acceptance criteria:
- engine DTOs and command/no-command boundary are defined
- future frontend prerequisites are explicit

### ARGUS-R006 - Extract Trade Plan Ladder UI Component
Branch: `codex/ARGUS-R006-extract-trade-plan-ladder-ui`

Allowed files:
- `momentum_hunter/app.py`
- `momentum_hunter/ui/**`
- `tests/test_autonomy_gateway.py` or a new focused ladder UI test
- release docs

Protected files:
- broker/order execution, scoring, readiness, replay, storage/schema, package/dependency files, generated data

Tests:
- compileall
- focused Trade Plan Ladder UI tests
- screenshot sanity if visible layout changes
- `git diff --check`

Stop conditions:
- ladder implies approved live trades
- locked/live/paper/simulation language is weakened
- manual override or Risk Governor status disappears

Acceptance criteria:
- Trade Plan Ladder is a reusable UI component
- it remains display-only and live-locked

## What Not To Extract First
- Scanner execution.
- Review-decision writes.
- Entry-plan writes.
- Watchlist report generation.
- Capture save/load/autocapture.
- Replay identity.
- Readiness semantics.
- Active monitor process control.
