# Candidate Story Graph-First Design

Phase: 2A  
Status: design approved for smallest safe vertical slice before deeper chart/timeframe work

## Purpose

The current Candidate Timeline is audit-first. It proves identity, but it makes the operator work too hard to understand the stock story.

Phase 2A changes the default experience from `Candidate Timeline` to `Candidate Story`:

1. Graph first
2. Details second
3. Audit data last

The primary operator question is:

> Did Momentum Hunter find this move early, did the signal strengthen, and where did price go afterward?

## Proposed Layout

Default dialog title:

```text
Candidate Story - SYMBOL
```

Top to bottom:

```text
Story Header
Prominent Capture-Trail Graph
Mode Controls: Trail | Intraday | 5D | Audit
Simplified Capture Story Rows
Advanced Capture Audit
```

### Story Header

The header should summarize:

- symbol and company when available
- sector and industry
- first seen timestamp
- latest capture timestamp
- first seen price
- latest price
- move since first seen
- first score
- latest score
- peak score and date
- trusted capture count
- plain-language status:
  - Building
  - Peaked
  - Fading
  - Holding
  - Stale
  - Insufficient data

### Prominent Trail Graph

The first vertical slice uses stored capture points only:

- x-axis: capture sequence/date labels
- primary line: capture price
- secondary line/markers: score
- lower/secondary cue: volume bars if feasible in the same chart

The graph should show only real stored capture facts. It must not invent missing prices, volume, relative volume, minute bars, or future outcomes.

### Modes

`Trail` is the default and is implemented first.

`Intraday` and `5D` are placeholders in the first slice unless reliable stored data already exists. They should show clear missing-data states:

- `No minute bars available for this symbol/date.`
- `No 5D stored price context available.`

`Audit` reveals the existing dense capture table and replay identity information.

## Data Sources

Use only stored data:

- active raw captures from `MomentumHunterData/data/captures`
- derived score explanations from `score-breakdowns.json`
- later review decisions from `review-decisions.json`
- later outcome labels from `analysis-outcomes.csv`
- existing `TimelineRow` data from `momentum_hunter.replay`

Do not fetch current market data.
Do not recalculate historical scores.
Do not mutate raw captures.

## Fallback Behavior

If data is missing:

- no timeline rows: show `No trusted captures found for this ticker.`
- no usable prices: show `Capture trail cannot be charted because stored prices are missing.`
- one capture only: show the single capture and classify status as `Insufficient data`
- missing relative volume: show `Rel Vol unavailable for legacy capture`
- missing outcome: show `No outcome annotation available yet`
- missing minute bars: show `No minute bars available for this symbol/date`

No fallback may silently substitute a different ticker, date, capture, or latest row.

## Component Plan

Smallest safe vertical slice:

1. Add deterministic story summary helpers:
   - first/latest capture
   - price move since first seen
   - first/latest/peak score
   - trusted capture count
   - story status
2. Add story header HTML/label above the graph.
3. Add a prominent capture-trail chart for stored price/score points.
4. Add simplified detail rows below the graph.
5. Preserve existing dense table as `Capture Audit`.
6. Add a mode selector:
   - `Trail`: story header + graph + simplified rows
   - `Audit`: existing dense table
   - `Intraday` / `5D`: clear missing-data placeholder in this slice

## Test Plan

Use focused tests only:

- story summary for two captures produces correct first/latest/peak values
- June 17 and June 18 rows remain distinct
- single capture status is `Insufficient data`
- missing price creates a missing-data chart state
- audit mode keeps existing capture table available
- no raw capture mutation

Avoid broad Qt test modules. Use syntax checks, pure helper tests, and tiny offscreen Qt probes only where necessary.

## Risks

- Too much chart work could become a mini trading workstation. Avoid that in Phase 2A.
- Dual-axis price/score visualization can mislead if not labeled clearly.
- Current data may have legacy relative-volume gaps. Show them honestly.
- Dense audit data must remain available because Replay is a trust boundary.
- If chart rendering is hard to test in headless mode, keep deterministic story metrics well covered and use small offscreen smoke probes.

## Quick Work

Do now:

- header summary
- trail graph from capture rows
- simplified rows
- audit toggle/table preservation
- missing-data placeholders

## Wait

Do later:

- intraday minute-bar visualization
- 5D enriched chart context
- alert/watchlist/entry-plan markers on graph
- outcome markers on graph
- sector/benchmark relative-strength overlays
- zoom/pan/drawing tools
- indicator suite
