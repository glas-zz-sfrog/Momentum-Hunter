# ARGUS-SHADOW-025A - Synthetic Event-Driven Decision-Cycle Contract

## Status

- Branch: `codex/ARGUS-SHADOW-025A-synthetic-decision-cycle-contract`
- Base: PLAN-002A `7be49fd8192517bc3b8dd18d4aa14c55393791ed`
- Classification: `IMPLEMENTED_PENDING_MERGE`
- Canonical runtime impact: none

## Implementation

`momentum_hunter/event_driven_decision_cycle.py` adds a dormant evidence contract:

- Material trigger evidence with stable IDs and SHA-256 fingerprints.
- Explicit suppression receipts for quote-only changes, insufficient deltas, and active
  entry cooldown.
- Safety-trigger and safety-state cooldown bypass.
- Immutable non-live cycles bound to the exact PLAN-002A plan, risk, allocation, account,
  capability, configuration, and predecessor evidence.
- Fail-closed equality between the event-cycle policy configuration and the versioned
  PLAN-002A configuration.
- Atomic, explicit-path JSON persistence with deterministic bytes, idempotent replay,
  tamper validation, and shared in-process path locking.

The contract stops at `SELECTED_FOR_DOWNSTREAM_NONLIVE_EXECUTION` or `NO_SELECTION`.
Those labels are evidence for a later integration task, not an order instruction.

## Verification

- Compileall: pass.
- Focused suite: 36/36 pass.
- Adjacent lifecycle/plan/Shadow/context suite: 268/268 pass.
- Adjacent Paper/allocation suite: 46/46 pass.
- Affected legacy storage/story tests after harness collision: 15/15 pass.
- Self-review regressions: 230/230 continuous-evidence and 62/62 Paper/allocation pass.
- Clean final Python discovery: 1,674/1,674 pass in 226.106 seconds.
- Initial full-discovery rerun was invalid because an earlier timed-out child continued
  concurrently and collided on fixed legacy `_test_*` paths; no SHADOW-025A test failed.
- No existing module imports the new contract.
- No .NET/WPF test is required because no .NET or UI file changed.

## Safety Boundary

- No provider, network, account, credential, service, scheduler, Engine Host, WPF, or
  production data-store access.
- No broker adapter and no submit, replace, cancel, fill, mark, or lifecycle method.
- No score, readiness, selector, TradePlan, Risk Governor, allocation, or Shadow mutation.
- No merge, install, activation, Paper order, or live order.

## Remaining Work

- Preserve Tuesday's terminal operational evidence.
- Integrate ARGUS-CONTINUOUS-001, then PLAN-002A, then SHADOW-025A in dependency order.
- Define and prove actual runtime event-source semantics separately.
- Add a production persistence ownership/locking design before wiring multiple processes.
