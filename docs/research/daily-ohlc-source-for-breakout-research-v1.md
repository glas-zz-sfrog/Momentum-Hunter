# Daily OHLC Source for Breakout Research v1

Technical Breakout Research Engine v1 can detect daily chart signals, but it needs normalized daily OHLC bars. This slice adds a research-only daily OHLC source pipeline and coverage report without changing Momentum Hunter scoring, readiness, alerts, trade planning, outcomes, scanner behavior, broker behavior, UI workflows, or raw captures.

## Source Audit

| Source | Available Fields | Missing Fields | Use In v1 |
| --- | --- | --- | --- |
| `MomentumHunterData/data/daily-ohlc-bars.json` | normalized `symbol`, `date`, `open`, `high`, `low`, `close`, `volume`, `source`, `adjusted`, quality fields | absent until generated or supplied | Preferred local research source |
| Yahoo chart-derived daily bars | timestamp, open, high, low, close, volume, adjusted close | provider availability can fail; adjusted OHLC must be normalized | Explicit research cache builder only |
| `analysis-captures.csv` | ticker, capture timestamp/date, price, volume, relative volume, market regime | no daily open/high/low; capture price is a snapshot | Context and requested-symbol discovery only |
| `analysis-outcomes.csv` | forward returns, max gain/drawdown, outcome windows | no reusable OHLC history | Context only |
| `opportunity-minute-bars.json` | intraday open/high/low/close/volume | not daily history; may include pre/post-market minute data | Intraday breakout source only |
| Trade-plan / active-monitor reports | previous day high/low/close, five/twenty-day highs, ATR summaries | no complete per-day OHLC series, often derived summaries only | Audit reference, not daily bar source |
| SQLite capture/evidence mirrors | capture rows, alert rows, minute bars, system status | no authoritative daily OHLC table before this slice | Optional additive mirror only |

## Source Priority

1. Local normalized research cache: `MomentumHunterData/data/daily-ohlc-bars.json`.
2. Explicit Yahoo chart-derived research cache build using the existing Yahoo chart provider pattern.
3. User-supplied local JSON in the same normalized shape.
4. Trade-plan technical summaries only as audit context, never as a substitute for daily OHLC bars.
5. Capture snapshots only for requested-symbol discovery and market-regime context.

The default loader is local/read-only. Provider access happens only through the explicit daily OHLC CLI fetch option.

## Normalized Record

Each daily OHLC record contains:

- `symbol`
- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `source`
- `adjusted`
- `imported_at`
- `quality_status`
- `warnings`

Quality status is `VALID` only when the record has a valid symbol/date, positive OHLC values, non-negative volume when present, and internally possible high/low relationships.

## Date And Timestamp Conventions

- Daily bars use ISO dates: `YYYY-MM-DD`.
- Generated/imported timestamps use ISO datetimes.
- Yahoo chart timestamps are normalized to local date values from the returned epoch timestamps.
- The breakout engine converts normalized daily records into its existing daily bar model using `date` as the event timestamp.

## Adjusted Price Concern

Yahoo chart payloads include raw OHLC and adjusted close. The research cache applies the adjusted-close ratio to open/high/low and stores adjusted close as close. Records are marked `adjusted: true`.

This keeps daily range and return math internally consistent, but the adjustment policy is a research assumption. Reports preserve the source and adjusted flag so future studies can compare raw versus adjusted bars if needed.

## Volume Availability

Daily volume is preserved when present. If volume is missing, the bar can still be structurally valid, but volume confirmation will be unavailable for that event. Negative volume is invalid.

Minute-bar volume remains separate from daily-bar volume and may be zero in existing intraday data.

## Symbol Coverage

Coverage is reported in `daily-ohlc-coverage-latest.json/md`:

- requested symbols
- covered symbols
- bars per symbol
- date range
- missing symbols
- invalid records
- insufficient-history warnings

The loader can use existing evidence to define requested symbols, but it does not infer OHLC bars from captures.

## SQLite Mirror

The module includes an opt-in additive mirror table:

`research_daily_ohlc`

This mirror is not authoritative. It is created only by an explicit helper/CLI path and does not alter the central SQLite schema version or production read paths.

## Data Quality Risks

- Provider fetches can fail or return sparse bars.
- Adjusted OHLC normalization may differ from raw chart levels.
- Very recent symbols may have fewer than 50 bars, limiting 50-day and long-window signals.
- Capture prices are not daily bars and must not be used as OHLC substitutes.
- Trade-plan technical summaries are derived levels, not event-study history.

## Research-Only Boundary

This slice does not:

- change scoring math
- change readiness thresholds
- change alert logic
- change trade-planning logic
- change outcome classification
- create trade recommendations
- mutate raw captures
- make SQLite authoritative
- alter production scanner behavior
- add broker integration
- add automated trading

## Initial Proof Run

The initial research cache was built explicitly for:

- `CRWV`
- `QQQ`

That produced:

- 630 valid normalized daily OHLC records
- 0 invalid records
- 315 bars for `CRWV`
- 315 bars for `QQQ`

The breakout report then produced:

- 124 breakout-present records
- 17 Donchian 20-day breakouts
- 11 Donchian 30-day breakouts
- 7 Donchian 50-day breakouts
- 11 Bollinger upper-band breakouts
- 10 ATR/Keltner breakouts
- 28 price/SMA crossover records
- 3 SMA 20-over-50 crossover records
- 124 event-study rows

The coverage report requested 226 evidence symbols, covered 2, and listed 224 missing symbols. This is expected because the cache build was intentionally bounded to the locally active minute-bar symbol plus QQQ rather than fetching every historical capture symbol in one pass.
