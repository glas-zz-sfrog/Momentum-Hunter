# ARGUS-GUI-COMMAND-CENTER-001A Visual Mapping

## Design Decision

Steven's `1672 x 941` Hybrid Analytics Console is authoritative for macro
information architecture, operator workflow, hierarchy, density, and visual
language. The 001A proposal restores global situational awareness as the
default Command Center. Single-symbol candle investigation remains a later
drill-down and does not dominate this surface.

The proposal is explicitly labeled `DESIGN PROOF - EXAMPLE DATA`. Populated
example values communicate layout only. They are not claims about current
runtime, market, provider, position, strategy, or execution truth.

## Region Mapping

| Reference region | Proposed region | Status | Authoritative data source | Known limitation |
| --- | --- | --- | --- | --- |
| Header | Compact Momentum Hunter shell with source context, UI clock, evidence mode, last update, `DATA HEALTHY`, and `READ-ONLY RESEARCH - NO ORDER AUTHORITY` | `REFINED` | Existing product/workspace safety labels, exact data-health state, and source timestamps; UI clock is presentation-only | `MARKET OPEN`, `SCANNER LIVE`, connectivity, and execution-live claims are unavailable and intentionally absent |
| Five summary cards | Radar, Accepted, Rejected, Positions, and Attention slots in the original order and visual weight | `PRESERVED` | Candidate and read-only position collection counts may be presentation-derived when source-scoped | Accepted/Rejected membership and Attention/At Risk semantics are not currently exposed; proof values are visibly example data and runtime must show honest unavailable states |
| Radar visualization | `RADAR - ATTENTION MAP` in the original left-center position | `PRESERVED / RUNTIME DEFERRED` | Proposed presentation encoding: radius = source rank, angle = catalyst group, color plus text = visible state | No approved polar/normalization contract exists. The region is preserved for design review, but implementation requires explicit semantic approval and a stable read model; it may not invent geometry |
| Radar Top candidates | Major central `RADAR TOP 10` table with rank, symbol, score, change, RVOL, catalyst, price action, human freshness, and exact visible state | `REFINED` | Existing source-ordered Live Universe candidate snapshot | Score is labeled as score, never confidence; transition deltas and durable first-surfaced clocks require future evidence |
| Accepted | Dedicated upper-right Accepted surface, simultaneously visible with Radar and Rejected | `PRESERVED` | Future normalized candidate-disposition read model; selected-plan evidence exists but is not canonical membership | Example rows are layout-only. Current WPF cannot infer Accepted membership, count, accepted-at time, or thesis from color/readiness/risk evidence |
| Rejected | Dedicated lower-right Rejected surface with blocker/reason parity to Accepted | `PRESERVED` | Future normalized disposition and transition read model | Rejected membership, durable reason, and rejected-at timestamp are not bridged to WPF; example rows are layout-only |
| Accepted mini-chart | Equal-width green 2-day/15-minute example sparkline and transition marker per visible row | `PRESERVED / RUNTIME DEFERRED` | Future bounded multi-symbol candle payload; one selected-symbol 15m chart is available today | No per-row multi-symbol payload exists. Runtime must not fan out provider calls, synthesize bars, backfill, or reuse another symbol's candles |
| Rejected mini-chart | Equal-width red 2-day/15-minute example sparkline and transition marker per visible row | `PRESERVED / RUNTIME DEFERRED` | Same future bounded multi-symbol candle and disposition-transition payload | Same limitation as Accepted; transition markers need exact immutable event time/identity |
| Positions | First-class bottom-center `POSITIONS - READ-ONLY` region | `REFINED` | Existing source-labeled Shadow/FakeBroker `OpenPositionView` fields | Must retain exact source/unavailable states and must not imply brokerage positions or order authority; proof values are example data |
| Machine Log / Recent Events | First-class bottom-left `WHAT CHANGED - RECENT EVENTS` with `PARTIAL HISTORY` | `REFINED` | Existing Activity, Candidate Story, and Technical Research chronology | Current evidence is not a complete candidate-transition ledger; exact Hot Universe transitions need a future typed boundary |
| Stats / system context | Compact bottom-right `SYSTEM CONTEXT` with exact data-health state, last update, workspace authority, history completeness, and unavailable attention state | `REFINED` | Existing data-health/workspace/source observations | Connectivity, uptime, scan rates, scanner state, acceptance rates, rejection rates, and market-open claims remain unavailable |
| Freshness / newness | `NEW 7m`, `NEW 24m`, `RECENT 38m`, `RECENT 54m`, and `SEEN` labels in Radar rows plus a persistent footer separation statement | `REFINED` | Candidate report observation can be formatted without reranking | Current observation age is not durable first-surfaced or last-meaningful-change time. `USER ATTENTION FRESHNESS != TRADING / STRATEGY AGE` and never feeds engine semantics |
| Left navigation | Slim Console/Radar/Accepted/Rejected/Positions/Activity/Settings rail mirroring reference hierarchy | `PRESERVED` | Navigation concept only | Destinations remain read-only concepts; this proof adds no application command or behavior |
| Footer | Compact product, safety, and design-proof provenance line | `REFINED` | Static proof disclosure and exact data-health state | Bare green `LIVE` and unsupported connectivity claims are removed; the green state is explicitly `DATA HEALTHY` only |

## Macro Layout At 1920 x 1080

1. A compact header and five-card summary strip establish source, data health,
   and the complete at-a-glance hierarchy.
2. The primary band places Radar/attention visualization left, the ranked Radar
   list center, and simultaneous Accepted/Rejected regions right.
3. Accepted and Rejected receive equal historical-context treatment and clear
   green/red plus text labels; color is never the only meaning.
4. The lower band keeps What Changed, read-only Positions, and truthful System
   Context continuously visible without scrolling.
5. The default view contains no dominant CandleChart. Existing single-symbol
   investigation remains valuable secondary navigation.

## Radar Encoding Proposal

The visual proof proposes, but does not implement, this presentation-only
semantic:

```text
RADIUS = source rank
ANGLE = approved stable catalyst group
COLOR + TEXT = exact visible state
```

The map is not authorized for production until grouping, normalization,
population, stable identity, and unavailable behavior are separately approved.
It must never feed admission, ordering, score, readiness, risk, timing, or
execution.

## Example-Data Discipline

- `28`, `7`, `12`, `5`, row prices, reasons, targets, timestamps, and mini-chart
  paths in the proof are visual examples.
- Every populated region is covered by the proof-wide
  `DESIGN PROOF - EXAMPLE DATA` disclosure.
- `ATTENTION` shows an honest unavailable slot to demonstrate the required
  runtime fallback.
- `PARTIAL HISTORY`, `READ-ONLY`, `NO ORDER AUTHORITY`, and `not exposed`
  remain visible at native resolution.
- No value in the proof is an analytical input or current-state assertion.

The exact field-level implementation boundary is recorded in
`ARGUS-GUI-COMMAND-CENTER-001A-TRUTH-DEPENDENCY-MAP.md`.
