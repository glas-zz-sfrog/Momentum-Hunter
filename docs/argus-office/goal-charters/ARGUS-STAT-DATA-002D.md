# ARGUS-STAT-DATA-002D Goal Charter

## Objective

Prove the frozen STAT-DATA canary through its exact `run-all` orchestration by
substituting only the external provider boundary with accepted, hash-bound
Finviz and Schwab evidence from the reviewed Producer-001D/001E V4 packet.

## Authorized Scope

- Add a read-only `OFFLINE_PRESERVED_PROVIDER_REPLAY` boundary for discovery,
  current quotes, and historical candle stores.
- Preserve original provider timestamps, receipt timestamps, `knownAt` values,
  session identity, and source hashes.
- Exercise canonical discovery, hot-universe, readiness, composition,
  prospective denominator, writer, restart, verification, and packaging paths.
- Record that the replay creates no new prospective live-market observation.

## Prohibited Changes

Do not alter denominator definitions, discovery policy, readiness semantics,
composition or TradePlan behavior, Paper, Shadow, broker/account/position/order
authority, installed services, production manifests, canonical Git, or Monday
schedules.

## Acceptance

1. The exact wrapper `run-all` path completes with at least one prospective
   replay member and membership/outcome accounting reconciles.
2. No credential, network, account, position, Paper, Shadow, broker, or order
   path is requested.
3. Replay records bind the reviewed provider packet and every selected source
   entry by SHA-256.
4. Runtime restart, writer persistence, analyzer verification, pre-ZIP tests,
   manifest verification, and extracted-ZIP tests pass.
5. The resulting packet is sanitized and self-contained for second-eye review.

## Stop Gate

No merge, deployment, promotion, repin, or live prospective activation is
authorized. Seal Package A and stop Phase A for its serial opening-runtime
successor proof.
