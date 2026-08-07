# ARGUS-R032C Automatic Candle Backfill

Status: `COMPLETE`

## Result

The Python Engine Host now keeps chart reads cache-first and schedules missing,
shallow, or market-hours-stale Schwab history behind one bounded background
worker. Repeated five-second WPF refreshes coalesce by symbol; WPF receives
loading/failure evidence and never receives credentials or calls Schwab.

## Runtime Boundaries

- The worker loads only bounded `/pricehistory` minute and Daily OHLCV through
  the existing immutable sole-account guard.
- The installed automation manifest must name this exact checkout, ending
  `2573`, and type `INDIVIDUAL_CASH` before network work can begin.
- Queue state is atomic, contains no token or account identity, permits one
  interrupted-job restart recovery, and records position/order requests as
  false with transmission `UNAVAILABLE`.
- A malformed queue state or untrusted/tampered candle partition stays locked;
  automatic loading never repairs it.
- No score, readiness, capture, scheduler, Shadow, Risk Governor, position,
  order, transmission, database/schema, credential, or legacy-candle behavior
  changed.

## Proof

- Python compileall: pass.
- Focused Python: 59 passed.
- Full Python discovery: 1,216 passed in 205.185 seconds.
- Focused .NET chart/presentation: 35 passed.
- Full .NET: 251 passed (199 presentation, 46 integration, 6 layout).
- Release WPF build: pass, zero warnings, zero errors.
- `git diff --check`: pass.
- Synthetic transition: immediate `UNAVAILABLE / LOADING HISTORY`, one worker
  writes 30 canonical minute bars, next cache read returns `AVAILABLE` with no
  duplicate provider work.
- Failure/restart/tamper: finite failure, one restart recovery, malformed state
  and tampered candle evidence fail closed.

## Installed Proof

- The stacked R032C/R034A release fast-forwarded into canonical `master`.
- The guarded Engine Host identity check replaced the stale host and returned a
  healthy snapshot on the integrated runtime.
- Previously uncached QQQ transitioned from `QUEUED` with zero candles to
  `COMPLETE` with 180 stored candles on 1m, 5m, 15m, and Daily.
- Intraday snapshots correctly reported `STALE` after hours; Daily reported
  `AVAILABLE`.
- The live run observed exactly one ending `2573` `INDIVIDUAL_CASH` account,
  requested neither positions nor orders, and kept transmission `UNAVAILABLE`.

Steven accepted the isolated 1180x820 loading/failure proof on 2026-08-06. The
right-side failure was intentionally synthetic and proved the fail-closed UI;
it was not a Schwab or production-runtime failure.
