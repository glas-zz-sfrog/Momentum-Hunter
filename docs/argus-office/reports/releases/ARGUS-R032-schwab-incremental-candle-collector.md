# ARGUS-R032 Schwab Incremental Candle Collector

Status: `COMPLETE`

## Scope

R032 adds a manually invoked, bounded Schwab one-minute candle collector and a
separate evidence store. It does not schedule collection or activate Engine
Host, WPF, Shadow, scoring/readiness, selection, FakeBroker, or broker/order
behavior. The legacy CRWV JSON and SQLite mirror remain untouched for R034.

## Implementation

- Resolves an exact-date opening universe from selected and active symbols, the
  top five Hunter candidates, SPY, and IWM under a hard ten-symbol ceiling.
- Rejects stale/wrong-session reports, invalid or duplicate rank/symbol
  identity, malformed Shadow inputs, and ambiguous source evidence.
- Persists each `CHART_EQUITY` version immediately in daily/symbol partitions.
- Reconciles completed minutes against `/pricehistory`, which becomes the
  canonical version while stream versions and corrections remain preserved.
- Classifies `IN_PROGRESS`, `COMPLETED_UNRECONCILED`, `RECONCILED`, `CORRECTED`,
  and `HISTORY_ONLY_GAP_FILL` states without inventing finality.
- Uses an operating-system-held writer lease, atomic replacement, bounded file
  sizes, semantic SHA-256 identities, strict schema validation, current-session
  health, and write-once run results.
- Defaults to a plan-only CLI. Live execution requires the explicit `--execute`
  switch and guarded validation of the sole expected account.

## Exact-Code Live Proof

- Path: `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-R032-live-collector-proof-20260805-v3`
- Session: extended hours, 60 seconds.
- Universe: SPY, IWM, NVDA, SHOP, and ZETA.
- Stream: `PASS`, eight persisted versions, all five symbols observed.
- Price history: `PASS`, 13 persisted versions, every observed stream minute
  represented by history.
- Overall: `PARTIAL`, intentionally, because SPY, SHOP, and ZETA contained one
  visible sparse-market gap apiece.
- Result SHA-256: `F29ECCAB3D7AE5C883202CC194F088EE1A5D693F3533FB81418FEB65510A8DE9`.
- Manifest SHA-256: `99DE3728270C8722D41E0FD840C2703FCF5E7B88303E6A8B369738AB7D6A2BBE`.
- Secret scan: zero hits.

An earlier proof correctly exposed and drove repair of stale-health masking;
the preserved v3 proof is from the final patched code. The expected sole account
ending `2573`, type `INDIVIDUAL_CASH`, passed guarded identity revalidation.
No positions or orders were requested. Transmission remained `UNAVAILABLE`.

## Verification

- Python compileall: pass.
- Focused R032 tests: 30/30 pass.
- Full Schwab candle stack: 89/89 pass.
- Full Python discovery: 1,173/1,173 pass in 237.176 seconds.
- `git diff --check`: pass.
- Source nonmutation: the August 5 report remains
  `5945EBBEDC2E62004716632A371BBDE49ADAFAAB51171FB5FC1EBA00ECE9DBE0`;
  the legacy candle JSON remains
  `DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69`.
- Protected-path review: no score, readiness, selection, TradePlan, Shadow,
  broker/order, service/scheduler, Engine Host, WPF, database/schema, package,
  environment, raw-capture, or legacy-candle behavior changed.

## Next

R033 may expose the versioned snapshot through Engine Host and render it in WPF.
It must preserve source, provisional/canonical state, gaps, stale state, and
corrections. R034 remains the separately approved destructive legacy cutover.
