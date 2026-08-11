# ARGUS-SHADOW-025E Source Admission Ledger

## Branch

`codex/ARGUS-SHADOW-025E-source-admission-ledger`, stacked on verified
ARGUS-SHADOW-025D head `c273aaa`.

## Scope

The dormant continuous-decision stack can now preserve each 025C source
admission in a deterministic append-only JSON ledger. The caller must provide
the path; this task does not select an installed or production root.

One shared path-transaction utility now supplies the finite, reentrant,
cross-process lease previously embedded in the event-cycle store. The old store
retains its domain-specific errors and behavior. The new admission store holds
that same lease around the complete load, validation, append, and atomic replace
transaction.

## Files Changed

- `momentum_hunter/path_transaction.py`
- `momentum_hunter/event_driven_decision_cycle.py`
- `momentum_hunter/event_source_admission.py`
- `tests/test_event_source_admission.py`
- Branch-local Argus governance and this release report.

## Evidence

- Compileall: pass.
- Focused source-admission and event-cycle tests: 68 pass.
- Candidate/plan/topology/Engine Host/service-supervisor tests: 221 pass.
- Full Python discovery: 1,766 pass in 231.8 seconds.
- `git diff --check`: pass.
- Credential-shaped value scan: no hit.
- Static network, provider, account, broker, order, service, scheduler, runtime,
  and implicit-root capability review: pass.
- Canonical checkout: clean and synchronized at frozen `78db1bf` throughout.

## Failure Modes Proved

- Exact replay returns the same record and leaves canonical bytes unchanged.
- A successor cannot be written before its exact predecessor admission.
- Duplicate plan/source identities, contradictory lineage, regressed chronology,
  malformed schemas, and record tampering fail closed.
- Atomic replacement failure leaves the previous ledger readable and unchanged.
- Two Windows processes preserve distinct simultaneous appends.
- Contention times out finitely and recovers after ordinary release.
- OS ownership is released after a process exits while holding the lease.

## Protected Areas

No score, readiness, alert, provider, account, broker, order, Paper, Shadow,
selector, service, scheduler, Engine Host, WPF, database/schema, production
store, credential, raw data, generated report, or installed runtime changed.

## Risks

The actual installed root, filesystem ACL/reparse proof, startup topology/writer
claim composition, admission-store wiring, and Engine Host orchestration remain
future tasks. This branch creates no production artifact and cannot participate
in Tuesday's scheduled opening or Paper cycle.

## Manual QA

None. This is nonvisual dormant evidence infrastructure.

## Recommendation

Preserve Tuesday's terminal opening and Paper evidence. Then reconcile and
integrate the continuous stack in dependency order before selecting the actual
root or wiring the Engine Host orchestration loop.

## Classification

`IMPLEMENTED_PENDING_MERGE`
