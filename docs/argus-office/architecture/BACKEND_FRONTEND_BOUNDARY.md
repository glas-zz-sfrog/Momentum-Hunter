# Backend / Frontend Boundary

## Boundary Decision
Momentum Hunter should evolve toward a Python engine plus replaceable frontend architecture. The frontend should ask the engine for state, commands, and DTOs; it should not own scoring, readiness, replay, storage, or broker semantics.

## Python Engine Responsibilities
The Python engine should own:
- Scanning/provider access.
- Candidate normalization.
- Scoring and score explanations.
- Review identities and review state.
- Watchlist and entry-plan persistence.
- Daily Workflow report facts.
- Evidence and readiness reports.
- Replay timeline and identity.
- SQLite storage and migrations.
- TradePlan generation and validation.
- Future Risk Governor evaluation.
- Future Broker Adapter and Execution Ledger services only after approved Goal Charters.

## Frontend Responsibilities
The frontend should own:
- Navigation.
- Layout.
- Visual theme and components.
- Button/menu interactions.
- Presentation of DTOs.
- Screenshot-proofable UI states.
- Operator-facing text that does not alter engine semantics.

## Application Service Layer
Introduce a service layer between UI and engine:

```text
Frontend Page
  -> Application Service
      -> Engine Module
      -> Storage/Provider Module
  <- DTO/View Model
```

Candidate services:
- `DashboardService`
- `DailyWorkflowService`
- `WatchlistService`
- `ReplayService`
- `EvidenceService`
- `ArgusMachineService`
- `TradePlanService`
- `RiskGovernorService`

## DTOs Needed First
- `GatewayState`
- `DashboardSnapshot`
- `DailyWorkflowViewModel`
- `WatchlistCenterViewModel`
- `ReplaySnapshotViewModel`
- `ArgusMachineConsoleViewModel`
- `TradePlanViewModel`
- `RiskGovernorViewModel`
- `MachineLogEvent`

## Command Boundary
Frontend commands should be narrow and explicit:
- `run_scan`
- `load_capture`
- `mark_review_status`
- `save_entry_plan`
- `generate_watchlist_report`
- `open_replay_snapshot`
- `evaluate_trade_plan`
- `append_machine_log_event`

Commands that must remain absent until separately approved:
- broker connect
- order preview
- paper order submit
- live order submit
- live route enable
- scoring weight mutation
- readiness semantic mutation

## Why This Enables Future Frontends
Once the Python service layer returns DTOs and accepts explicit commands, PySide6 can remain the first frontend while WinUI, Avalonia, or Tauri can later be evaluated without rewriting the engine.

## Immediate Boundary Rule
Do not start a second frontend until:
- R001-R005 are complete.
- Critical DTOs are documented.
- PySide6 pages consume at least some view models instead of direct app state.
- The broker/execution boundary remains locked.
