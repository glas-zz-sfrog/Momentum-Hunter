# Goal Charter: ARGUS-CONTINUOUS-PRODUCER-001C-FORENSIC-CANARY

## Objective

Physically prove the repaired Producer-001C natural path with real Finviz and
Schwab market evidence, then package a sanitized self-contained packet for
independent review.

## Boundaries

- The provider wrapper is observational only. Canonical production classes own
  discovery, admission, readiness, material events, composition, and records.
- A separate deterministic harness uses production runtime/composition classes
  to prove failed-staging nonmutation, append-only failure evidence, restart,
  one valid commit, and idempotent duplicate replay.
- Runtime state is disposable under `%TEMP%`; durable evidence uses one new
  immutable ArgusReviewBundles identity.
- Account values, positions, Paper, Shadow, broker access, and orders remain
  unavailable.

## Acceptance

- The exact clean Producer-001C product commit and task head pass preflight.
- Real provider discovery, Schwab history/readiness, at least one valid
  completed-bar dispatch, accepted composition, and natural no-plan or
  TradePlan evidence are preserved.
- Zero premature completed-bar events occur.
- One accepted composition exists before restart and one natural processing
  cycle succeeds after restart without duplication.
- Append-only attempts, truthful counters, exact chronology, physical
  atomicity, nonmutation, and secret scans pass.
- The extracted ZIP verifies its manifest and reruns the focused suite from
  packaged source.
- Every terminal provider outcome requires a sanitized second-eye ZIP. A
  no-candidate/no-ready market, provider failure, phase failure, failed
  acceptance gate, or failed focused verification remains failed evidence but
  does not suppress packaging.
- Missing acceptance artifacts are inventoried exactly. They are not
  synthesized, backfilled, or converted into passing evidence.

## Hard Stop

No merge, deployment, Paper reconciliation, STAT-DATA-002 work, or execution
authority is authorized. Stop after the second-eye ZIP is produced and its
manifest, sanitization, and extracted focused-verification results are reported,
regardless of whether provider acceptance passed or failed.
