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
- Study Engine tab consolidation: group Catalyst Explorer, Catalyst Age, Headline Dedup, Outcome Explorer, Opportunity Research, and Readiness Gate into clearer research sections
- Recommendations tab rename/readiness gating so advisory weight notes cannot be mistaken for optimizer output

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

## Data Platform

- SQLite migration after clusters stabilize
- Replay database

## Trading Workflow

- Watchlist discipline enhancements
- Daily operator workflow consolidation: make Daily Checklist -> Morning Review -> Watchlist Report the obvious daily path
- Watchlist/Research List naming cleanup
- Workflow Discipline Analytics: compare reviewed vs unreviewed candidates, complete vs incomplete plans, watchlist vs non-watchlist, and workflow score vs actual outcomes
- Trade Plan Outcome Analysis: compare watchlist vs non-watchlist, plan complete vs incomplete, triggered vs never triggered, planned hold time vs actual best hold time, planned risk vs actual drawdown, and human-reviewed vs scanner-only candidates
- Entry Plan UI v2: compact mode, expand/edit mode, side-panel layout, and multi-monitor optimized morning layout
- Broker integration only after research validation
- Automated trading not planned until evidence exists

## Documentation

- Documentation encoding cleanup for mojibake in long-dash labels
- Dedicated roadmap/status document maintained separately from README and CHANGELOG
