# ARGUS-R032B Goal Charter - Schwab Historical Candle Backfill

## Goal

Give the workstation enough authoritative Schwab history to render useful 1m,
5m, 15m, and Daily charts instead of one-minute proof fragments.

## Operator Outcome

Steven can open a Hunter candidate and inspect recent price structure from a
named provider. A successful backfill supplies up to Schwab's documented
ten-day one-minute window and one year of daily OHLCV; missing depth remains a
visible failure rather than a fabricated chart.

## Scope

- Fetch bounded one-minute and daily `/marketdata/v1/pricehistory` evidence.
- Reuse the R032 ten-symbol candidate/selected/active/benchmark universe.
- Persist minute history through the existing reconciled Schwab store.
- Persist daily history in a separate source-specific, atomic Schwab store.
- Preserve corrections, duplicate idempotency, source identity, provider
  timestamps, account invariants, and write-once run evidence.
- Keep execution plan-only by default and require explicit `--execute`.

## Non-Goals

- Do not schedule or install the backfill.
- Do not connect Streamer, Engine Host, WPF, Shadow, scoring, readiness,
  selection, Risk Governor, FakeBroker, positions, orders, or transmission.
- Do not overwrite or delete Yahoo daily evidence, CRWV legacy candles, raw
  captures, reports, or SQLite rows.
- Do not accept R033 visually until it consumes the new stores and is reviewed
  again with real chart depth.

## Acceptance Criteria

- [x] Minute requests are bounded to the documented one-to-ten-day window.
- [x] Daily requests use Schwab daily price history with explicit timestamps.
- [x] Exact reruns are no-ops; corrections and A-B-A reassertions are preserved.
- [x] Fewer than 30 minute bars or 20 daily bars is explicit insufficient depth.
- [x] Tampered identity, hashes, OHLCV, timestamps, and derived state fail closed.
- [x] A writer conflict fails before account or provider access.
- [x] Plan-only CLI performs no network call and creates no store.
- [x] Legacy minute/daily sources remain byte-identical in tests.
- [x] Full Python discovery passes.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused backfill tests: 16/16 pass.
- Schwab contract/observer/collector/backfill tests: 96/96 pass.
- Final full Python discovery: 1,196/1,196 pass in 228.078 seconds.
- Plan-only CLI: pass; `networkCalled=false`, `productionDataWritten=false`.
- `git diff --check`: pass before governance closeout.
- No live provider call or production-data write was made before the Thursday
  opening capture.

## Status

`IMPLEMENTED_PENDING_LIVE_BACKFILL_AND_R033_RECONCILIATION` on
`codex/ARGUS-R032B-schwab-historical-candle-backfill`.

## Goal Steward Review

- [x] The visual failure is tied to a specific missing data capability.
- [x] Source trust and correction semantics are explicit.
- [x] Production activation and destructive cutover remain separate gates.
- [x] Tests prove depth, idempotency, failure, tamper, and nonmutation behavior.
