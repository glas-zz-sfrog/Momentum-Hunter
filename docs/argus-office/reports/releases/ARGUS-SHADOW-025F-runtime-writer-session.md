# ARGUS-SHADOW-025F Runtime Writer Session

## Branch

`codex/ARGUS-SHADOW-025F-runtime-writer-session`, stacked on verified
ARGUS-SHADOW-025E head `0b60eef`.

## Scope

The dormant continuous-decision stack now has a single-use writer session that
composes 025D's exact Engine Host writer claim with a process-lifetime OS lease
and 025E's append-only source-admission store. Authority is revalidated at each
append, including current PID and host identity, runtime build, configuration,
topology, append permission, and exact topology-derived path.

Source-admission schema v2 adds configuration identity. Ledger schema v2 adds
evidence-program and configuration identity plus one fingerprint over the
header and complete ordered admission chain. A store cannot be constructed
without an explicit namespace, and a relabeled, reordered, edited, or
cross-configuration ledger fails closed.

## Files Changed

- `momentum_hunter/event_runtime_writer_session.py`
- `momentum_hunter/event_source_admission.py`
- `tests/test_event_runtime_writer_session.py`
- `tests/test_event_runtime_topology.py`
- `tests/test_event_source_admission.py`
- Branch-local Argus governance and this release report.

## Evidence

- Compileall: pass.
- Focused source-admission/writer-session tests: 43 pass.
- Candidate/plan/topology/Engine Host/client/service tests: 248 pass.
- Full Python discovery: 1,783 pass in 228.4 seconds.
- One initial adjacent command named a nonexistent historical test module;
  the corrected repository test targets passed 248/248.
- `git diff --check`: pass before documentation closeout.
- Changed-file credential-shaped scan: no hit before documentation closeout.
- Static network, provider, account, broker, order, service, scheduler, runtime,
  and implicit-root capability review: pass.
- Canonical checkout remained clean and synchronized at frozen `78db1bf`.

## Failure Modes Proved

- Wrong PID, wrong host, stale/tampered claim, wrong configuration, denied
  topology access, and escaped store path fail before persistence.
- A second local session cannot reenter the lifetime lease.
- Concurrent activation of the same single-use session cannot reuse it after
  the first activation closes.
- A replacement process times out finitely while the owner is active and can
  acquire after release.
- Process exit releases OS ownership without deleting the sidecar.
- Exact duplicate append is byte-stable; conflicting or orphan evidence fails
  without ending the valid session.
- Header, namespace, ordered-chain, and admission tampering are detected.

## Protected Areas

No score, readiness, alert, provider, account, broker, order, Paper, Shadow,
selector, service, scheduler, Engine Host runtime, WPF, database migration,
production store, credential, raw data, generated report, or installed runtime
changed.

## Risks

The session is deliberately dormant and no installed module imports it. Actual
root selection, filesystem ACL/reparse proof, Engine Host startup/importer
wiring, and orchestration of candidate/plan/admission/cycle stores remain future
work. The raw store is an integrity primitive, not an operating-system security
boundary; installed orchestration and ACLs must ensure runtime writes pass
through the writer session.

## Manual QA

None. This is nonvisual dormant evidence infrastructure.

## Recommendation

Preserve Tuesday's terminal opening and Paper evidence. Then reconcile the
stacked continuous branches in dependency order before selecting an installed
root or activating Engine Host orchestration.

## Classification

`IMPLEMENTED_PENDING_MERGE`
