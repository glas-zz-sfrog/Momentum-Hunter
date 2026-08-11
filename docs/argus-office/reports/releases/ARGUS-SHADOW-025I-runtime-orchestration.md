# ARGUS-SHADOW-025I Runtime Orchestration

## Branch

`codex/ARGUS-SHADOW-025I-runtime-orchestration`, stacked on verified
ARGUS-SHADOW-025H head `4e61865`.

## Scope

The dormant continuous-decision stack now has one explicit orchestration
transaction over candidate lifecycle, continuous plan, runtime source
admission, and decision-cycle evidence. The caller must supply every immutable
record; the orchestrator does not discover a candidate, build a plan, evaluate
risk, allocate capital, or create a decision.

After acquiring the current topology-bound process-lifetime writer lease, the
transaction inspects the current valid prefix, builds an in-memory preview of
the exact proposed chain, and only then replays each stage in order. Exact
replay is byte-stable. A valid interrupted prefix resumes, while invalid
identity, chronology, policy, configuration, or writer authority fails closed.

## Files Changed

- `momentum_hunter/event_runtime_orchestration.py`
- `tests/test_event_runtime_orchestration.py`
- Narrow dormant-import allowlist updates in four existing runtime tests.
- Branch-local Goal Charter, Roadmap, branch/task/changelog/risk records, and
  this release report.

## Evidence

- Compileall: pass.
- Focused orchestration tests: 14 pass.
- Topology/writer/chain/recovery/orchestration/cycle tests: 126 pass.
- Candidate/plan/admission/runtime/intraday/allocation boundary: 266 pass.
- Full Python discovery: 1,830 pass in 232.92 seconds.
- `git diff --check`: pass.
- Protected-path, credential-pattern, and forbidden-capability scans: pass.
- Static tests prove no existing runtime imports the orchestrator and it has no
  provider, network, account, broker, order, service, scheduler, or host-start
  capability.
- Canonical checkout remained clean and synchronized at frozen `78db1bf`.

## Failure Modes Proved

- Partial candidate batches plus candidate-only, plan-only, and admission-only
  crash prefixes resume at the next stage without duplicating evidence.
- A fully completed exact request replays as `DUPLICATE_REPLAY` without changing
  any evidence artifact byte.
- A decision bound to a different plan and invalid cycle chronology fail before
  the first evidence artifact write.
- A stale/wrong process claim cannot acquire writer authority or write evidence.
- Result-fingerprint tampering fails validation.
- Completing one exact target does not conceal an unrelated pending successor
  plan in the after-snapshot.

## Protected Areas

No score, readiness, alert, provider, account, broker, order, Paper, Shadow,
selector, service, scheduler, Engine Host runtime, WPF, database migration,
production store, credential, raw data, generated report, or installed runtime
changed.

## Risks

The transaction is dormant and has no installed importer. Its in-memory preview
prevents invalid requests from partially writing evidence, while an actual disk
failure between valid stage appends still leaves a deliberately recoverable
prefix rather than a four-file atomic commit. Installed-root selection,
ACL/reparse/raw-store confinement, current-host composition, and production
restart proof remain required before activation.

## Manual QA

None. This is nonvisual dormant evidence infrastructure.

## Recommendation

Preserve Tuesday's terminal opening and Paper evidence. Then reconcile the
stacked continuous branches before selecting an installed root or importing
this transaction into Engine Host runtime.

## Classification

`IMPLEMENTED_PENDING_MERGE`
