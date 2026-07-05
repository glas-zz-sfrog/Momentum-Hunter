# Technical Confluence Architecture v1

This proposal defines a research-only architecture for a future Momentum Hunter
Technical Confluence Matrix. It is not production scoring, not trade readiness,
not alert logic, and not a trade recommendation engine.

## Goals

- Show when independent technical families align.
- Separate raw indicator count from independent family confirmation.
- Preserve unavailable and insufficient-data states.
- Keep warnings, blockers, and gates visible.
- Support event-study validation before any production use.

## Non-Goals

- No Opportunity Score.
- No trade recommendation.
- No broker integration.
- No automated trading.
- No readiness rule change.
- No alert threshold change.
- No mutation of raw captures or evidence files.

## Conceptual Model

The confluence matrix should evaluate indicators in layers:

1. Raw indicator states.
2. Family-normalized states.
3. Gates and warnings.
4. Data-quality state.
5. Research conclusion.

The research conclusion must describe evidence quality, not action.

## State Vocabulary

Allowed stock-level signal states:

- `GREEN`: evidence supports the family condition.
- `YELLOW`: mixed, weak, or early evidence.
- `RED`: evidence is absent or contradicts the condition.
- `CAUTION`: risk or overextension is present.
- `BLOCKED`: a gate prevents a clean research conclusion.
- `UNAVAILABLE`: required data does not exist.
- `INSUFFICIENT_DATA`: data exists but is not enough for the calculation.

Allowed research conclusions:

- `STRONG_CONFLUENCE`
- `MODERATE_CONFLUENCE`
- `WEAK_CONFLUENCE`
- `CONFLICTED_CONFLUENCE`
- `INSUFFICIENT_DATA`

These labels must remain research-only.

## Family-Level Scoring

Family-level state should be computed before any raw count is displayed as a
headline.

Example:

| Family | Inputs | Output |
| --- | --- | --- |
| Trend | EMA stack, SMA state, ADX | GREEN |
| Breakout | Donchian, Darvas, gap-and-hold | GREEN |
| Volatility | Squeeze, Bollinger/Keltner release, ATR expansion | GREEN |
| Volume | RVOL, volume above average, money-flow checks | GREEN |
| Relative Strength | QQQ/SPY/sector relative strength | YELLOW |
| Market Regime | QQQ/SPY trend, VIX, breadth | SUPPORTIVE |
| Risk | extension, failed breakout, volume climax | CAUTION |
| Data Quality | sufficiency, staleness, missing mappings | PARTIAL |

Family state should use explicit precedence:

- `BLOCKED` outranks green checks when a hard gate fails.
- `UNAVAILABLE` remains visible and does not count as red.
- `CAUTION` downgrades the conclusion but does not erase positive evidence.
- Conflicting indicators inside one family produce `YELLOW` unless a blocker exists.

## Raw Indicator Counts

Raw counts are useful for transparency:

- Raw Green Checks: `23 / 30`
- Raw Yellow Checks: `4 / 30`
- Raw Red Checks: `1 / 30`
- Unavailable Checks: `2 / 30`

But raw counts must be displayed beneath independent family state because raw
counts can overstate confidence when indicators are redundant.

## Independent Family Counts

Independent family counts answer the more important question:

- How many separate evidence families agree?
- Which families disagree?
- Which families are unavailable?
- Are warnings severe enough to downgrade the setup?

Example:

- Independent Green Families: `5 / 7`
- Major Red Flags: `0`
- Warning Flags: `2`
- Data Quality: `PARTIAL`
- Conclusion: `MODERATE_CONFLUENCE`

## Warning And Blocker Flags

Warnings should be first-class outputs, not buried notes.

Warning examples:

- Price extended more than researched ATR threshold.
- RSI > 80 after multi-day run.
- Volume climax after large gap.
- Relative strength fading while price rises.
- Intraday price below VWAP after daily breakout.

Blocker examples:

- Failed breakout below trigger.
- Data quality fail.
- Missing required benchmark for relative-strength conclusion.
- Liquidity/spread condition fails when that data exists.

## Unavailable-Data Flags

Unavailable data must be explicit.

Examples:

- `sector_relative_strength: UNAVAILABLE` because no sector ETF mapping exists.
- `anchored_vwap: UNAVAILABLE` because no anchor event is defined.
- `intraday_vwap: INSUFFICIENT_DATA` because minute bars are missing volume.
- `sma_200: INSUFFICIENT_DATA` because the stock has fewer than 200 bars.

Unavailable indicators should not be treated as failed indicators.

## Risk Gates

Risk gates should not be confused with signal families.

Risk gates answer:

- Is the move too extended to treat as fresh evidence?
- Did the breakout fail?
- Is the signal occurring after a volume climax?
- Is the current price far above trend or VWAP?

Risk gate outputs:

- `CLEAR`
- `CAUTION`
- `BLOCKED`
- `UNAVAILABLE`

## Liquidity Gates

Liquidity gates are deferred until reliable liquidity inputs exist, but the
architecture should reserve them.

Potential inputs:

- Average dollar volume.
- Float.
- Bid/ask spread.
- Intraday volume consistency.
- Price level and minimum tradable liquidity.

Potential outputs:

- `PASS`
- `CAUTION`
- `FAIL`
- `UNAVAILABLE`

## Data-Quality Gates

Data quality should be a gate because technical precision is meaningless when
inputs are stale, sparse, or mismatched.

Data-quality checks:

- Required bars are present.
- Bars are chronologically ordered.
- Latest bar is fresh enough for the timeframe.
- OHLC relationships are internally valid.
- Volume is present when the indicator requires volume.
- Benchmark bars align with stock bars.
- Sector mapping exists when sector-relative strength is requested.

Outputs:

- `PASS`
- `PARTIAL`
- `FAIL`

## Example Research Output

```text
Trend Family: GREEN
Breakout Family: GREEN
Volatility Family: GREEN
Volume Family: GREEN
Relative Strength Family: YELLOW
Market Regime: SUPPORTIVE
Risk Family: CAUTION
Liquidity Gate: PASS
Data Quality: PARTIAL

Raw Green Checks: 23 / 30
Independent Green Families: 5 / 7
Major Red Flags: 0
Warning Flags: 2
Unavailable Checks: 3
Conclusion: STRONG_CONFLUENCE, not a trade recommendation
```

## Event-Study Integration

The confluence matrix should become useful only after event-study validation.

For each evaluated candidate/date, store:

- Raw indicator states.
- Family states.
- Gate states.
- Data-quality state.
- Research conclusion.
- Forward outcome windows.
- Failure and hold-above-trigger flags when breakout context exists.

This lets research answer:

- Which families actually improved follow-through?
- Which checks were redundant?
- Which warnings mattered most?
- Which unavailable-data states reduce confidence?

## Recommended v1 Slice After This Roadmap

Build Wave 1 confluence primitives as a research-only module:

- EMA stack / slope.
- ADX trend strength.
- Bollinger/Keltner squeeze release.
- ATR extension risk.
- Failed breakout state.
- Relative strength vs QQQ/SPY.
- Volume confirmation / relative volume.
- Family-normalized confluence summary.

The slice should write generated local JSON/Markdown reports and tests, but must
not feed production scoring, readiness, alerts, or trade planning.
