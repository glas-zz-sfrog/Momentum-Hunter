# ARGUS-A002/A003 Gateway Shell + Argus Machine Console Skeleton

## Branch
`codex/ARGUS-A002-A003-gateway-machine-console-skeleton`

## Scope
Implemented the first visible autonomous product split: a startup gateway with Steven Desk and Argus Machine choices, plus a safe Argus Machine Console skeleton.

## Files Changed
- `momentum_hunter/app.py`
- `tests/test_autonomy_gateway.py`
- `docs/argus-office/reports/releases/ARGUS-A002-A003-gateway-machine-console-skeleton.md`
- `docs/argus-office/CURRENT_STATE.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`

## On-Screen Change
Momentum Hunter now opens to a premium dark gateway with two large choices:
- Steven Desk: human-guided momentum operations.
- Argus Machine: autonomous planning, simulation, and execution control.

Steven Desk opens the existing dashboard path. Argus Machine opens a display-only console shell with Machine Status Bar, Top 5 Trade Plan Candidates, Selected Candidate Workbench, Trade Plan Ladder, Risk Governor, Order Console, and Machine Log.

## Safety Boundary
The Argus Machine shell uses placeholder/demo candidate data only. It does not connect to a broker, does not preview orders, does not submit paper orders, does not submit live orders, and does not change scoring, readiness, replay, alert thresholds, database/schema files, package files, generated data, or market-data runtime behavior.

## Top 5 To Ladder Behavior
The console shows five placeholder candidate rows. Each row contains ticker, setup label, status, and gate state. Clicking a candidate populates the Trade Plan Ladder with placeholder fields for entry trigger, entry/limit, stop/invalidation, targets, trailing rule, position size, max dollar risk, risk/reward, manual override state, and Risk Governor status.

## Verification
- `python -m unittest tests.test_autonomy_gateway -v` passes.
- `python -m unittest tests.test_daily_workflow -v` passes.
- `python -m unittest tests.test_gui_states.GuiStateTests.test_command_center_navigation_pages_exist -v` passes.
- `git diff --check` passes.
- Changed-path review confirms protected app domains were not modified.

## UI Evidence
Generated UI proof screenshots:
- `docs/argus-office/reports/releases/ARGUS-A002-A003-gateway-ui-proof.png`
- `docs/argus-office/reports/releases/ARGUS-A002-A003-machine-console-ui-proof.png`

## Manual QA
1. Launch Momentum Hunter.
2. Confirm the first screen is the gateway.
3. Click Steven Desk and confirm the existing dashboard opens.
4. Return to the gateway using the Gateway control.
5. Click Argus Machine.
6. Confirm Machine Status Bar says Simulation Lab, Broker None connected, Live Trading Locked, Risk Governor Preview only, Kill Switch Available.
7. Click each Top 5 candidate and confirm the Trade Plan Ladder updates.
8. Confirm Preview Order, Submit Paper Order, and Submit Live Order are disabled.

## Risks
This is a UI shell only. Future tasks still need product review, data contracts, model work, Risk Governor logic, and broker adapter boundaries before any real execution path exists.

## Recommendation
Steven should manually QA the gateway and Argus Machine shell, then use ARGUS-A004/A005 planning when ready to define TradePlan and Risk Governor behavior.
