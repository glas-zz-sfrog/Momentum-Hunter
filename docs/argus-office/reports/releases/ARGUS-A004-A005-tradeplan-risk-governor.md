# ARGUS-A004/A005 TradePlan Model + Risk Governor First Gates

## Branch
`codex/ARGUS-A004-A005-tradeplan-risk-governor`

## Scope
Implemented the first autonomous planning backbone for Argus Machine: a structured `TradePlan` model and a pure first-pass `Risk Governor` evaluator. This is model/evaluation code only.

## Files Changed
- `momentum_hunter/execution/__init__.py`
- `momentum_hunter/execution/trade_plan.py`
- `momentum_hunter/execution/risk_governor.py`
- `tests/test_trade_plan.py`
- `tests/test_risk_governor.py`
- `docs/argus-office/reports/releases/ARGUS-A004-A005-tradeplan-risk-governor.md`
- `docs/argus-office/CURRENT_STATE.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`

## TradePlan Model
`TradePlan` includes:
- `plan_id`
- `ticker`
- `direction`
- `setup_type`
- `entry_trigger`
- `entry_limit`
- `stop_price`
- `target_1`
- `target_2`
- `target_3`
- `trailing_stop_rule`
- `position_size`
- `max_dollar_risk`
- `risk_reward`
- `manual_override`
- `mode`
- `source`
- `created_at`
- `approval_status`

Validation is conservative: ticker and direction are required, entry trigger or entry limit is required, stop is required before risk approval, position size and max dollar risk must be nonnegative, manual override requires re-check, and live modes are locked by default.

## Risk Governor Gates
The first Risk Governor evaluates:
- ticker present
- direction present
- entry defined
- stop defined
- at least one target defined
- max dollar risk defined and nonnegative
- position size defined and nonnegative
- mode allowed for non-broker evaluation
- manual override re-check
- approval status for advancement

Risk statuses are:
- `PASS`
- `WARN`
- `BLOCK`
- `NEEDS_STEVEN`
- `LOCKED`

## Safety Boundary
This implementation does not connect to brokers, preview orders, submit paper orders, submit live orders, modify scoring, alter readiness semantics, change replay identity, touch database/schema files, change alert thresholds, add secrets, or change runtime market data behavior.

Live and live-preview modes return locked Risk Governor results by default. Paper mode requires Steven approval. Simulation can pass when complete and explicitly simulation-approved, or warn conservatively when approval is still draft.

## Ladder Compatibility
`TradePlan.to_ladder_rows()` and `TradePlan.to_ladder_dict()` produce field/value data suitable for a future Trade Plan Ladder integration without wiring the UI yet.

## Verification
- `.\.venv\Scripts\python.exe -B -m compileall -q momentum_hunter tests`
- `.\.venv\Scripts\python.exe -B -m unittest tests.test_trade_plan tests.test_risk_governor -v`
- `git diff --check`

## Manual QA
No manual UI QA is required for this task because the UI was not wired. Review the tests and release report to confirm conservative gate language before UI integration.

## Risks
The model is intentionally conservative and not yet persisted or connected to the Argus Machine UI. Future work should map placeholder console candidates into `TradePlan` objects only after Steven approves the next implementation slice.

## Recommendation
Proceed to a narrow UI integration task only after Steven reviews the model fields and gate names.
