# Goal Charter: ARGUS-CONTINUOUS-002 Offline Contract Reconciliation

## Goal

Prove that the dormant continuous-intraday evidence stack, hardened PLAN-002A,
BREAKOUT-002A outcomes, and SHADOW-025A event cycles coexist on one branch
without authority drift, test collision, or operational capability.

## Operator Value

Find cross-contract defects before the stack is eligible for a later serialized
integration window. Preserve Tuesday's installed opening and Paper runtime
exactly as pinned while reducing later merge risk.

## Scope

- Reconcile the six PLAN-002A, BREAKOUT-002A, and SHADOW-025A implementation and
  hardening commits onto ARGUS-CONTINUOUS-001 head `f6b776e`.
- Repair only defects exposed by the combined contract tests.
- Keep all modules dormant, explicit-path, offline, and non-live.
- Record branch-local verification and integration evidence.

## Non-Goals

- No canonical merge, installation, service restart, scheduler repin, or job run.
- No provider, account, position, order, credential, or production-store access.
- No scoring, readiness, selector, Risk Governor, allocation, TradePlan, Shadow,
  Paper, or live runtime wiring.
- No prospective cohort activation or strategy conclusion.

## Acceptance Evidence

- Python compileall passes.
- Combined contract, adjacent protected-boundary, and full discovery tests pass.
- Cross-contract plan authority is independently bound and cannot be forged.
- Static runtime-import, external-capability, secret, and protected-path scans pass.
- Canonical `master` remains clean and synchronized at `78db1bf`.
- Only the feature branch is committed and non-force pushed.

## Status

`IMPLEMENTED_PENDING_MERGE`. Integration remains frozen until Tuesday's terminal
opening and Paper engineering evidence is preserved.
