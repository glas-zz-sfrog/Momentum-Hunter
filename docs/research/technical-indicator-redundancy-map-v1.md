# Technical Indicator Redundancy Map v1

This map prevents Momentum Hunter from treating correlated technical checks as
independent evidence. The future confluence matrix can show raw indicator count,
but the research conclusion should be driven by independent family evidence,
warning flags, data quality, and event-study results.

## Core Rule

Raw green checks are descriptive. They are not confidence by themselves.

Example: `23 / 30 green` is weaker than it sounds if 12 of those checks are
different versions of trend strength. A stronger research state is:

- Trend: green
- Breakout: green
- Volume: green
- Relative strength: green
- Market regime: supportive
- Risk: no major warning
- Data quality: complete

## Trend / Momentum Overlap

Likely overlapping indicators:

- EMA stack
- 20/50/200 SMA position
- ADX trend strength
- Supertrend
- MACD cross
- MACD histogram expansion
- PPO
- TRIX
- ROC

What they mostly measure:

- Whether price is moving directionally.
- Whether shorter-term trend is above longer-term trend.
- Whether trend momentum is accelerating or decelerating.

Recommended treatment:

- Count EMA/SMA stack as trend structure.
- Count ADX as trend-strength confirmation, not a separate primary bullish signal.
- Count MACD/PPO/TRIX as momentum confirmation, but cap their family contribution.
- Do not let EMA stack, SMA stack, MACD, PPO, and TRIX all count as independent green families.

Research question:

- Does adding MACD/PPO/TRIX improve event-study results after EMA/SMA trend state is already known?

## Breakout / Range Structure Overlap

Likely overlapping indicators:

- 20-day high breakout
- 30-day high breakout
- 50-day high breakout
- Darvas Box / range box breakout
- Bollinger upper-band breakout
- Keltner/ATR channel breakout
- Gap-and-hold
- Opening-range breakout

What they mostly measure:

- Price moving beyond a prior reference level.
- Range expansion after containment or compression.
- Whether a new high or volatility band break occurred.

Recommended treatment:

- Count Donchian and Darvas signals inside the Breakout family.
- Count Bollinger/Keltner release inside Volatility / Compression unless used as the breakout trigger.
- Count gap-and-hold as breakout quality only when the gap level holds.
- Keep failed breakout as a risk/blocker signal, not another breakout variant.

Research question:

- Which breakout type has the best forward return and lowest failure rate after controlling for volume and relative strength?

## Volatility Expansion Overlap

Likely overlapping indicators:

- Bollinger Bandwidth squeeze
- Bollinger inside Keltner squeeze release
- Bollinger upper-band breakout
- Keltner breakout
- ATR expansion
- Average daily range expansion
- Historical volatility percentile

What they mostly measure:

- Compression before expansion.
- Range expansion.
- Volatility regime shift.

Recommended treatment:

- Count squeeze state as compression setup.
- Count release as volatility expansion.
- Count ATR/ADR expansion as confirmation or risk context depending on direction.
- Use historical volatility percentile as context, not another green vote until validated.

Research question:

- Are squeeze releases more useful than simple range breakouts, or do they only restate the same expansion?

## Volume / Money-Flow Overlap

Likely overlapping indicators:

- Relative volume
- Volume above 20-day average
- OBV new highs
- Money Flow Index
- Chaikin Money Flow
- Accumulation/Distribution trend
- Up-volume vs down-volume
- Volume dry-up before breakout then expansion
- Volume climax

What they mostly measure:

- Participation.
- Close location with volume.
- Accumulation or distribution pressure.
- Potential exhaustion.

Recommended treatment:

- Count relative volume or volume above average as the simple participation gate.
- Count OBV/CMF/MFI/A-D as money-flow confirmation, capped to one family state.
- Count volume dry-up then expansion as a setup-quality pattern.
- Count volume climax as a risk warning, not as a green participation signal.

Research question:

- Do money-flow indicators add predictive value after simple relative volume is known?

## Relative Strength Overlap

Likely overlapping indicators:

- Stock vs QQQ
- Stock vs SPY
- Stock vs sector ETF
- Sector ETF vs QQQ/SPY
- 20-day relative strength slope
- 60-day relative strength slope
- Relative strength new high

What they mostly measure:

- Candidate performance versus market or sector.
- Whether leadership is improving.
- Whether the stock is leading or just rising with the tape.

Recommended treatment:

- Count stock-vs-QQQ/SPY as primary relative strength.
- Count stock-vs-sector as refinement when sector mapping is reliable.
- Count 20-day and 60-day slopes as short/intermediate sub-states.
- Count RS new high as a high-quality relative strength event, not as a separate family.

Research question:

- Which benchmark is most useful for Momentum Hunter candidates: QQQ, SPY, or sector ETF?

## Market Regime Overlap

Likely overlapping indicators:

- QQQ above 20/50/200
- SPY above 20/50/200
- Sector breadth
- New highs vs new lows
- VIX trend
- Risk-on / risk-off composite

What they mostly measure:

- Whether the broad market supports momentum continuation.
- Whether breadth confirms index strength.
- Whether volatility is a headwind.

Recommended treatment:

- Treat market regime as a gate or context family, not a stock-level green vote.
- Keep component states visible when using a composite.
- Avoid allowing both component checks and the composite to count independently.

Research question:

- Do momentum breakouts perform differently in supportive versus stressed regimes?

## Risk / Overextension Overlap

Likely overlapping indicators:

- Distance above 20 EMA
- Distance above VWAP
- ATR extension
- RSI > 80 after multi-day run
- Gap too large without consolidation
- Volume climax
- Failed breakout back below trigger

What they mostly measure:

- Late-stage extension.
- Exhaustion risk.
- Failed confirmation.
- Fragility of the setup.

Recommended treatment:

- Keep these as warnings, cautions, blockers, or gates.
- Do not count overextension as another bullish green check.
- Allow a strong confluence state to be downgraded by major risk flags.

Research question:

- Which risk warnings best separate continuation from fade after a breakout?

## Proposed Family Caps

For research output, each family should contribute one primary state:

| Family | Possible State | Raw Checks Allowed | Independent Count Contribution |
| --- | --- | --- | --- |
| Trend / Structure | GREEN, YELLOW, RED, UNAVAILABLE | EMA, SMA, ADX, Supertrend | Max 1 |
| Breakout | GREEN, YELLOW, RED, UNAVAILABLE | Donchian, Darvas, gap, range | Max 1 |
| Volatility / Compression | GREEN, YELLOW, RED, UNAVAILABLE | Squeeze, ATR, ADR, HV percentile | Max 1 |
| Volume / Participation | GREEN, YELLOW, RED, UNAVAILABLE | RVOL, OBV, CMF, MFI, A-D | Max 1 |
| Relative Strength | GREEN, YELLOW, RED, UNAVAILABLE | QQQ, SPY, sector, slope, new high | Max 1 |
| Market Regime | SUPPORTIVE, MIXED, HOSTILE, UNAVAILABLE | QQQ, SPY, VIX, breadth | Gate/context |
| Risk / Overextension | CLEAR, CAUTION, BLOCKED, UNAVAILABLE | ATR extension, RSI, gap, failure | Gate/context |
| Data Quality | PASS, PARTIAL, FAIL | sufficiency, stale data, mapping | Gate/context |

## Implementation Implication

Future confluence work should store both:

- Raw indicator states for transparency.
- Family-normalized states for decision-quality research.

This lets Steven see "29 of 30 green" while also seeing whether that means
seven independent families aligned or one family repeated itself.
