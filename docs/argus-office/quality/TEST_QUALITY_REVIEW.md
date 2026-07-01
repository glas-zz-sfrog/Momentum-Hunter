# Test Quality Review

Date: 2026-07-01

## Current Test Inventory

| File | Count | Classification |
| --- | ---: | --- |
| `tests/test_trade_planning.py` | 13 | `KEEP` |
| `tests/test_argus_autonomy.py` | 19 | `KEEP_WITH_HARDENING` |
| `tests/test_trade_plan_ladder.py` | 2 | `KEEP_WITH_HARDENING` |
| `tests/test_autonomy_gateway.py` | 9 | `KEEP_WITH_HARDENING` |

Focused command:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_trade_planning tests.test_argus_autonomy tests.test_trade_plan_ladder tests.test_autonomy_gateway -v
```

Result: PASS. 43 tests ran in 6.119 seconds.

## What The Tests Prove

`tests/test_trade_planning.py` proves the TradePlan source model still builds rows, warnings, exports, and market-tape derived states. It also proves no mutation of raw capture in the covered report path.

`tests/test_argus_autonomy.py` proves:

- Top 5 view models use real `TradePlan` objects and safe labels.
- Missing stop and missing max risk block simulation.
- Live mode blocks risk evaluation.
- Manual override requires a risk re-check.
- Ledger events serialize/deserialize.
- FakeBroker supports preview, submit/fill, rejection, and positions.
- Simulation engine records pass/reject results and audit chain evidence.
- Paper advancement gate blocks missing TradePlan evidence and missing order evidence.
- Auditor catches missing required fields, missing risk result, invalid mode/adapter/approval state, missing risk gate, duplicate order-like IDs, and missing order-like IDs.
- FakeBroker implementation has no direct `requests`, `urllib`, or `http` strings.

`tests/test_trade_plan_ladder.py` proves the extracted ladder widget renders structured rows and clears to empty state.

`tests/test_autonomy_gateway.py` proves:

- Gateway routing preserves Steven Desk and Argus Machine paths.
- Argus Machine shell displays simulation/FakeBroker/locked language.
- Top 5 rows render.
- Candidate click populates workbench, ladder, risk table, and machine log.
- Paper/live buttons are disabled and labeled locked.
- Simulation button records FakeBroker order/position/event UI state.
- Auditor displays `WARN` before final simulation outcome and `PASS` after complete simulation evidence.
- Empty candidates state is visible.

## What The Tests Do Not Prove

- They do not prove `SimulationLabEngine` refuses a non-FakeBroker adapter before invoking adapter methods.
- They do not prove an adapter with `order_transmit_allowed=True` is rejected before call.
- They do not prove auditor chronology.
- They do not prove preview evidence is required before fake submit evidence.
- They do not prove ledger write validation at record time.
- They do not prove report source freshness or corrupt report errors are visible to Steven.
- They do not prove UI visual fit with screenshot evidence.
- They do not prove disabled paper/live buttons have no connected command path beyond `isEnabled=False`.

## Missing Negative Tests

1. Non-Fake adapter rejected before preview/submit.
2. Transmit-capable adapter rejected before preview/submit.
3. Submit evidence without preview evidence fails auditor.
4. Order event before risk event fails auditor.
5. Event type/requested action mismatch fails auditor.
6. Empty required fields fail before append or cannot be emitted by engine.
7. Corrupt trade-planning report source produces a visible Top 5 source warning.
8. Fewer-than-five and stale report source states remain safe and clear.
9. Locked paper/live controls cannot call any order path even if programmatically clicked.
10. Manual override state is represented end-to-end in the UI, not only in the Risk Governor unit test.

## Recommended Next Test Task

Create `ARGUS-QUALITY-002` as a tests-first hardening task. It should add the missing negative tests above without implementing broker code, credentials, API keys, or paper/live behavior.
