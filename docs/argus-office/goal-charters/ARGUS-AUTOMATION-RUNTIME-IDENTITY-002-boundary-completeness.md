# Goal Charter: ARGUS-AUTOMATION-RUNTIME-IDENTITY-002

## Goal

Prove whether the production-approved opening runtime identity is complete and
appropriately scoped: unrelated development should remain decoupled, while
every code, configuration, environment, launcher, and loaded-process boundary
capable of changing the unattended 08:35 opening must fail closed.

## Operator Value

Steven can continue ordinary documentation, research, and presentation work
without repinning future openings, while a real opening-runtime change still
requires explicit qualification and promotion.

## Scope

- Read-only production identity and Monday readiness reconciliation.
- Static opening import/dependency analysis and dynamic-loading audit.
- Disposable mutation, import-escape, configuration, dependency, and realistic
  development-sequence proofs.
- Tests, audit tooling, ADR/release/governance documentation.
- A narrow infrastructure correction only if a current unsafe omission is
  proven and Monday can remain protected.

## Exclusions

- Candidate, scoring, ranking, TradePlan, Risk Governor, allocation, Paper,
  Shadow, broker, provider, market-data, opening timing, or order semantics.
- Production provider/account calls, captures, runtime evidence mutation, and
  the active thinkorswim RTD worktree or campaign evidence.

## Acceptance

Done means the actual dependency boundary, broadness, import-escape behavior,
dynamic loading, configuration, environment, interpreter, launcher, and loaded
service-byte guarantees are explicitly proven; the mutation matrix and Hard
Chew pass; the production impact is stated without overclaiming; and Monday
August 24 remains pending at 08:35/08:40 CT with a matching approved runtime,
15 future openings, a fresh service heartbeat, zero Shadow/Paper jobs, and
unavailable order transmission.

## Starting Classification

`ACTIVE / PRODUCTION_READ_ONLY`

## Qualification Result

`BOUNDARY_SAFE_BUT_OVERBROAD / ENVIRONMENT_BOUNDARY_OVERBROAD /
IMPLEMENTED_PENDING_MERGE`

The actual opening graph is contained, has zero local import escapes and zero
dynamic-loading sites, and remains protected by the active conservative V1
release. The audit adds offline fail-closed qualification checks for future
outside-root imports and dynamic loading. No production fingerprint semantics
were changed before Monday. Full Python discovery passes 2,723 tests with one
expected non-elevated symlink skip.
