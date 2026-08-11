# ARGUS-SHADOW-025H Runtime Recovery Planner

## Branch

`codex/ARGUS-SHADOW-025H-runtime-recovery-planner`, stacked on verified
ARGUS-SHADOW-025G head `576aef9`.

## Scope

The dormant continuous-decision stack now has a read-only recovery planner for
the four-stage candidate, plan, source-admission, and decision-cycle evidence
chain. It independently validates each ledger and all cross-ledger bindings,
then returns a deterministic fingerprinted snapshot naming exact pending and
completed identities.

Valid states distinguish no evidence, candidate observation waiting for a
plan, plan waiting for source admission, admission waiting for a cycle receipt,
multiple independent pending stages, and a fully receipted chain. The reported
action is an orchestration label only; the planner contains no method that
performs the action.

## Files Changed

- `momentum_hunter/event_runtime_recovery.py`
- `momentum_hunter/event_runtime_evidence_chain.py`
- `tests/test_event_runtime_recovery.py`
- `tests/test_event_runtime_evidence_chain.py`
- `tests/test_event_runtime_topology.py`
- `tests/test_event_driven_decision_cycle.py`
- Branch-local Argus governance and this release report.

## Evidence

- Compileall: pass.
- Focused recovery tests: 19 pass.
- Recovery/evidence-chain/writer-session tests: 47 pass.
- Candidate/plan/admission/cycle/topology/Engine Host/client/service boundary:
  281 pass.
- Full Python discovery: 1,816 pass in 234.5 seconds.
- `git diff --check`: pass before documentation closeout.
- Static tests prove no existing runtime imports the planner and it has no
  provider, network, account, broker, order, service, scheduler, repair, or
  ledger-append capability.
- Canonical checkout remained clean and synchronized at frozen `78db1bf`.

## Failure Modes Proved

- Candidate-only, plan-only, admission-only, mixed partial, and complete valid
  prefixes receive distinct deterministic classifications.
- Raw plan evidence without its candidate chain fails closed.
- A receipt/cycle with its admission removed fails closed.
- Cross-program source-admission evidence and malformed JSON fail closed with a
  redacted error.
- Direct handcrafted unvalidated ledgers are rejected by the public prefix
  validator.
- A re-fingerprinted snapshot with a contradictory status/action pair is
  rejected by deriving the expected classification from its recorded counts.
- An artifact change between pre-read and post-read hashes invalidates the
  inspection rather than returning mixed counts and hashes.
- Repeated inspection is deterministic and changes no source byte.

## Protected Areas

No score, readiness, alert, provider, account, broker, order, Paper, Shadow,
selector, service, scheduler, Engine Host runtime, WPF, database migration,
production store, credential, raw data, generated report, or installed runtime
changed.

## Risks

The planner identifies the next stage but deliberately cannot execute it. A
later Engine Host orchestrator must revalidate current writer authority after
inspection and before any append. Double hashing detects an artifact changed
during inspection, but installed-root ACL/reparse/raw-store confinement remains
required before activation. This synthetic work does not prove recovery against
the installed service or production evidence directory.

## Manual QA

None. This is nonvisual dormant evidence infrastructure.

## Recommendation

Preserve Tuesday's terminal opening and Paper evidence. Then reconcile the
stacked continuous branches before installed-root selection, filesystem proof,
or Engine Host orchestration.

## Classification

`IMPLEMENTED_PENDING_MERGE`
