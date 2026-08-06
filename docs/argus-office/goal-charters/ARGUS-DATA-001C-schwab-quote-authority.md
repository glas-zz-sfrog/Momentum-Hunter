# ARGUS-DATA-001C Goal Charter - Schwab TradePlan Quote Authority

## Goal

Replace the unsupported Yahoo Finance quote enrichment with the existing
read-only Schwab quote boundary so TradePlan execution-price authority is
explicit, fresh, source-bound, and fail-closed.

## Operator Outcome

Steven can distinguish research tape from an execution-eligible price. A visible
Nasdaq or Yahoo chart value cannot silently become a trusted entry, stop, target,
or readiness input merely because a separate provider request failed.

## Scope

- Request one bounded Schwab quote batch for the report's candidate symbols.
- Reuse canonical Schwab quote parsing and regular-market proof logic.
- Require exact symbol/source, real-time, regular-session, tradable, fresh,
  finite positive last/bid/ask, valid spread, provider clocks, and HTTPS clock
  proof before granting execution-price authority.
- Preserve Nasdaq and Yahoo chart evidence as research-only fallback.
- Retire the unsupported Yahoo Finance v7 quote request prospectively.
- Reapply the same price, plan, and catalyst authority gates after Active
  Monitor refresh.

## Non-Goals

- Do not change scoring weights, ranking formulas, alert thresholds, TradePlan
  formulas, position sizing, Risk Governor semantics, or Shadow sample state.
- Do not add account, position, order, preview, cancellation, replacement, or
  transmission methods.
- Do not change database/schema, packages, credentials, UI, scheduler, service,
  Engine Host, candle collection, raw captures, or historical reports.
- Do not claim that a valid price alone makes a hypothetical plan executable.

## Acceptance Criteria

- [x] One report batches all requested candidate symbols through Schwab.
- [x] Only a fully validated Schwab quote can become execution-price-authoritative.
- [x] Stale, reused, delayed, extended-session, missing-last, malformed, wrong-
  symbol, failed-clock, and authorization-failure evidence remains blocked.
- [x] Research fallback remains visible but never inherits Schwab authority.
- [x] Active Monitor cannot promote research-only evidence to execution-ready.
- [x] No runtime request targets Yahoo Finance v7 quote enrichment.
- [x] Source capture/report inputs remain unmodified.
- [x] Full test discovery passes and protected capabilities remain absent.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused TradePlan/Schwab/monitor tests: 44/44 pass.
- Adjacent evidence, Shadow, capture, monitor, and transport tests: 159/159 pass.
- Full Python discovery: 1,179/1,179 pass.
- `git diff --check`: pass.
- URL scan: no runtime `/v7/finance/quote` request remains.
- Protected-path review: only the explicitly authorized price/readiness authority
  boundary changed; no score weight, alert threshold, account/order, broker
  transmission, database/schema, package, UI, or generated-data path changed.
- Secret scan: no secret value or credential material added.
- Live-provider proof: not invoked; all new tests use injected synthetic sources.

## Status

`COMPLETE`, integrated, backed up, and exact-head repinned through
implementation commit `17e5b50` plus its final governance closeout.

## Goal Steward Review

- [x] The operator value and fail-closed behavior are concrete.
- [x] The protected readiness semantic is explicitly authorized by Steven.
- [x] Tests prove behavior and negative paths rather than label existence.
- [x] No visual acceptance item is required because no UI changed.
