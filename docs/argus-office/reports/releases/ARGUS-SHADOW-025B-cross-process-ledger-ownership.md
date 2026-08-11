# ARGUS-SHADOW-025B Cross-Process Ledger Ownership

## Branch

`codex/ARGUS-SHADOW-025B-cross-process-ledger-ownership`, based on verified
ARGUS-CONTINUOUS-002 head `657cb37`.

## Scope

The dormant event-cycle ledger now uses a deterministic sidecar file lease for
the complete read/validate/append/atomic-write transaction. Direct saves use the
same ownership boundary. The lease is finite, reentrant in one thread, preserved
on disk rather than unlinked, and released by the operating system when a
process exits.

## Files Changed

- `momentum_hunter/event_driven_decision_cycle.py`
- `tests/test_event_driven_decision_cycle.py`
- Branch-local Argus governance and this release report.

## Evidence

- Compileall: pass.
- Focused event-cycle tests: 42 pass.
- PLAN/BREAKOUT/event-cycle contracts: 98 pass.
- Combined continuous evidence: 268 pass.
- Allocation/Paper/Shadow/candle boundaries: 130 pass.
- Full Python discovery: 1,717 pass.
- `git diff --check`: pass.
- Static network/broker/runtime capability scan: pass.
- Credential-shaped value scan: no credential found.
- Changed-path review: no installed service, scheduler, provider, account,
  order, WPF, production store, package, schema, or generated-data path.

## Failure Modes Proved

- Two Windows processes cannot lose one another's concurrent append.
- A contending process fails after a finite configured timeout.
- A normal lease release permits a later writer.
- A process exiting while it owns the lease does not strand ownership.
- Invalid zero, negative, infinite, or NaN timeouts fail closed.

## Protected Areas

No execution, provider, account, allocation, scoring, readiness, selector,
Paper, or Shadow semantics changed. The contract remains unimported by runtime
and uses only explicit caller-provided paths.

## Risks

Local Windows filesystem behavior is directly tested. Network-share locking
semantics are not claimed and should not be used for the installed ledger
without separate proof. Runtime source selection and the canonical installed
path remain future prospective decisions.

## Manual QA

None. This is nonvisual synthetic persistence infrastructure.

## Recommendation

Preserve Tuesday's operational evidence first. Then reconcile this successor
branch against canonical master and integrate the continuous contract stack in
one serialized window before any runtime SHADOW-025 source/path wiring.

## Classification

`IMPLEMENTED_PENDING_MERGE`
