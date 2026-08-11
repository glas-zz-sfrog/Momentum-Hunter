# ARGUS-SHADOW-025G Runtime Evidence Chain

## Branch

`codex/ARGUS-SHADOW-025G-runtime-evidence-chain`, stacked on verified
ARGUS-SHADOW-025F head `628d555`.

## Scope

The dormant continuous-decision stack now routes candidate lifecycle,
continuous plan, runtime source-admission, and decision-cycle persistence
through one topology-bound writer session. Every operation revalidates current
host/PID/build/configuration authority and its exact topology-derived path.

Later stages require their exact upstream records: plans require the persisted
candidate event; admissions require the persisted plan plus candidate chain;
cycles require the persisted admission, plan, candidate, and matching policy.
Cross-configuration ledgers, path rebinding, missing stages, and contradictory
identities fail before a later artifact is written.

## Files Changed

- `momentum_hunter/event_runtime_evidence_chain.py`
- `momentum_hunter/event_runtime_writer_session.py`
- `tests/test_event_runtime_evidence_chain.py`
- `tests/test_event_runtime_writer_session.py`
- `tests/test_event_runtime_topology.py`
- `tests/test_event_driven_decision_cycle.py`
- Branch-local Argus governance and this release report.

## Evidence

- Compileall: pass.
- Focused evidence-chain/writer-session tests: 28 pass.
- Combined candidate/plan/admission/cycle/topology tests: 184 pass.
- Engine Host/client/automation-supervisor boundary suite: 262 pass.
- Tests affected by an invalid overlapping full-run attempt: 10 pass in a
  clean isolated rerun.
- Full Python discovery: 1,797 pass in 230.7 seconds.
- An initial short command-wrapper timeout left a concurrent child discovery
  process. Its overlapping rerun produced Windows test-directory lock errors;
  no product assertion failed. After both processes ended, the exact affected
  tests and one clean full discovery passed.
- Static capability tests prove no existing runtime imports this module and it
  has no provider, network, account, broker, order, service, or scheduler calls.
- Canonical checkout remained clean and synchronized at frozen `78db1bf`.

## Failure Modes Proved

- Plan-before-candidate, admission-before-plan, and cycle-before-admission fail
  without creating the later artifact.
- Exact restart replay continues a candidate-only prefix and creates no
  duplicate candidate, plan, admission, receipt, or cycle.
- Raw plan-store bypass cannot produce a valid admission without the candidate
  chain.
- Mixed configuration, mismatched policy, contradictory source identity,
  escaped store path, and inactive writer authority fail closed.
- Shutdown waits for an in-flight authorized append before releasing the
  process-lifetime writer lease.

## Protected Areas

No score, readiness, alert, provider, account, broker, order, Paper, Shadow,
selector, service, scheduler, Engine Host runtime, WPF, database migration,
production store, credential, raw data, generated report, or installed runtime
changed.

## Risks

The four-file chain is deliberately staged, not a distributed transaction. A
crash may leave a valid prefix; restart replays the same inputs idempotently and
continues from that prefix. Raw stores remain integrity primitives rather than
an operating-system security boundary. Actual installed-root selection,
ACL/reparse proof, constraining raw-store access, and Engine Host orchestration
remain required before activation.

Candidate ledger records do not carry a separate program/configuration header;
the topology path and the downstream plan/admission configuration bind the
chain. The later installed-root/namespace boundary must prevent copied raw
candidate prefixes from bypassing this topology.

## Manual QA

None. This is nonvisual dormant evidence infrastructure.

## Recommendation

Preserve Tuesday's terminal opening and Paper evidence. Then reconcile the
stacked continuous branches in dependency order before selecting an installed
root or activating Engine Host orchestration.

## Classification

`IMPLEMENTED_PENDING_MERGE`
