# Momentum Hunter Future Ideas

This file tracks deferred ideas. Do not remove items without explicit justification.

## Research Engine

- Opportunity Score
- Opportunity Score v1 should only be designed after sufficient completed outcomes exist
- Walk-forward Opportunity Score validation
- Regime-specific Opportunity Score research
- Minimum sample-size thresholds before recommendations
- Score Weight Optimization with walk-forward testing
- Regime-specific scoring profiles
- Engine version comparison
- Top-score fixed-hold event study:
  - Test top 1/3/5/10 ranked candidates over 1/3/5/10-day holding windows
  - Include transaction costs, benchmark-relative returns, stop variants, MFE/MAE, walk-forward validation, and out-of-sample results
  - Require valid relative-volume handling and duplicate-observation controls before treating results as evidence

## Opportunity Detection

- Continuous watchlist polling loop for watchlist, interested, execution-ready, and user-defined symbols
- Active monitor scheduler service with GUI start/stop/status controls
- Automated daily system-readiness dispatch after scheduled captures and Evidence Autopilot runs
- Reliability trend dashboard showing provider health, monitor-cycle reliability, and evidence completion rates over time
- Active monitor cycle dashboard with current target coverage and missing-symbol warnings
- Live market-data backed alert outcome updater beyond trade-planning observation snapshots
- Tick-level MFE/MAE refinement beyond one-minute bars
- Target/stop path analysis using high/low intraday bars instead of snapshot prices
- User-tunable alert classification thresholds for Successful, Failed, Noise, and Late
- Best/worst alert-type leaderboards with minimum sample-size warnings
- Symbol-level alert performance tracking
- Readiness-state alert performance tracking
- Market-regime alert performance tracking
- Event-mode alert performance tracking for Fed/FOMC windows
- Audible/desktop notifications for high-confidence active alerts
- User-defined monitor symbol import/export tools
- Persistent monitor target center showing why each symbol is being watched
- Alert replay overlay showing exactly what was known when the alert fired
- Full trade-plan regeneration from refreshed monitor tape, preserved technical levels, and current execution context
- Intraday minute-bar provider quality and latency tracking for alert outcome validation
- Market Structure Validation Layer:
  - Prevent bad prints, isolated odd-lot trades, quote glitches, and liquidity vacuums from generating false alerts
  - For every alert, check volume confirmation, bid/ask confirmation, spread expansion, persistence of move, sector ETF correlation, and benchmark ETF correlation
  - Classify alert market structure as `VALID_MOVE`, `LOW_LIQUIDITY_MOVE`, `ETF_ANOMALY`, `ABNORMAL_PRICE_EVENT`, or `POSSIBLE_BAD_PRINT`
  - Do not allow abnormal market-structure events to generate execution-ready alerts
- Liquidity Sweep and Market Structure Detection:
  - Detect large one-bar moves, low-volume moves, immediate recoveries, multi-symbol simultaneous occurrences, ETF-wide anomalies, sector-wide anomalies, and price moves without bid/ask or volume confirmation
  - Classify events as `Liquidity Sweep`, `Possible Bad Print`, `ETF Anomaly`, `Genuine Breakdown`, `Genuine Breakout`, or `Abnormal Price Event`
  - Track stops that would have been hit, recovery time, event volume/spread, bid/ask behavior, and price after 1/5/15/30/60 minutes
  - Prevent abnormal events from generating execution-ready signals

## Catalyst Intelligence

- Catalyst quality scoring
- Catalyst date/age engine
- Catalyst age trend analysis by cluster and market regime
- Catalyst timestamp provider-quality report
- Historical replay overlay showing catalyst age beside original candidate score
- News freshness weighting
- Headline classification improvements
- Headline deduplication across syndicated articles
- Source-level timestamp reliability scoring
- Use source reliability as a confidence factor in future freshness analysis
- Use source reliability as an input to future catalyst quality, Opportunity Score, and research weighting
- Semantic event clustering
- Near-duplicate headline detection
- Multi-source catalyst consolidation
- Headline-to-event confidence scoring
- Earnings calendar integration
- Analyst recommendation tracking
- Newsletter ingestion
- Preserve excluded future-timestamp headline audit details for deeper news-quality analysis

## Historical Clustering

- Catalyst Cluster Explorer v2:
  - Refine Sector Sympathy classification
  - Add confidence score per catalyst classification
  - Catalyst classification confidence score trend analysis
  - Show percentage of headlines matched by explicit rules
  - Reduce catch-all cluster dominance
  - Display cluster purity metric
  - Cluster purity metric trend analysis
  - Example: AI Infrastructure purity 87%; Sector Sympathy purity 42%
- Earnings beat + guidance raise subclusters
- Earnings mention only subcluster
- AI partnership subcluster
- AI infrastructure subcluster
- Analyst upgrade subcluster
- Analyst target raise subcluster
- FDA binary event subcluster
- Biotech sympathy subcluster
- Historical sector leadership
- Historical theme rotation

## Study Engine

- Outcome distribution analysis
- Trade expectancy analysis
- Position sizing helper
- Paper trade journal
- Research Lab navigation v2: consider nested sections or a sidebar for Overview, Catalyst Research, Historical Review, and Data Readiness
- Locked Research Notes gating v2: hide or disable locked notes until Readiness Gate thresholds are met

## Market Calendar

- Early close support
- Special market closure support

## Market Cycle Research

- Automated Market-Cycle Classification
  - Compute an objective long-term `market_cycle` label from S&P 500 closing-price history.
  - Suggested labels: `bull`, `bear`, `transition`.
  - Use conventional 20% thresholds: bear after a broad-market decline of at least 20% from the prior cycle high; bull after a broad-market rise of at least 20% from the bear-market low.
  - Keep `market_cycle` distinct from the existing tactical `trading_regime` scoring overlay.
  - News may later be stored as supporting context, but headlines should not be the authoritative source.

## Data Quality

- Provider raw snapshot capture
- Conditional cross-provider verification only when prospective evidence identifies a consequential ambiguity that the current authoritative source cannot resolve
- Yahoo Finance only for a future named coverage or validation gap that Schwab cannot reasonably close; never as default strategy authority or a redundant vote
- Raw news timestamp audit improvements
- Runtime/version guard to detect stale GUI processes creating legacy captures without calendar metadata

## Provider Architecture

Priority: HIGH architectural guardrail.

- Prefer one authoritative source per functional job:
  - Schwab for strategy market data
  - Alpaca Paper for Paper order, fill, position, and buying-power truth
  - A separately approved live broker for future live execution truth
  - Explicitly attributed source evidence for news and catalysts
  - A separately approved source for overnight context only when a real coverage gap is demonstrated
- Do not add a provider, quote path, or candle path merely because another feed exists or agrees with the current feed.
- Do not average provider prices, vote providers, boost confidence from provider count, or treat overlapping exchange feeds as independent evidence.
- Preserve an execution broker's contemporaneous quote as execution evidence when available, but keep it separate from the Schwab evidence that formed the TradePlan.
- Do not rewrite or blend the TradePlan from the execution quote and do not create a divergence threshold before prospective evidence demonstrates a problem.
- Use Alpaca Paper to prove execution mechanics such as fractional submission, order types, protective orders, partial fills, cancel/replace, restart/recovery, exact liquidation, buying power, multi-position behavior, and reconciliation.
- Do not treat Paper fills or Paper profitability as strategy-edge proof. Strategy evidence remains prospective and includes chronology, no-trade decisions, losses, winners, rank-conditioned outcomes, regime context, realistic spread/slippage, and execution limitations.
- Treat overnight or Sunday-market evidence as `CONTEXT / RESEARCH` until separately validated for greater authority.
- Require every future provider proposal to state:
  - `PROBLEM` - the exact unresolved capability, reliability, validation, or coverage deficiency
  - `CURRENT SOURCE` - why the current authority cannot reasonably close the gap
  - `PROPOSED SOURCE` - the specific capability supplied
  - `COST` - engineering, complexity, subscriptions, credentials, reliability, and testing
  - `AUTHORITY` - the one named role the provider would own
  - `EXIT` - the condition under which the provider would be removed

## Conditional Execution-Source Validation

Problem:
If prospective execution evidence shows repeated material disagreement, stale-source ambiguity, unexplained slippage, or execution failures, Momentum Hunter may need a bounded comparison between its authoritative Schwab strategy evidence and execution-source evidence.

Possible discrepancies include:

- Bid/ask values
- Quote timestamps
- Volume reporting
- After-hours data
- Data latency

Future Conditional Goal:
Add only the smallest diagnostic needed to explain a proven discrepancy. This is not authorization for a permanent provider-voting system or redundant production market-data stack.

Validation checks:

- Last price agreement
- Bid/ask agreement
- Spread agreement
- Volume agreement
- Timestamp latency
- Alert timing differences

Success Criteria:
Momentum Hunter can explain a documented consequential discrepancy without averaging prices, voting providers, increasing confidence from provider count, or changing strategy authority retrospectively.

Long-Term Requirement:
Before a second provider gains production authority, prove the gap, assign the provider one named job, define removal criteria, and approve the resulting capability and security cost separately.

## Data Platform

- SQLite migration after clusters stabilize
- Replay database

## Trading Workflow

- Watchlist discipline enhancements
- Position Management / Exit Logic:
  - Manage short-term trading positions after entry with `HOLD`, `TRIM`, or `EXIT` outputs
  - Do not sell only because a position is profitable; ask whether the same position would still be opened today at the current price
  - Track entry price, current price, unrealized gain/loss, key support, breakout/reclaim level, relative strength vs QQQ, relative strength vs sector ETF, sector leadership, volume trend, momentum deterioration, and gap-up exhaustion risk
  - Keep profitable leaders as `HOLD` when leadership and breakout support remain intact
  - Use `TRIM` for extension or gap-up exhaustion risk, and `EXIT` for failed support/reclaim or broken leadership
- Full Daily Review Dashboard merge
- Daily operator workflow v2: consider a sidebar or guided flow for Daily Checklist -> Morning Review -> Generate Watchlist Report
- Watchlist Center
- Watchlist/report center v2 for saved watchlists, generated reports, and latest artifacts
- Guided first-run walkthrough
- Command palette / search actions
- User-customizable workflow layout
- Delayed Review Analytics
- Workflow Discipline Analytics: compare reviewed vs unreviewed candidates, complete vs incomplete plans, watchlist vs non-watchlist, and workflow score vs actual outcomes
- Trade Plan Outcome Analysis: compare watchlist vs non-watchlist, plan complete vs incomplete, triggered vs never triggered, planned hold time vs actual best hold time, planned risk vs actual drawdown, and human-reviewed vs scanner-only candidates
- Entry Plan UI v2: compact mode, expand/edit mode, side-panel layout, and multi-monitor optimized morning layout
- Broker integration only after research validation
- Automated trading not planned until evidence exists

## Documentation

- Documentation encoding cleanup for mojibake in long-dash labels
- Dedicated roadmap/status document maintained separately from README and CHANGELOG

## QA / Test Harness Reliability

- Qt test harness hardening:
  - Keep broad Qt unittest modules out of routine validation unless they are being specifically debugged.
  - Prefer isolated offscreen probes with hard timeouts, bytecode disabled, and explicit Python process checks.
  - Add a small test-runner helper that executes one risky Qt probe at a time and kills only the spawned test process on timeout.
  - Record the exact command that hangs before attempting any retry.

## Architecture Modernization / Rewrite Decision

- Do not rewrite Momentum Hunter now.
- Modernize PySide6 first with a real design system and extracted UI modules.
- Treat `momentum_hunter/app.py` as the first major refactor target because it mixes shell navigation, UI construction, workflow mapping, scanner orchestration, report rendering, formatting, and styling.
- Keep scanning, scoring, evidence, replay, SQLite/storage, Daily Workflow facts, TradePlan, and future Risk Governor behavior in Python.
- Define backend/frontend DTO and command boundaries before choosing C# WinUI, Avalonia, or Tauri.
- Revisit a frontend rewrite only after the R001-R005 architecture tasks prove the boundary and improve the visible UI.
