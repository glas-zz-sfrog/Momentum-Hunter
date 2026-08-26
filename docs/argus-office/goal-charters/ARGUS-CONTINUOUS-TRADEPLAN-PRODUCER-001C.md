# Goal Charter: ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001C

## Objective

Repair canonical instant identity, completed-bar finality, append-only attempt
forensics, truthful stage accounting, and complete Producer restart continuity
without adding execution authority.

## Starting Identity

- Canonical base: `82460b3313b86c34dff4ffb737d2c04bf02e3ace`.
- Stacked parent: Producer-001B head
  `6b64c6f4dd601708a035e2bc93fc3e768156301f`.
- Branch: `codex/ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001C`.
- Authority: `RESEARCH_ONLY`; order capability: `UNAVAILABLE`.

## Acceptance

- Equivalent timezone-offset representations bind to one canonical UTC instant;
  malformed, naive, different, or future-known timestamps fail closed.
- A completed-bar event requires a price-history version first received at or
  after the one-minute interval end and no later than the decision cutoff.
- Every readiness/composition attempt and failure is append-only across restart;
  latest-symbol status is a linked projection rather than the evidence source.
- Repeated assessments and unique symbols, provisional and completed bars,
  dispatched and accepted events, and attempted/failed/accepted compositions
  remain distinct.
- Failed staged composition leaves authoritative stores byte-identical; a valid
  composition commits once and survives restart without duplication.
- Prior Producer-001A/001B failed evidence remains byte-identical.
- Hard Chew and one fresh exact-head provider canary pass before a new
  self-contained second-eye ZIP is sealed.

## Hard Stop

Do not merge, deploy, activate STAT-DATA-002, reconcile Continuous Paper, query
accounts or positions, or expose any broker/order capability. Stop after the
new second-eye packet for independent review.
