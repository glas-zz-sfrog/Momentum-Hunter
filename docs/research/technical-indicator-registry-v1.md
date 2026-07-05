# Technical Indicator Registry v1

This registry defines candidate technical indicators for a future Momentum Hunter
Technical Confluence Matrix. It is research infrastructure only. It does not
change scoring, readiness, alerts, trade planning, outcome classification,
broker behavior, automated trading, or UI workflows.

The purpose is to catalog indicators with enough precision to research whether
they add independent evidence. A high raw count such as "29 of 30 green" must
not imply confidence unless the checks come from independent signal families and
survive event-study validation.

## Registry Fields

Each indicator is documented with:

- Name: operator-facing name and common abbreviation when useful.
- Family: primary signal family.
- Purpose: the research question the indicator answers.
- Formula / definition: implementation-ready calculation guidance.
- Required data: input bars, benchmark series, volume, sector mapping, or other fields.
- Timeframe: daily, intraday, swing, market-regime, or mixed.
- Data sufficiency requirements: minimum lookback and unavailable-data handling.
- Common false positives: conditions where the signal can mislead.
- Redundancy risk: related indicators that may measure the same thing.
- Signal role: primary signal, confirmation signal, warning signal, or blocker/gate.
- Research priority: Wave 1, Wave 2, Wave 3, or Deferred.
- Dependencies: daily OHLC, minute bars, volume, float, bid/ask, sector ETF mapping, QQQ/SPY baseline, or catalyst/headline data.

## Trend / Structure

| Name | Role / Priority | Purpose | Formula / Definition | Required Data / Timeframe / Sufficiency | False Positives | Redundancy / Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| EMA stack | Primary signal / Wave 1 | Detect organized trend structure and whether shorter trend baselines are above longer baselines. | Compute 8, 20, and 50 period EMAs by default. Green when close > EMA8 > EMA20 > EMA50 and EMA20 slope is positive. Yellow when close is above EMA20 but stack is incomplete. | Daily OHLC close series. Minimum 60 completed daily bars. If fewer bars exist, report `Insufficient data`. | Late-stage runs can look perfect immediately before reversal. Thin stocks can print artificial closes above EMAs. | Overlaps with SMA position, Supertrend, MACD, PPO, and ADX. Depends on daily OHLC. |
| 20/50/200 SMA position | Primary signal / Wave 1 for 20/50, Wave 3 for 200 | Measure whether price is above key institutional trend baselines. | Compute SMA20, SMA50, and SMA200. Green when close > SMA20 > SMA50 > SMA200. Partial state allowed when only 20/50 are available. | Daily OHLC close series. Minimum 50 bars for 20/50 state, 200 bars for full state. Missing SMA200 must not block 20/50 research. | Newly listed names may lack 200-day history. A stock can be above averages because it is overextended, not because risk/reward is favorable. | Overlaps with EMA stack, ADX, Supertrend, MACD, PPO. Depends on daily OHLC. |
| ADX trend strength | Confirmation signal / Wave 1 | Separate actual trend from sideways chop without declaring direction. | Compute Wilder ADX14 from +DI and -DI. Green trend-strength confirmation when ADX >= 20 or 25 and rising over the prior 3 to 5 bars. Direction must come from price or DI state, not ADX alone. | Daily OHLC high/low/close. Minimum 30 daily bars. If directional movement cannot be calculated, report unavailable. | ADX can rise during downside trends. It can lag after the strongest part of a move. | Overlaps with moving-average alignment, MACD, Supertrend. Depends on daily OHLC. |
| Supertrend | Confirmation signal / Wave 3 | Provide a volatility-adjusted trend state that flips when price crosses ATR bands. | Compute ATR10 by default and bands using multiplier 3.0. Trend is green when close remains above the active Supertrend line. | Daily OHLC high/low/close. Minimum 30 bars. Mark unavailable when ATR cannot be calculated. | Whipsaws in choppy names. Parameter sensitivity can create overfit states. | Overlaps with ATR extension, Keltner channels, EMA/SMA trend. Depends on daily OHLC. |
| Anchored VWAP | Primary signal / Wave 1 | Compare price to volume-weighted fair value from a meaningful event. | From an anchor date/time, compute cumulative sum(price * volume) / cumulative volume. Research anchors: earnings date, major gap day, breakout day, or latest candidate capture. Green when price holds above anchored VWAP after reclaim. | Minute bars preferred for intraday anchors; daily OHLCV acceptable for daily anchors. Requires anchor event and volume. Minimum anchor-to-current span of 5 bars for research state. | Bad anchor choice can create fake precision. Low-volume prints distort VWAP. | Overlaps with distance above VWAP and volume confirmation. Depends on minute bars or daily OHLCV, volume, and catalyst/event context. |
| Darvas Box / range box breakout | Primary signal / Wave 2 | Detect structured consolidation followed by breakout above a range high. | Define a box when price remains inside a recent high/low range for N bars, default 10 to 20. Breakout occurs when close crosses above box high after the box is established. | Daily OHLC high/low/close. Minimum 30 bars. Box rules must use completed prior bars only. | Loose definitions can classify random chop as a box. Earnings gaps can skip the range structure entirely. | Overlaps with Donchian breakouts, range breakouts, Bollinger/Keltner expansion. Depends on daily OHLC. |

## Momentum

| Name | Role / Priority | Purpose | Formula / Definition | Required Data / Timeframe / Sufficiency | False Positives | Redundancy / Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| RSI regime | Confirmation signal / Wave 2 | Classify whether momentum is persistently constructive rather than only overbought or oversold. | Compute RSI14. Green regime when RSI holds above 50 for multiple bars and reaches 60 to 70 during advances. Warning when RSI > 80 after a multi-day run. | Daily OHLC close series. Minimum 20 bars. Report unavailable when RSI window is incomplete. | High RSI can mean strength or exhaustion. Mean-reverting names can fail after high RSI readings. | Overlaps with ROC, MACD, PPO, Stochastic RSI. Depends on daily OHLC. |
| MACD cross | Confirmation signal / Wave 2 | Detect a momentum inflection when faster trend momentum crosses slower signal. | Compute MACD as EMA12 - EMA26 with EMA9 signal line. Green event when MACD crosses above signal line. | Daily OHLC close series. Minimum 35 bars. Use completed bars only. | Crosses often occur late. Sideways markets can produce repeated false crosses. | Overlaps with EMA stack, PPO, TRIX, RSI regime. Depends on daily OHLC. |
| MACD histogram expansion | Confirmation signal / Wave 2 | Measure whether momentum is accelerating after an inflection. | MACD histogram = MACD - signal. Green when histogram is positive and expanding for at least 2 consecutive bars. | Daily OHLC close series. Minimum 35 bars. Report insufficient if prior histogram values are missing. | Can peak before price peaks. Expansion after a gap can be short lived. | Overlaps with MACD cross, PPO, ROC. Depends on daily OHLC. |
| Rate of Change | Confirmation signal / Wave 2 | Measure direct price momentum over a fixed lookback. | ROC_N = (close_today / close_N_bars_ago - 1) * 100. Default N values: 10, 20, and 60 for research comparison. | Daily OHLC close series. Minimum N + 1 bars per window. | High ROC can reflect exhaustion. Low-priced stocks can show extreme ROC from small absolute moves. | Overlaps with RSI, PPO, MACD, relative strength slope. Depends on daily OHLC. |
| PPO | Confirmation signal / Wave 2 | Compare MACD-style momentum across differently priced stocks. | PPO = (EMA12 - EMA26) / EMA26 * 100. Signal line is EMA9 of PPO. Green when PPO crosses above signal or histogram expands. | Daily OHLC close series. Minimum 35 bars. | Same lag and whipsaw risk as MACD. | Highly redundant with MACD and EMA momentum. Depends on daily OHLC. |
| Stochastic RSI | Secondary confirmation / Wave 3 | Detect short-term momentum shifts inside RSI. | StochRSI = (RSI - lowest RSI over N) / (highest RSI over N - lowest RSI over N), default N = 14. | Daily close series. Minimum 30 bars. Report unavailable when RSI range is zero or incomplete. | Very sensitive and noisy. Can fire repeatedly in strong trends. | Overlaps with RSI regime and short ROC. Depends on daily OHLC. |
| TRIX | Secondary confirmation / Wave 3 | Measure smoothed trend momentum and filter noise. | Compute triple-smoothed EMA of close, then one-period percentage rate of change of that triple EMA. | Daily OHLC close series. Minimum 60 bars. | Heavy smoothing can lag. It may add little beyond EMA/PPO. | Overlaps with PPO, MACD, EMA slope. Depends on daily OHLC. |

## Volatility / Compression

| Name | Role / Priority | Purpose | Formula / Definition | Required Data / Timeframe / Sufficiency | False Positives | Redundancy / Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| Bollinger Bandwidth squeeze | Primary signal / Wave 1 | Detect volatility compression before possible expansion. | Bollinger Bandwidth = (upper band - lower band) / SMA20. Squeeze when bandwidth is in the lowest 20th percentile of its prior 120 readings, or below a research threshold when history is short. | Daily OHLC close series. Minimum 40 bars for basic state; 140 bars for percentile state. | Compression can persist for weeks. Low liquidity can mimic compression. | Overlaps with Keltner squeeze and historical volatility percentile. Depends on daily OHLC. |
| Bollinger inside Keltner squeeze release | Primary signal / Wave 1 | Detect compression followed by volatility expansion. | Compression when Bollinger Bands sit inside Keltner Channels. Release when close breaks above upper Bollinger or Keltner after compression. | Daily OHLC high/low/close. Minimum 40 bars. Must use prior completed compression state before release. | Breaks can fail immediately if volume or relative strength is weak. | Overlaps with Bollinger breakout, Keltner breakout, ATR expansion. Depends on daily OHLC. |
| ATR expansion | Confirmation signal / Wave 2 | Measure whether price range is expanding versus recent baseline. | ATR14 current compared with SMA20 of ATR14. Green expansion when ATR14 > 1.25x ATR average and price direction confirms. | Daily OHLC high/low/close. Minimum 35 bars. | ATR expands on downside volatility too. News shocks can produce one-day spikes. | Overlaps with average daily range expansion and Keltner channels. Depends on daily OHLC. |
| Historical volatility percentile | Confirmation signal / Wave 3 | Compare current volatility to the stock's own distribution. | Compute rolling standard deviation of daily returns, then percentile rank versus prior 120 to 252 observations. | Daily OHLC close series. Minimum 150 bars preferred. | High volatility can mean instability rather than opportunity. Adjusted data policy matters. | Overlaps with Bollinger bandwidth and ATR expansion. Depends on daily OHLC. |
| Gap-and-hold behavior | Primary signal / Wave 1 | Determine whether a gap keeps control instead of fading. | Gap up when today's open > prior high or exceeds prior close by a threshold. Hold when intraday or closing price remains above prior high/opening range level. | Daily OHLC for gap; minute bars improve hold quality. Minimum prior bar plus current session data. | Pre-market gaps can fade quickly. News spikes can hold briefly and fail later. | Overlaps with opening-range breakout, failed breakout, volume confirmation. Depends on daily OHLC and preferably minute bars. |
| Average daily range expansion | Confirmation signal / Wave 2 | Measure whether the daily high-low range is expanding versus recent norms. | ADR_N = average(high - low) or average((high - low) / close) over N days, default N = 20. Expansion when current range > 1.5x ADR20. | Daily OHLC high/low/close. Minimum 25 bars. | Expanded range can be exhaustion or downside volatility. | Overlaps with ATR expansion. Depends on daily OHLC. |

## Volume / Participation

| Name | Role / Priority | Purpose | Formula / Definition | Required Data / Timeframe / Sufficiency | False Positives | Redundancy / Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| Relative volume | Confirmation signal / Wave 1 | Confirm whether current participation is above normal. | RVOL = current volume / average volume for comparable period. Daily default uses prior 20 completed daily bars. Intraday default requires time-of-day normalization when available. | Daily or minute volume. Minimum 20 completed comparable periods. | Intraday RVOL is misleading if not time-normalized. One-off news can spike volume without continuation. | Overlaps with volume above average and volume climax. Depends on volume. |
| Volume above 20-day average | Confirmation signal / Wave 1 | Simple daily participation check. | Current daily volume > SMA20 of prior completed daily volume. Strong confirmation at >= 1.5x. | Daily volume. Minimum 21 daily bars. | Low float or low liquidity names can show extreme ratios from small baselines. | Overlaps with RVOL and volume climax. Depends on daily OHLCV. |
| OBV new highs | Confirmation signal / Wave 2 | Test whether cumulative volume pressure confirms price strength. | Add volume on up-close days, subtract volume on down-close days, unchanged on flat days. Green when OBV reaches a 20-day or 50-day high before or with price breakout. | Daily close and volume. Minimum 50 bars preferred. | OBV can distort on split-adjusted or sparse volume data. | Overlaps with CMF, MFI, Accumulation/Distribution. Depends on daily OHLCV. |
| Money Flow Index | Confirmation signal / Wave 2 | Combine price and volume into a bounded participation oscillator. | Use typical price and volume to compute positive and negative money flow over 14 periods, then MFI. Green regime when MFI is improving and above 50; warning when extremely high after a run. | Daily high/low/close/volume. Minimum 20 bars. | Like RSI, high values can mean strength or exhaustion. | Overlaps with RSI and CMF. Depends on daily OHLCV. |
| Chaikin Money Flow | Confirmation signal / Wave 2 | Estimate whether closes are occurring near high or low of bars with volume weight. | Money flow multiplier = ((close - low) - (high - close)) / (high - low). CMF20 = sum(multiplier * volume) / sum(volume). | Daily high/low/close/volume. Minimum 21 bars. Handle zero high-low range explicitly. | Gap days can distort close-location logic. Narrow bars with high volume can dominate. | Overlaps with Accumulation/Distribution and MFI. Depends on daily OHLCV. |
| Accumulation/Distribution trend | Confirmation signal / Wave 2 | Track whether volume-weighted close location is improving over time. | Cumulative sum of money flow volume using close location value. Green when A/D line makes higher highs or has positive slope into breakout. | Daily high/low/close/volume. Minimum 50 bars preferred. | Same close-location issues as CMF. Cumulative series can drift. | Overlaps with CMF and OBV. Depends on daily OHLCV. |
| Up-volume vs down-volume | Confirmation signal / Wave 2 | Compare volume on advancing bars versus declining bars. | Over N bars, sum volume on up-close bars and divide by sum volume on down-close bars. Default N = 10 or 20. | Daily close and volume, or minute bars for intraday variant. Minimum N + 1 bars. | Direction classification can be noisy in flat closes. | Overlaps with OBV and volume confirmation. Depends on volume. |
| Volume dry-up before breakout then expansion | Primary confirmation / Wave 2 | Detect quiet consolidation followed by participation expansion. | Dry-up when average volume during the consolidation window is below prior baseline, followed by breakout volume > 1.5x prior 20-day average. | Daily OHLCV and defined consolidation window. Minimum 40 bars. | Dry-up can reflect loss of interest, not constructive absorption. | Overlaps with squeeze, RVOL, Darvas Box. Depends on daily OHLCV. |

## Relative Strength

| Name | Role / Priority | Purpose | Formula / Definition | Required Data / Timeframe / Sufficiency | False Positives | Redundancy / Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| Stock vs QQQ | Primary confirmation / Wave 1 | Determine whether a candidate is outperforming a growth-heavy benchmark. | RS ratio = stock close / QQQ close. Green when ratio is rising over 20 days or making a recent high. | Daily OHLC close for stock and QQQ. Minimum 25 aligned bars. | Outperformance can occur because QQQ is weak rather than stock is strong. | Overlaps with stock vs SPY and RS slope. Depends on QQQ baseline. |
| Stock vs SPY | Primary confirmation / Wave 1 | Determine whether a candidate is outperforming the broad market. | RS ratio = stock close / SPY close. Green when ratio slope is positive or ratio reaches a lookback high. | Daily close for stock and SPY. Minimum 25 aligned bars. | Defensive outperformance can appear in weak markets without momentum quality. | Overlaps with stock vs QQQ. Depends on SPY baseline. |
| Stock vs sector ETF | Confirmation signal / Wave 2 | Determine whether the stock is stronger than its industry or sector context. | RS ratio = stock close / mapped sector ETF close. Green when ratio rises over 20 or 60 days. | Daily close for stock and sector ETF plus mapping. Minimum 25 aligned bars. | Bad sector mapping can misclassify the benchmark. | Overlaps with stock vs QQQ/SPY. Depends on sector ETF mapping. |
| Sector ETF vs QQQ/SPY | Market context / Wave 2 | Determine whether the candidate's sector is in favor. | Sector RS ratio = sector ETF close / QQQ or SPY close. Green when sector ratio is rising and sector ETF trend is constructive. | Daily close for sector ETF and benchmark. Minimum 25 aligned bars. | Sector strength can mask weak individual stock behavior. | Overlaps with market regime and sector breadth. Depends on sector ETF mapping and benchmarks. |
| 20-day relative strength slope | Confirmation signal / Wave 1 | Measure short-term improvement in benchmark-relative performance. | Compute slope or percentage change of RS ratio over 20 bars. Green when positive and improving. | Daily stock and benchmark close. Minimum 25 aligned bars. | Short windows can be noisy. Gap-driven moves can dominate slope. | Overlaps with RS new high and stock-vs-benchmark checks. Depends on QQQ/SPY baseline. |
| 60-day relative strength slope | Confirmation signal / Wave 2 | Measure intermediate relative strength trend. | Compute slope or percentage change of RS ratio over 60 bars. Green when positive. | Daily stock and benchmark close. Minimum 65 aligned bars. | Slower signal can lag early breakouts. | Overlaps with 20-day RS slope and RS new high. Depends on QQQ/SPY baseline. |
| Relative strength new high | Primary confirmation / Wave 1 | Detect when relative performance is leading price action. | RS ratio reaches highest value over prior 20, 50, or 60 completed bars. | Daily stock and benchmark close. Minimum selected lookback + 1 aligned bars. | A new RS high can occur while both stock and market are falling. | Overlaps with RS slope. Depends on QQQ/SPY baseline. |

## Breadth / Market Regime

| Name | Role / Priority | Purpose | Formula / Definition | Required Data / Timeframe / Sufficiency | False Positives | Redundancy / Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| QQQ above 20/50/200 | Market gate / Wave 1 for 20/50, Wave 3 for 200 | Determine whether the growth benchmark supports momentum setups. | Compute QQQ close relative to SMA20, SMA50, and SMA200. Green when above key averages and slopes are positive. | Daily QQQ OHLC. Minimum 50 bars for 20/50, 200 for full state. | Index strength can be concentrated in a few mega caps. | Overlaps with risk-on/risk-off state. Depends on QQQ baseline. |
| SPY above 20/50/200 | Market gate / Wave 1 for 20/50, Wave 3 for 200 | Determine whether broad market conditions are supportive. | Compute SPY close relative to SMA20, SMA50, and SMA200. | Daily SPY OHLC. Minimum 50 bars for 20/50, 200 for full state. | Broad strength may not help speculative momentum names. | Overlaps with QQQ state and risk-on/risk-off state. Depends on SPY baseline. |
| Sector breadth | Market context / Wave 3 | Measure how many stocks in a sector are participating. | Percentage of sector constituents above SMA20/SMA50 or making 20-day highs. | Sector constituent universe and daily OHLC. Minimum 50 bars per constituent. | Constituent lists can be stale or unavailable. | Overlaps with sector ETF trend. Depends on sector mapping and daily OHLC. |
| New highs vs new lows | Market context / Wave 3 | Estimate market risk appetite and breadth quality. | Count universe members making N-day highs versus N-day lows, default 20 and 52-week variants. | Broad symbol universe and daily OHLC. Minimum lookback + 1 bars per symbol. | Universe selection strongly affects results. | Overlaps with sector breadth and risk regime. Depends on broad daily OHLC universe. |
| VIX trend / volatility regime | Market gate / Wave 3 | Classify whether broad volatility backdrop is calm, rising, or stressed. | Use VIX close relative to SMA20/SMA50 and recent percentage change. Rising VIX can mark caution. | Daily VIX data. Minimum 50 bars. | VIX can fall while individual momentum names fail. | Overlaps with risk-on/risk-off state. Depends on external index data. |
| Risk-on / risk-off market state | Market gate / Wave 3 | Combine benchmark trend, volatility, and breadth into one market-context label. | Research-only composite from QQQ/SPY trend, VIX trend, sector breadth, and new highs/lows. Must expose component states. | Benchmarks, VIX, breadth inputs. Minimum depends on components. | Composite can hide disagreement between components. | Aggregates many market-regime signals and must not become production readiness without explicit approval. |

## Overextension / Risk

| Name | Role / Priority | Purpose | Formula / Definition | Required Data / Timeframe / Sufficiency | False Positives | Redundancy / Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| Distance above 20 EMA | Warning signal / Wave 1 | Flag late-stage extension above short-term trend. | Distance = (close / EMA20 - 1) * 100. Warning thresholds should be researched by symbol volatility bucket, not hard-coded as trade rules. | Daily close. Minimum 25 bars. | Strong stocks can remain extended. Low-volatility and high-volatility names need different thresholds. | Overlaps with ATR extension and RSI > 80. Depends on daily OHLC. |
| Distance above VWAP | Warning signal / Wave 1 | Flag intraday extension above volume-weighted fair value. | Distance = (current price / session VWAP - 1) * 100, or anchored VWAP variant. | Minute bars with price and volume. Minimum enough bars to compute VWAP from anchor/session start. | VWAP can be distorted by low volume or abnormal opening prints. | Overlaps with anchored VWAP. Depends on minute bars and volume. |
| ATR extension | Warning signal / Wave 1 | Normalize extension by the stock's own range. | Extension = (close - EMA20 or breakout trigger) / ATR14. Warning when extension is high relative to historical outcomes. | Daily high/low/close. Minimum 35 bars. | Large extension can be justified by major catalyst; context matters. | Overlaps with distance above EMA and ADR expansion. Depends on daily OHLC. |
| RSI > 80 after multi-day run | Warning signal / Wave 2 | Mark possible exhaustion after persistent momentum. | RSI14 > 80 and close has advanced across multiple recent bars or ROC is high. | Daily close. Minimum 20 bars. | Strong growth names can ride high RSI. Warning must not be treated as automatic bearish state. | Overlaps with RSI regime and ROC. Depends on daily OHLC. |
| Gap too large without consolidation | Warning signal / Wave 1 | Flag unstable moves where price has not built support. | Gap percentage versus prior close/high exceeds researched threshold, and no consolidation bars have formed above the gap level. | Daily OHLC and preferably minute bars. Minimum prior day plus current intraday data. | Some catalyst gaps hold cleanly. Missing catalyst data can misclassify. | Overlaps with gap-and-hold and failed breakout. Depends on daily OHLC, minute bars, and catalyst context. |
| Volume climax | Warning signal / Wave 2 | Detect possible exhaustion after unusually high participation. | Current volume >= 3x or 5x prior 20-day average after a multi-day advance, especially with wide range or close off highs. | Daily OHLCV. Minimum 21 bars. | True institutional accumulation can also show huge volume. | Overlaps with RVOL and volume confirmation. Depends on volume. |
| Failed breakout back below trigger | Blocker/gate / Wave 1 | Identify when a breakout has lost its trigger level. | After breakout event, flag failed when close or intraday price falls back below trigger level within defined follow-up window. | Daily or minute OHLC after event. Requires trigger level and forward bars. | Brief shakeouts can recover. Failure criteria must be time-bound. | Overlaps with event-study failure logic. Depends on breakout events and forward OHLC. |

## Research-Only Boundary

The registry may support future labels such as:

- `Breakout present`
- `Breakout absent`
- `Trend confirming`
- `Volume confirming`
- `Relative strength improving`
- `Risk caution`
- `Insufficient data`

It must not produce trade instructions, Opportunity Score, production readiness changes,
alert threshold changes, broker actions, or automated orders.

## References Consulted

- StockCharts ChartSchool technical indicator documentation:
  [Average Directional Index](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-directional-index-adx),
  [MACD](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-moving-average-convergence-divergence-oscillator),
  [Bollinger BandWidth](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/bollinger-bandwidth),
  [Chaikin Money Flow](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/chaikin-money-flow-cmf),
  [Money Flow Index](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/money-flow-index-mfi), and
  [On Balance Volume](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv).
- Investopedia background references for
  [VWAP](https://www.investopedia.com/terms/v/vwap.asp),
  [Relative Strength Index](https://www.investopedia.com/terms/r/rsi.asp), and
  [Supertrend](https://www.investopedia.com/supertrend-indicator-7976167).
