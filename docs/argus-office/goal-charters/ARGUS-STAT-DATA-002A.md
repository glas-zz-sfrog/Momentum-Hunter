# ARGUS-STAT-DATA-002A Goal Charter

## Objective

Repair the confirmed activation JSON round-trip type mismatch and ensure every
post-prepare pre-provider failure produces truthful terminal evidence and a
mandatory sanitized second-eye package.

## Authorized Scope

- Normalize a persisted JSON population array to the canonical immutable tuple
  before strict activation validation.
- Preserve exact order, membership, activation identity, and record fingerprint.
- Move post-prepare invariants inside failure-aware terminal accounting.
- Distinguish provider-path attempt from observed provider evidence.
- Add deterministic tests and an offline exact-path rehearsal.
- Run one new natural regular-session canary only after all offline proof passes.

## Prohibited Changes

Do not change population definitions, denominator semantics, discovery,
readiness, scoring, ranking, TradePlans, providers, Paper, Shadow, broker,
account, position, order, service, scheduler, or canonical production behavior.

## Acceptance

1. Exact ordered JSON population arrays reload as the canonical tuple.
2. Reordered, missing, extra, duplicate, malformed, or non-string populations
   fail closed.
3. Activation ID and fingerprint survive the JSON round trip unchanged.
4. The preserved failed activation reloads without mutation.
5. Every failure after preparation writes `terminal-result.json` with truthful
   provider-contact and zero-observation accounting where applicable.
6. `run-all` packages terminal failure and returns failure.
7. Offline rehearsal, focused tests, full discovery, compile, scans, and
   protected-boundary checks pass before provider contact.
8. Every terminal live-canary outcome produces a sanitized verified ZIP and
   stops for independent review.
