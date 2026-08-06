# ARGUS-R032B Schwab Historical Candle Backfill

Status: `IMPLEMENTED_PENDING_LIVE_BACKFILL_AND_R033_RECONCILIATION`

## Finding

R033 rendered its evidence correctly, but the evidence was only R032's
60-second extended-hours proof: two to four one-minute bars per symbol. The 5m
and 15m views therefore had one or two aggregates, and the isolated proof data
contained no daily source. This is not useful workstation chart depth.

## Implementation

- Adds a plan-first historical backfill command at
  `python -m momentum_hunter.schwab_candle_backfill`.
- Requests up to ten calendar days of Schwab one-minute OHLCV and 365 calendar
  days of Schwab daily OHLCV for at most ten bounded symbols.
- Stores one-minute evidence in `schwab-candles-v1` and daily evidence in the
  separate `schwab-daily-candles-v1` source-specific store.
- Preserves provider timestamps, source identity, corrections, history-only
  gap fills, exact duplicate idempotency, and A-B-A provider reassertions.
- Requires at least 30 minute and 20 daily rows per symbol for a passing depth
  result.

## Safety

The command is not scheduled or installed. It does not connect Streamer or
invoke WPF, Engine Host, Shadow, scoring, readiness, selection, FakeBroker,
positions, orders, or transmission. It does not write the legacy minute cache,
the Yahoo daily cache, raw captures, SQLite, or generated reports in Git.

## Verification

- Compileall: pass.
- Focused backfill: 16/16.
- Complete Schwab candle stack: 96/96.
- Final full Python discovery: 1,196/1,196 in 228.078 seconds.
- Plan-only CLI: pass with zero network/write authority.
- R033 manual result: failed data-depth gate; repeat after live backfill and
  R033 consumer reconciliation.

## Next

After Thursday's pinned opening capture is terminal, perform one guarded,
read-only Schwab backfill into the source-specific production stores, inspect
row depth and source/timestamp lineage, reconcile R033 to consume the daily
store, and repeat Steven's visual review. Do not merge R033 or perform R034's
legacy deletion before those gates pass.
