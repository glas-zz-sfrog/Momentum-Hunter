# ARGUS-R032C Automatic Candle Backfill

Status: `IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE_AND_MERGE`

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

## Remaining Gates

1. Steven checks the visible loading/failure wording and layout.
2. Commit and push the feature branch.
3. Fast-forward into canonical `master` and repin future capture jobs.
4. Use one elevated reload so the installed Engine Host runs the integrated
   code.
5. Select one previously uncached liquid symbol and prove live transition to
   populated 1m/5m/15m/Daily Schwab history without account/order activity.
