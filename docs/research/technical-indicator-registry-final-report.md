# Technical Indicator Registry and Confluence Roadmap Final Report

## Summary

Technical Indicator Registry & Confluence Roadmap v1 defines a research-only
path for evaluating technical "perfect storm" setups in Momentum Hunter. It
catalogs indicators, maps redundancy risk, and proposes a family-level
confluence architecture so future work can test independent evidence without
creating fake confidence from overlapping checks.

No application code, tests, scoring logic, readiness rules, alert thresholds,
trade-planning logic, broker behavior, UI workflows, database schema, runtime
behavior, generated market data, or raw captures are changed by this slice.

## Files Created

- `docs/research/technical-indicator-registry-v1.md`
- `docs/research/technical-indicator-redundancy-map-v1.md`
- `docs/research/technical-confluence-architecture-v1.md`
- `docs/research/technical-indicator-registry-final-report.md`

## Indicators Cataloged

The registry catalogs 47 technical indicators across seven families:

- Trend / Structure: 6 indicators.
- Momentum: 7 indicators.
- Volatility / Compression: 6 indicators.
- Volume / Participation: 8 indicators.
- Relative Strength: 7 indicators.
- Breadth / Market Regime: 6 indicators.
- Overextension / Risk: 7 indicators.

Each indicator includes:

- Purpose.
- Formula or implementation definition.
- Required data.
- Timeframe.
- Sufficiency requirements.
- Common false positives.
- Redundancy risk.
- Signal role.
- Research priority.
- Dependencies.

## Families Cataloged

Trend / Structure:

- Measures whether price is organized above meaningful trend baselines or
  breaking structured ranges.

Momentum:

- Measures acceleration, directional persistence, and oscillator regime.

Volatility / Compression:

- Measures compression, range expansion, and volatility regime shifts.

Volume / Participation:

- Measures whether participation confirms price movement.

Relative Strength:

- Measures whether a candidate is outperforming QQQ, SPY, or sector context.

Breadth / Market Regime:

- Measures whether the broader tape supports momentum continuation.

Overextension / Risk:

- Measures whether strength may be late-stage, fragile, or already failing.

## Wave 1 Indicators

Wave 1 prioritizes high-value, relatively clear research indicators:

- Anchored VWAP.
- EMA stack / slope.
- ADX trend strength.
- Bollinger/Keltner squeeze release.
- ATR extension risk.
- Failed breakout detection.
- Relative strength vs QQQ/SPY.
- Volume confirmation / relative volume.

Why these come first:

- They align directly with the current breakout research path.
- They can be tested with daily OHLC, minute bars, volume, and benchmark data.
- They offer a useful balance of positive evidence and risk warnings.
- They are less dependent on sector mapping, broad breadth universes, or subjective inputs.

## Wave 2 Indicators

Wave 2 includes useful indicators that require clearer definitions or better
data coverage:

- Sector ETF relative strength.
- Darvas Box / range box.
- OBV / CMF / MFI.
- Volume dry-up then expansion.
- RSI regime.
- MACD / PPO.

Main dependencies:

- Reliable sector ETF mapping.
- Clear box/consolidation rules.
- Stronger volume-quality checks.
- Redundancy testing against simpler Wave 1 signals.

## Wave 3 Indicators

Wave 3 includes higher-complexity or more data-intensive indicators:

- Sector breadth.
- New highs vs new lows.
- VIX regime.
- Supertrend.
- TRIX.
- Stochastic RSI.
- Historical volatility percentile.

Main reasons for later placement:

- Broader universe data requirements.
- More parameter sensitivity.
- Higher redundancy risk.
- Greater need for long clean histories.

## Deferred Indicators

Indicators should remain deferred when:

- Required data is unavailable or unreliable.
- The calculation would introduce lookahead bias.
- The signal is too redundant to add research value.
- The definition depends on subjective trading decisions.
- Provider limitations make the indicator unsafe to automate.

## Redundancy Control

The redundancy map recommends family caps:

- Trend / Structure: max one independent family contribution.
- Breakout: max one independent family contribution.
- Volatility / Compression: max one independent family contribution.
- Volume / Participation: max one independent family contribution.
- Relative Strength: max one independent family contribution.
- Market Regime: gate or context, not a stock-level green vote.
- Risk / Overextension: warning or blocker, not bullish evidence.
- Data Quality: gate or context.

This prevents raw indicator counts from overstating confidence.

## Confluence Architecture

The architecture recommends storing both:

- Raw indicator states for transparency.
- Family-normalized states for decision-quality research.

Example:

```text
Trend Family: GREEN
Breakout Family: GREEN
Volume Family: GREEN
Relative Strength Family: YELLOW
Risk Family: CAUTION
Liquidity Gate: PASS
Data Quality: PARTIAL

Raw Green Checks: 23 / 30
Independent Green Families: 5 / 7
Major Red Flags: 0
Conclusion: STRONG_CONFLUENCE, not a trade recommendation
```

The conclusion remains research-only and must not feed production behavior
without a later approved task.

## Biggest Risks

- Overfitting remembered winners.
- Lookahead bias in breakout, box, squeeze, and relative-strength definitions.
- Redundant indicators creating fake confidence.
- Insufficient sample size before drawing conclusions.
- Sparse or stale provider data.
- Bad intraday relative volume if not time-normalized.
- Missing sector ETF mapping.
- Treating overextension as strength.
- Mixing intraday and daily timestamps incorrectly.
- Liquidity and spread risk when those inputs are missing.

## Recommended Next Implementation Slice

Recommended next slice:

`Technical Confluence Wave 1 Research Primitives`

Scope:

- Create a research-only module for Wave 1 indicators.
- Compute raw indicator states and family-normalized states.
- Generate local JSON/Markdown confluence reports.
- Include tests for insufficiency, redundancy handling, no scoring imports, and no source mutation.
- Do not connect the output to production scoring, readiness, alerts, trade planning, broker behavior, or UI workflows.

## Validation Plan For This Docs Slice

This slice should be validated with:

- Git diff review confirming only docs under `docs/research/` changed.
- Markdown/content review confirming all requested phases are represented.
- Protected-path review confirming no app, test, package, database, runtime, generated data, broker, scoring, readiness, alert, trade-planning, outcome, or UI files changed.

## Commit

Suggested commit:

`Add technical indicator registry and confluence roadmap`
