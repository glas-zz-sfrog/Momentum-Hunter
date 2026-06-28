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
- Multi-provider verification
- Yahoo Finance provider
- Raw news timestamp audit improvements
- Runtime/version guard to detect stale GUI processes creating legacy captures without calendar metadata

## Broker-Grade Market Data Validation Layer

Problem:
Momentum Hunter currently relies on public market-data sources such as Nasdaq web data and Yahoo chart data. These are acceptable for screening, monitoring, alert generation, paper validation, and outcome testing.

However, public feeds may differ from broker/execution feeds in:

- Bid/ask values
- Quote timestamps
- Volume reporting
- After-hours data
- Data latency

Future Goal:
Add a broker-grade validation layer that compares Momentum Hunter's market data against execution-source data.

Potential providers:

- Schwab API
- Interactive Brokers
- Polygon
- IEX Cloud
- Nasdaq official feeds
- Fidelity, if usable data access exists

Validation checks:

- Last price agreement
- Bid/ask agreement
- Spread agreement
- Volume agreement
- Timestamp latency
- Alert timing differences

Success Criteria:
Momentum Hunter can report whether an alert would have been detected at approximately the same time using broker-grade market data.

Long-Term Requirement:
Before automated trading is enabled, require broker-grade quote confirmation for all execution-ready trade signals.

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

## Future Ideas Parking Lot - Momentum Hunter / Argus

### Frontend Modernization Spike
Investigate whether Momentum Hunter should remain PySide6 with a modern design system or eventually migrate the frontend to C# WinUI 3, Avalonia, or a Tauri/web-style shell.

Key questions:
- Can PySide6 be made modern enough with a real design system?
- Would C# WinUI 3 give the best native Windows experience?
- Would Avalonia help if cross-platform matters?
- Would Tauri/web offer the most polished dashboard experience?
- How can we separate the Python engine from the UI so the frontend can be replaced later?

### Momentum Hunter Design System
Create a reusable visual system:
- dark premium trading theme
- gold/red accent language
- modern cards
- status pills
- mode banners
- warning states
- locked/live/paper visual language
- Trade Plan Ladder visual components
- consistent spacing and typography

This should improve the dated "Netscape browser from 1998" feel without requiring an immediate rewrite.

### Steven Desk vs Argus Machine Gateway
Preserve the two-door product split:
- Steven Desk: human-guided momentum operations
- Argus Machine: autonomous planning, simulation, paper trading, and future execution control

The gateway should feel intentional and high-stakes, not like a basic menu. It creates a safety boundary between human review and machine supervision.

### Trade Plan Ladder Visual System
Continue developing Trade Plan Ladder as a major autonomous-side component.

It should show:
- Top 5 Trade Plan Candidates
- clickable ticker rows
- selected ticker details
- entry trigger
- entry/limit price
- invalidation / hard stop
- Target 1 / Target 2 / Target 3
- trailing stop rule
- position size
- max dollar risk
- risk/reward
- manual override state
- Risk Governor status

The generated "Trade Plan Ladder" button/asset is good enough as an early visual direction and can be refined later.

### Top 5 Trade Plan Candidates
Argus Machine should show the top five candidate trade plans as clickable ticker rows. Clicking a ticker should populate the Trade Plan Ladder.

Avoid implying these are approved live trades. Prefer labels like:
- Top 5 Setups
- Top 5 Trade Plan Candidates
- Top 5 Machine Plans

Avoid "Strongest Trades" until Risk Governor and paper outcomes justify that language.

### Chart Analyst Agent
Add a dedicated Chart Analyst lane for read-only technical analysis:
- trend/posture
- support/resistance
- gap behavior
- volume confirmation
- relative volume
- moving average posture if available
- invalidation level
- chase risk
- final label: ignore / monitor / watchlist / deeper review

Chart analysis should support candidate review, not directly change scoring or execution.

### Public Equity Investing Research Desk
Use public-equity-investing as a read-only research layer around Momentum Hunter candidates.

It should help with:
- company snapshot
- catalyst context
- earnings risk
- valuation context
- bull/bear thesis
- thesis invalidation
- portfolio/risk flags

Default policy: read-only decision support only. It may not change scoring, readiness, alerts, broker behavior, or execution without a Goal Charter and Steven approval.

### Execution Console and Machine Log
Argus Machine needs an always-visible Machine Log and Execution Console so Steven can see:
- what Argus is doing
- why it is doing it
- what data it used
- what is blocked
- what needs approval
- what mode it is in
- whether live trading is locked

Every future simulated, paper, or live action should be audit-logged.

### Paper / Live Safety Language
Keep strong mode separation:
- Simulation Lab
- Paper Trading
- Live Trading Locked
- Live Preview only
- Confirmed Live Execution later
- Supervised Automation much later

Live trading should never be a casual toggle.

### Screenshot Validation Repair
Future UI proof should validate that screenshots are real:
- file exists
- nonzero dimensions
- nontrivial file size
- not blank
- expected labels/panels visible or verified by UI inspection

This prevents false confidence from broken screenshot capture.

### TradePlan / Risk Governor Follow-Ups
Track follow-up questions from ARGUS-A004/A005:
- Should future UI require all three targets, or is at least one target enough?
- Should TradePlan fields be renamed before UI wiring?
- Should live-preview remain fully locked until a separate approval model exists?
- How should manual override re-checks appear in the UI?
- What is the exact mapping from Top 5 candidates into real TradePlan objects?

### Argus Office as a Reusable Company-in-a-Box
If the Argus Office model works, adapt it later for Honda work:
- NARS automation
- TagTracker
- QMF/SAP BI workflow support
- dashboard/report generation
- work-process automation

Reusable pattern:
- CEO / final approver
- ChatGPT advisor
- Goal Steward
- Git Steward
- Builder
- QA
- domain specialists
- Release Scribe
- Hard Chew Protocol
