# ARGUS-R034A Goal Charter - Legacy Candle Consumer Migration

## Goal

Make deletion of the retired CRWV minute-bar cache independently safe to plan
by moving every active default consumer to reconciled Schwab evidence or an
explicit retired-source state, while implementing no destructive action.

## Operator Outcome

Momentum Hunter no longer depends on `opportunity-minute-bars.json` for active
outcomes, health, research, read models, Daily symbol discovery, or SQLite
freshness/validation. Steven receives an exact, nonmutating R034 deletion plan
only after every dependency is proven absent.

## Scope

- Read only terminal, price-history-backed Schwab minute partitions.
- Retain explicit JSON fixtures for historical/synthetic tests.
- Block writes to the exact production legacy path.
- Retire the old Yahoo minute-fetch compatibility path.
- Mark the legacy SQLite mirror intentionally retired without changing schema
  or deleting rows.
- Inventory remaining source references and validate exact JSON/SQLite hashes,
  counts, Schwab-store health, archive destination, and rollback conditions.
- Version prospective report producers whose default source contract changed.

## Non-Goals

- Do not archive, delete, rewrite, repair, or normalize legacy JSON or SQLite.
- Do not change scoring, readiness, replay, selection, Risk Governor, TradePlan,
  capture, scheduling, service, WPF, account, position, order, or transmission
  behavior.
- Do not treat Streamer-only/provisional bars as canonical outcomes.
- Do not delete or migrate `daily-ohlc-bars.json`.
- Do not contact Schwab, Yahoo, another provider, an account, or a broker.

## Acceptance Criteria

- [x] Active default consumers use reconciled Schwab minute partitions or an
  explicit retired-source state.
- [x] The production legacy JSON cannot be recreated by outcome maintenance.
- [x] Explicit synthetic/historical fixture behavior remains testable.
- [x] Stream-only evidence cannot become canonical outcome/research evidence.
- [x] SQLite all-safe migration does not import the retired cache.
- [x] A read-only verifier reports exact legacy and SQLite identities, canonical
  replacement health, source references, archive location, and rollback rules.
- [x] The verifier changes no source, database, provider, account, order, or
  runtime state.
- [x] Historical outputs remain untouched and Daily research remains out of
  scope.
- [x] Focused, full Python, and full .NET regression proof passes.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused consumer/cutover suite: 44/44 pass.
- Full Python discovery: 1,225/1,225 pass in 267.409 seconds.
- Full .NET solution: 251/251 pass (199 presentation, 46 integration, 6
  layout).
- Actual plan-only verifier: `READY_FOR_DESTRUCTIVE_APPROVAL` with 710 CRWV
  JSON bars, 710 matching/710 total SQLite rows, 12,478 healthy canonical
  Schwab bars, zero blocking references, and unchanged inputs.
- `git diff --check`: pass.
- Secret-value scan: zero hits.
- Added network/account/order capability scan: zero hits.
- Protected-path review: no scoring, readiness, replay, broker/order,
  database-schema, package, credential, or UI change.

## Status

`IMPLEMENTED_PENDING_MERGE` on
`codex/ARGUS-R034A-legacy-candle-consumer-migration`.

## Goal Steward Review

- [x] The task removes a proven destructive-cutover dependency.
- [x] Source authority is explicit and fail-closed.
- [x] The destructive R034 action remains a separate Steven decision.
- [x] Evidence proves consumer behavior, nonmutation, and capability absence.
