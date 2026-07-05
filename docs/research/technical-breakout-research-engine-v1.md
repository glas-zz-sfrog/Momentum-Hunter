# Technical Breakout Research Engine v1

Momentum Hunter already captures candidate evidence, alert history, outcome labels, and minute-bar follow-through. The missing research layer is chart structure: whether a candidate is simply moving, or whether it is breaking a recent range, reclaiming a trend level, or pushing through a volatility band.

This engine is research-only. It measures technical events and follow-through. It does not alter scoring, readiness, alert thresholds, trade planning, outcome classification, broker behavior, or UI workflow.

## Why Chart Structure Matters

Momentum candidates can look strong for very different reasons. A price move may be:

- a clean range expansion after compression
- a short-lived spike into resistance
- a reclaim of a trend average
- a volatility-band expansion
- a noisy move without volume confirmation

The research question is whether these structures help explain which momentum candidates continue, fade, or become noise after the signal appears.

## Breakout Definitions

Daily signals use completed prior windows to avoid lookahead.

- Donchian breakout: current close crosses above the prior 20-day, 30-day, or 50-day high when sufficient daily OHLC bars exist.
- Moving-average confirmation: price above 20-day SMA, price above 50-day SMA, 20-day SMA above 50-day SMA, price crossing above either SMA, and 20-day SMA crossing above 50-day SMA.
- Bollinger breakout: current close crosses above the prior 20-period SMA plus 2 standard deviations.
- ATR/Keltner breakout: current close crosses above the prior 20-period SMA plus 1.5 ATR. The 1.5 ATR default is intentionally moderate for research sensitivity; later studies can compare it against 2 ATR.
- Intraday confirmation: VWAP reclaim, opening-range high breakout, prior 15-minute high breakout, and prior 60-minute high breakout when local minute bars exist.
- Volume confirmation: current volume relative to the prior 20-period average volume, with 1.5x treated as confirmed.
- Relative strength confirmation: symbol outperformance versus QQQ over a 5-bar daily window when local QQQ bars exist. Sector ETF confirmation is deferred until a sector-to-ETF mapping exists.

## Data Sources

The engine reads existing local artifacts only:

- `MomentumHunterData/data/analysis-captures.csv`
- `MomentumHunterData/data/analysis-outcomes.csv`
- `MomentumHunterData/data/opportunity-alerts.json`
- `MomentumHunterData/data/opportunity-minute-bars.json`
- optional local daily OHLC bars JSON supplied to the CLI

It does not fetch market data. It does not mutate raw captures or source evidence. Capture snapshots can provide context, but they are not treated as authoritative OHLC bars.

## Timeframes

Daily research windows:

- prior 20, 30, and 50 daily bars for range breakouts
- 20-day and 50-day SMAs
- 20-day Bollinger and ATR/Keltner channels
- 1, 2, 5, and 10 daily-bar forward outcomes

Intraday research windows:

- VWAP reclaim from available minute bars
- first 30 available minutes as the opening-range default
- prior 15-minute and 60-minute high breakouts
- 5, 15, 30, and 60 minute forward outcomes

## Event-Study Methodology

Each detected event records:

- symbol
- event timestamp/date
- event type
- timeframe
- trigger price
- prior high, band, or moving-average value
- distance above trigger/reference
- volume and relative volume
- market regime when available
- source data
- data sufficiency
- quality flag
- notes

The event study measures forward returns where data is available and records:

- horizon returns
- max favorable excursion
- max adverse excursion
- whether price held above the breakout level
- whether price failed back below the breakout level
- whether volume confirmed
- whether the move became extended

## Expected Outputs

Generated local reports:

- `MomentumHunterData/data/reports/technical-breakout-events-latest.json`
- `MomentumHunterData/data/reports/technical-breakout-events-latest.md`
- `MomentumHunterData/data/reports/technical-breakout-study-latest.json`
- `MomentumHunterData/data/reports/technical-breakout-study-latest.md`

The JSON output is structured for later aggregation. The Markdown output is for operator review.

## SQLite Position

No SQLite table is added in v1. A future non-authoritative mirror table could store event rows with:

- event id
- symbol
- timestamp
- event type
- timeframe
- trigger/reference values
- volume/relative-volume fields
- market regime
- source data
- sufficiency and quality flags
- study outcome fields

SQLite must remain a mirror unless a later architecture task explicitly promotes it.

## Limitations

- Daily range, moving-average, Bollinger, ATR/Keltner, and QQQ relative-strength signals require local daily OHLC bars. If those bars are absent, the report marks daily signals as insufficient.
- Minute-bar volume can be zero or unavailable, which limits VWAP and relative-volume confirmation.
- The opening range is based on the first 30 available local minute bars, not necessarily official regular-session bars.
- Sector ETF relative strength is deferred until a maintained sector mapping exists.
- This is evidence collection, not a rule change.

## Research-Only Boundary

This engine may say:

- `Breakout present`
- `Breakout absent`
- `Breakout failed`
- `Breakout unconfirmed`
- `Insufficient data`

It must not produce trade instructions, opportunity scoring, broker actions, readiness changes, alert threshold changes, outcome relabeling, or UI workflow changes.
