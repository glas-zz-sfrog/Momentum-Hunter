# ARGUS-A014/A015C - Simulation Cockpit and Auditor Gate Hardening

Date: 2026-06-30

Branch: `codex/ARGUS-A006-A015-argus-machine-simulation`

## Summary

ARGUS-A014/A015C hardens the Argus Machine prototype into a stronger simulation foundation. The console now separates simulated orders, simulated positions, and ledger-backed fills/events while keeping every order path explicitly FakeBroker-only. The Execution Auditor is also visible in the console as a display-only paper advancement gate: future paper work must start from a passing simulation evidence chain, but no paper or live broker is implemented here.

## Cockpit Changes

- Simulated Orders panel shows order ID, ticker, side, quantity, status, mode, TradePlan ID, and RiskResult ID.
- Simulated Positions panel shows FakeBroker-only simulated positions with average fake fill price.
- Simulated Fills / Events panel renders preview, submitted, rejected, filled, and blocked simulation events from the Execution Ledger.
- Simulation status copy says there is no paper broker, no live broker, and no real order.

## Auditor Gate Changes

- Added an explicit paper advancement audit gate over the simulation evidence chain.
- Argus Machine displays Auditor `PASS`, `WARN`, or `BLOCK`.
- The auditor evidence table links selected TradePlan, RiskResult, ledger risk gate, ledger final order/block outcome, and BrokerAdapter evidence.
- Running simulation records an `execution_audited` ledger event.
- Paper and live controls remain locked regardless of audit status.

## Safety Invariants

- FakeBroker remains the only adapter used by the console.
- No credentials, API keys, paper adapter, live adapter, or network broker calls were added.
- No scoring, readiness, replay, schema, generated data, package, or runtime market-data behavior changed.

## Verification

- Compile: `.\.venv\Scripts\python.exe -B -m compileall -q momentum_hunter tests`
- Focused suite: `.\.venv\Scripts\python.exe -B -m unittest tests.test_trade_planning tests.test_argus_autonomy tests.test_trade_plan_ladder tests.test_autonomy_gateway -v`
- Diff check: `git diff --check`
- UI proof: `docs/argus-office/reports/releases/ARGUS-A014-A015C-simulation-cockpit-auditor-proof.png`

## Remaining Risks

- This is still simulation-only; paper broker research and implementation remain deferred.
- The simulated positions and fills model is deterministic FakeBroker behavior, not real brokerage semantics.
- The auditor gate is display-only for future paper advancement; no paper mode exists to unlock.
