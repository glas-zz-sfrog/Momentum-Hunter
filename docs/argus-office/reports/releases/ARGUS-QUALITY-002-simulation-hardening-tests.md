# ARGUS-QUALITY-002 - Simulation Foundation Hardening Tests

Date: 2026-07-01
Branch: `codex/ARGUS-QUALITY-002-simulation-hardening-tests`

## Summary

ARGUS-QUALITY-002 adds targeted negative tests and narrow safety fixes for the Argus Machine simulation foundation. The goal is to prove that the Simulation Lab fails safely before any future paper/live broker work depends on it.

## Tests Added Or Strengthened

- `tests/test_argus_autonomy.py`
  - Added non-Fake adapter rejection proof: `SimulationLabEngine` blocks a non-Fake adapter before any adapter preview/submit call.
  - Added transmit-capable adapter rejection proof: transmit-capable metadata is blocked before any adapter method call.
  - Added preview-before-submit audit proof: `audit_simulation_chain` fails submit evidence without prior simulated preview evidence.
  - Added chronology audit proof: `audit_simulation_chain` fails when order evidence appears before Risk Governor evidence.
  - Added a recording adapter test double that records broker method calls so tests prove no broker method was invoked.
- `tests/test_autonomy_gateway.py`
  - Added locked UI no-op proof: programmatic clicks on disabled paper/live controls create no ledger events and no FakeBroker orders.

## Code Fixes Made

- `momentum_hunter/autonomy/simulation.py`
  - Added `simulation_adapter_block_reason`.
  - `SimulationLabEngine.run_candidate` now blocks before preview/submit if the adapter is not the local `FakeBrokerAdapter`, is not in `Simulation Lab`, allows transmit, requires credentials, or advertises paper/live/transmit capabilities.
- `momentum_hunter/autonomy/auditor.py`
  - Added chronology checks for simulation chains.
  - Auditor now requires Risk Governor evidence before preview/submit/block evidence.
  - Auditor now requires simulated preview evidence before fake submit evidence.

## Behavior Preserved

- FakeBroker simulation still supports preview, fill, rejection, positions, ledger events, and UI rendering.
- Paper and live controls remain locked.
- No paper broker, live broker, broker credentials, API keys, dependency changes, schema changes, scoring changes, readiness changes, replay changes, or market-data runtime changes were added.

## Verification

Required verification commands:

```powershell
.\.venv\Scripts\python.exe -B -m compileall -q momentum_hunter tests
.\.venv\Scripts\python.exe -B -m unittest tests.test_trade_planning tests.test_argus_autonomy tests.test_trade_plan_ladder tests.test_autonomy_gateway -v
git diff --check
git status --short --branch
```

Expected result at release time: compile passes, focused tests pass, diff check passes, and worktree is clean after commit.

## Forbidden-Pattern Scan Meaning

The task requires a scan for risky terms such as broker names, credentials, network libraries, and order-submission language. Expected safe hits include:

- Test names and strings for locked paper/live controls.
- Test-only fake invalid adapter metadata.
- Existing market-data/provider code elsewhere in Momentum Hunter using HTTP requests.

Risky result would be any new paper/live broker implementation, credential handling, API key handling, or external broker/network call in the autonomy simulation path.

## Merge Recommendation

Merge after the full verification suite passes. This branch is a targeted hardening branch and should be fast-forward merged only after Steven review.
