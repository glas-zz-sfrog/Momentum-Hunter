# ARGUS-PLAN-002A Continuous Plan-Version Contract

## Classification

`IMPLEMENTED_PENDING_MERGE`

## Baseline

- Canonical frozen baseline: `78db1bfddc91917b98a818f584576943e5624263`.
- Stacked prerequisite head: `f6b776eb876c75805e8b144a12e8ccd96fd226ab`.
- Feature branch: `codex/ARGUS-PLAN-002A-continuous-plan-version-contract`.
- Canonical checkout and installed runtime were not modified.

## Implementation

`momentum_hunter/continuous_plan_version.py` adds a pure contract for:

- deterministic immutable continuous plan versions;
- exact candidate opportunity and setup-revision binding;
- validated regime, macro-event, catalyst, RVOL, and source-clock lineage;
- append-only predecessor/supersession history;
- separate risk and provider-neutral allocation decision references;
- explicit authorized-for-configured-nonlive-mode or `NO_TRADE` outcomes;
- structural rejection of live modes and reused manual-override decisions;
- explicit-path, atomic, idempotent plan-ledger persistence.

It consumes DATA-004 plan semantics rather than redefining entry, stop, target,
expiry, missed-entry, reclaim, or forced-flat behavior.

## Verification

- Python compileall: PASS.
- Focused PLAN-002A suite: 19 / 19 PASS.
- Adjacent candidate, regime, event, catalyst, DATA-004, provider-neutral
  allocation, and Paper research suites: 210 / 210 PASS.
- Full Python discovery: 1,638 / 1,638 PASS in 227.802 seconds.
- Exact-repeat identity and byte-stable store proof: PASS.
- Tamper, forged-authority, stale/blocking context, missing clock, chain-branch,
  cross-identity, live-mode, and manual-override negative proof: PASS.

## Protected Boundary

No existing runtime imports the module. The task adds no provider fetch,
account query, broker/order method, credential access, score/readiness/rank
change, selector or Shadow authority, service/scheduler/Engine Host/WPF wiring,
database/schema/package change, generated report, raw-evidence mutation, or
default production persistence path.

## Remaining Work

PLAN-002 production setup generation and runtime wiring remain separate. They
require serialized integration of the prerequisite stack, prospectively frozen
source/policy authority, an explicit persistence path, full risk/allocation
adapters, and a new prospective sample identity. BREAKOUT-001 remains
research-only and cannot authorize a plan through this contract.
