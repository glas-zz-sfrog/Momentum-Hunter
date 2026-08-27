# ARGUS-GUI-COMMAND-CENTER-001B Semantic And Microchart Decision

## Lifecycle Decision

```text
CENTER_SURFACE_SEMANTICS = CROSS_LIFECYCLE_RANKED_CANDIDATES
```

The center surface is renamed from `RADAR TOP 10` to `RANKED CANDIDATES`.
It is a cross-lifecycle display that may retain important rows after disposition
for situational awareness. It is not a Radar-membership list.

The populations remain distinct:

- `RADAR` means presently under consideration;
- `ACCEPTED` means the authoritative lifecycle has accepted the candidate;
- `REJECTED` means the authoritative lifecycle has rejected the candidate;
- a row's presence in `RANKED CANDIDATES` does not change or extend its
  lifecycle membership;
- summary counts and dedicated panels count only their authoritative lifecycle
  populations, never center-board visibility.

This model preserves the accepted 001A cross-lifecycle situational view without
the contradictory `RADAR TOP 10` title. It does not define lifecycle logic.
Canonical Accepted/Rejected membership still requires the future read-only
contract identified in the 001A Truth Dependency Map.

## Surgical Microchart Analysis

Steven's supplemental `1112 x 655` reference uses a compact line treatment in
the primary ranked rows. The relevant visual properties are:

1. one chart per row, directly between candidate context and current price;
2. a wide, shallow plotting area approximately four to five times wider than
   its height;
3. a continuous anti-aliased polyline with many small local oscillations,
   preserving momentum texture rather than reducing the history to a straight
   trend glyph;
4. no visible axes, tick labels, area fill, frame, legend, or oversized endpoint
   marker inside the row;
5. the same dark row background continues behind the chart, with only faint
   structural separation;
6. consistent geometry across rows so shapes are comparable at a glance;
7. green examples for rising histories, amber for mixed/caution histories, and
   red for fading histories, always paired with numeric/text context so color
   is not the only meaning;
8. enough horizontal resolution to show climbing, fading, consolidation,
   breakout, failed move, or erratic action without becoming a full chart.

The 001B proof applies that treatment to all ten primary `RANKED CANDIDATES`
rows. Accepted and Rejected retain equivalent compact chart columns.

## Target Inline Contract

```text
HORIZON = 2 trading days
FIDELITY = 15-minute
STYLE = compact smooth brokerage-grade microchart
PURPOSE = human price-history context only
```

At full regular-session coverage, two 15-minute sessions normally provide up to
52 interval observations. The later implementation must plot only the bounded,
source-proven observations exposed by an authorized read-only payload. It must
not synthesize bars, aggregate another interval in WPF, backfill, reuse another
symbol's candles, or fan out provider calls from row rendering. Partial or
unavailable data must remain explicit.

Line color and shape are presentation output. Any future coloring rule must be
defined from displayed price-history facts and labels, not lifecycle priority,
score, admission, readiness, risk, or execution authority.

## Hard Semantic Separation

```text
INLINE_CHART != SCORING_INPUT
INLINE_CHART != ADMISSION_INPUT
INLINE_CHART != READINESS_INPUT
INLINE_CHART != RISK_INPUT
INLINE_CHART != EXECUTION_INPUT

USER_ATTENTION_FRESHNESS != TRADING_OR_STRATEGY_AGE
```

Microcharts and `NEW` / `RECENT` / `SEEN` labels are read-only human context.
They never feed ranking, scoring, candidate admission, trade readiness, risk,
entry, exit, or execution.

## Visual Freeze

001B changes only:

- the center title and semantic disclosure;
- the primary row price-action presentation from text to inline example
  microcharts;
- the local human-context disclaimer required by those charts.

The accepted 001A header, summary strip, Radar visualization, three-column macro
band, dedicated Accepted and Rejected panels, Positions, What Changed, System
Context, read-only wording, color system, spacing, and lack of a dominant
CandleChart remain frozen.
