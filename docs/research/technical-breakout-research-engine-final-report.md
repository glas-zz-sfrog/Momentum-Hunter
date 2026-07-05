# Technical Breakout Research Engine v1 Final Report

## Summary

Technical Breakout Research Engine v1 adds an isolated research layer for chart-structure events and forward outcome measurement. It reads existing Momentum Hunter evidence, records breakout-present and insufficient-data records, and writes local JSON/Markdown reports without changing scoring, readiness, alerts, trade planning, outcome labels, broker behavior, UI workflows, schemas, or raw captures.

## Signals Implemented

- Donchian 20-day, 30-day, and 50-day breakout detection when local daily OHLC bars exist.
- Moving-average state and crossover detection for 20-day and 50-day SMAs.
- Bollinger upper-band breakout using prior 20-period SMA plus 2 standard deviations.
- ATR/Keltner breakout using prior 20-period SMA plus 1.5 ATR.
- Intraday VWAP reclaim, opening-range high breakout, 15-minute high breakout, and 60-minute high breakout from local minute bars.
- Volume confirmation using current volume versus prior 20-period average volume.
- QQQ relative-strength confirmation when local QQQ daily bars exist.
- Forward event study for 5, 15, 30, and 60 minute horizons plus 1, 2, 5, and 10 daily-bar horizons where data exists.

## Signals Deferred

- Sector ETF relative strength is deferred until Momentum Hunter has an explicit sector-to-ETF mapping.
- Daily OHLC-derived event output is unavailable unless a local daily bars source is supplied. The engine does not fetch provider data.
- SQLite mirroring is deferred. v1 documents the possible schema but keeps JSON/Markdown reports as the generated research output.

## Data Sources Used

- `MomentumHunterData/data/analysis-captures.csv`
- `MomentumHunterData/data/analysis-outcomes.csv`
- `MomentumHunterData/data/opportunity-alerts.json`
- `MomentumHunterData/data/opportunity-minute-bars.json`
- optional local daily OHLC JSON path, not supplied in the initial run

All inputs are read-only.

## Reports Generated

- `MomentumHunterData/data/reports/technical-breakout-events-latest.json`
- `MomentumHunterData/data/reports/technical-breakout-events-latest.md`
- `MomentumHunterData/data/reports/technical-breakout-study-latest.json`
- `MomentumHunterData/data/reports/technical-breakout-study-latest.md`

Initial local run:

- Event records: 265
- Breakout present: 40
- Insufficient data: 225
- Study rows: 40
- Failed back below breakout level in available study window: 40
- Held above breakout level in available study window: 0

The large insufficient-data count is expected because no local daily OHLC source was supplied. Daily chart signals are not inferred from capture snapshots.

## Tests Added

Added `tests/test_technical_breakouts.py` with focused synthetic coverage for:

- 20-day high breakout detection
- 30-day high breakout detection
- price above moving average
- moving-average crossover
- Bollinger upper-band breakout
- ATR/Keltner breakout
- insufficient data handling
- volume confirmation
- intraday high breakout detection
- event-study return and failed-breakout calculation
- no daily source marking daily signals insufficient
- source-file non-mutation
- research-only import boundary

## Validation Results

Compile command:

```powershell
.\.venv\Scripts\python.exe -B -m compileall -q momentum_hunter tests
```

Result:

- passed

Focused test command:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_technical_breakouts -v
```

Result:

- 13 tests passed
- 0 failures
- 0 errors

Bounded neighboring regression command:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_alert_outcome_updater tests.test_evidence_census -v
```

Result:

- 9 tests passed
- 0 failures
- 0 errors

Report generation command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.technical_breakouts
```

Result:

- all four latest research reports were written under `MomentumHunterData/data/reports/`
- generated Markdown reports contained none of the forbidden trade-instruction phrases

## Limitations

- Daily Donchian, SMA, Bollinger, ATR/Keltner, and QQQ relative-strength signals require local daily OHLC bars.
- Minute-bar volume is sometimes zero, which limits VWAP and relative-volume confidence.
- Opening range is based on the first 30 available local minute bars, not a guaranteed official regular-session window.
- This research layer records evidence only; it does not change Momentum Hunter operating behavior.

## Recommended Next Research Slice

Add a curated local daily OHLC input source for research runs, then rerun the engine to compare daily breakout families against existing candidate outcomes. Keep the next slice read-only and continue treating SQLite as a mirror unless a separate architecture task approves a schema change.
