# ARGUS-SPECIALIST-CONTRACT-001 Goal Charter

## Goal Statement

Create one immutable, deterministic common packet through which independent
specialists can publish bounded research opinions without gaining execution or
strategy authority.

## User Pain / Operator Outcome

Momentum Hunter can compare specialist research without collapsing unlike
signals into a universal score, mistaking abstention for opposition, losing
evidence lineage, or allowing an analytical component to influence trading.

## In Scope

- Pure Python frozen opinion, evidence-reference, and confidence models.
- Canonical JSON, SHA-256 identities, strict validation, and tamper detection.
- Exact opportunity/candidate/setup/TradePlan target validation.
- `EVALUATED`, `ABSTAINED`, and `FAILED` semantics.
- Research-only authority, feature-family disclosure, bounded reason codes,
  reference fixtures, and adversarial tests.

## Out Of Scope

- Providers, accounts, brokers, orders, files, databases, runtime wiring,
  service/scheduler/Engine Host/WPF changes, specialist algorithms, opinion
  combination, Meta-Arbiter logic, strategy changes, and activation.

## Protected Areas

No protected runtime semantics are changed. Existing scoring, readiness,
TradePlan, Risk Governor, allocation, Paper, Shadow, broker/order, replay,
SETUP-002, credentials, production data, installed service, manifest, and
August 17 jobs remain unchanged. Any request to grant a specialist authority
or wire the contract into runtime requires a separate task and prospective
sample identity.

## Acceptance Criteria

- [x] Contract object is immutable, deterministic, versioned, and JSON-safe.
- [x] Evidence, policy, target, specialist version, and authority are identity
  bound and tampering is rejected.
- [x] Abstention and failure cannot masquerade as evaluated opinions.
- [x] Confidence cannot imply probability without calibrated semantics.
- [x] Existing Momentum Hunter opportunity/setup/TradePlan IDs interoperate.
- [x] No capability or existing runtime import is introduced.
- [x] Focused and bounded regression tests pass.
- [x] Full discovery and final protected-lane verification pass.

## Evidence Required

- Compileall, focused contract tests, DATA-003/004 identity regressions,
  evidence-integrity regressions, SETUP-002 nonmutation regressions, full
  Python discovery, diff/secret/capability scans, and canonical checkout plus
  installed-manifest nonmutation proof.

## Evidence Depth / Hard Chew Requirements

- Exercise four reference specialist packets and negative cases for malformed
  identity, future/stale chronology, unsupported authority, fake confidence,
  duplicate/contradictory evidence, wrong setup, expiration, and tampering.
- Prove canonical serialization across reordered inputs.
- Review every changed path and rerun the focused suite after self-review.
- Record exact branch/commit/test/push state; do not claim integration.

## Smallest Safe Implementation Slice

One isolated module, one focused test module, one architecture note, and
branch-local governance records. No consumer or persistence path is added.

## Open CEO Decisions

- None. Future authority or Meta-Arbiter behavior is explicitly deferred.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove the requested outcome.
- [x] Evidence required is strong enough to verify completion.
