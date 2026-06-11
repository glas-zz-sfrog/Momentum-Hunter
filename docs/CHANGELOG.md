# Momentum Hunter Changelog

## 2026-06-11

### Added

- Added Operator Navigation Cleanup v1.
- Renamed top-level workflow actions to `Daily Checklist`, `Morning Review`, `Capture Health`, `Generate Watchlist`, `Latest Watchlist`, `Open Historical Snapshot`, `Current Dashboard`, and `Research Study`.
- Grouped Study tabs with purpose prefixes: `Overview`, `Catalyst`, `Readiness`, and `Locked Research Notes`.
- Added Documentation, Workflow, and Roadmap Audit v1.
- Added `docs/ROADMAP_AUDIT.md` with UI view purpose/workflow notes, roadmap status, feature inventory, duplicate-functionality findings, documentation findings, future-idea findings, and recommended next milestone.
- Added deferred ideas for Study Engine consolidation, daily operator workflow consolidation, Watchlist/Research List naming cleanup, Recommendations readiness gating, and documentation encoding cleanup.
- Added Daily Workflow Checklist / Review Report v1.
- Added a `Daily Checklist` toolbar action with capture status, review status, entry-plan status, outcome status, readiness status, workflow warnings, and a workflow-discipline score.
- Added quick actions for Open Morning Review, Generate Watchlist, Open Capture Health, and Open Readiness Gate.
- Added Daily Workflow Checklist screenshot generation for documentation evidence.
- Added Morning Review Workspace v1.
- Added a `Morning Review` toolbar action with a focused candidate table, compact Decision Card, score/catalyst/freshness context, source and duplicate warning context, review actions, and entry-plan editing.
- Added quick actions for Mark Interested, Mark Rejected, Add to Watchlist, Open Why Score, and Open Timeline/Replay.
- Added Morning Review screenshot generation for documentation evidence.

### Safety

- Operator Navigation Cleanup v1 is UI/navigation-only and does not add trading logic, scoring changes, Opportunity Score, optimizer work, broker integration, SQLite migration, or new research engines.
- Documentation, Workflow, and Roadmap Audit v1 is documentation-only and does not add trading logic, scoring changes, optimizer work, broker integration, or SQLite migration.
- Daily Workflow Checklist is workflow tracking only and does not add scoring changes, Opportunity Score, optimization, broker integration, order placement, SQLite migration, or automated trading.
- The workflow score measures daily process completion only and does not evaluate trade quality.
- Morning Review is workflow/UI only and does not add broker integration, order placement, Opportunity Score, optimizer logic, scoring changes, SQLite migration, or automated trading.
- Current/live data can be reviewed and edited; stale, historical, replay, and study-style views remain clearly warned and read-only.
- Review decisions and entry plans continue to live in derived stores and do not mutate immutable raw captures.

### Tests

- No tests were added for the documentation-only audit because no runtime behavior changed.
- Added tests for deterministic Daily Workflow counts, workflow score math, warning triggers, raw-capture immutability, and read-only historical/study quick-action behavior.
- Added tests for current Morning Review editing, stale-data warnings, historical/study read-only behavior, raw-capture immutability, selected-candidate Decision Card updates, and incomplete-plan warnings.

## 2026-06-09

### Added

- Added Watchlist Discipline / Entry Plan v1.
- Added `entry-plans.json` as a separate user planning store keyed by candidate identity.
- Expanded the Entry Plan UI with trigger, stop, thesis, invalidation, max loss, position size idea, planned hold time, notes, and Plan Complete status.
- Added incomplete-plan warnings for missing trigger, stop, invalidation, and max loss.
- Added entry-plan fields to Watchlist Report output.

### Safety

- Entry plans are planning/journaling records only and do not place orders, integrate brokers, create Opportunity Score, optimize weights, mutate raw captures, or write SQLite records.
- Historical, Replay, and Study views remain read-only for entry-plan editing.

### Tests

- Added tests for entry-plan persistence, raw-capture immutability, read-only historical behavior, watchlist report output, and incomplete-plan warnings.

### Added

- Added Historical Cluster Display recurrence refinement.
- Added ticker, sector, and scanner recurring cluster summaries using stored active captures and Replay Mode identities.
- Added recurrence appearance detail support with capture-time fields separated from later-derived outcome labels.
- Added Replay Mode handoff for individual historical appearances from recurring clusters.
- Added documentation-only future idea for Automated Market-Cycle Classification.

### Safety

- Historical recurrence clustering does not fetch current market data, mutate raw captures, recalculate historical scores, start provider integrations, start optimizer work, or write SQLite records.
- Quarantined captures remain excluded by default, and non-study-eligible captures remain filtered through the existing Study Engine controls.

### Tests

- Added tests for repeated ticker, sector, scanner clustering, chronological appearance ordering, recency/count sorting, average score calculation, score-breakdown status counts, outcome summaries, quarantine exclusion, Replay Mode handoff, and no current-data fetch.

### Added

- Added Outcome Maturity / Data Readiness Gate v1.
- Added `Readiness Gate` Study Engine tab with readiness metrics and gate statuses for Outcome Explorer, Opportunity Research, Opportunity Score design, and Weight optimization.
- Added completed next-day versus completed five-day outcome counting so pending five-day rows do not block next-day readiness measurement.
- Added readiness warnings for insufficient completed outcomes, high pending rate, diagnostic-only state, and trading-decision safety.

### Safety

- Outcome Maturity v1 is monitor-only and does not create Opportunity Score, optimize weights, alter `momentum_score_v1`, alter `scoring_profiles.json`, fetch current market data, mutate raw captures, start broker integration, or write SQLite records.
- Pending outcomes are counted as pending and are never treated as completed outcomes.
- Quarantined captures and non-study-eligible captures remain excluded by default through the existing active-capture and Study Engine filters.

### Tests

- Added tests for deterministic readiness counts, pending exclusion, gate thresholds, quarantined capture exclusion, non-study default exclusion, raw-capture immutability, and graceful readiness-date estimates.

## 2026-06-07

### Added

- Added Opportunity Research Framework v1.
- Added `Opportunity Research` Study Engine tab with summary, condition grouping, ranking, and combination-analysis views.
- Added condition analysis by score bucket, market regime, scanner preset, sector, industry, catalyst cluster, catalyst confidence, cluster purity, catalyst age bucket, review status, source reliability bucket, and duplicate-rate bucket.
- Added ranking tables for best performing, worst performing, most pending, highest max gain, and highest drawdown conditions.
- Added combination analysis for regime+catalyst, score+catalyst confidence, score+cluster purity, and review+catalyst conditions.

### Safety

- Opportunity Research v1 is research-only and does not create Opportunity Score, optimize weights, alter `momentum_score_v1`, alter `scoring_profiles.json`, fetch current market data, mutate raw captures, start broker integration, or write SQLite records.
- Pending outcomes are counted but excluded from completed-return math and are never treated as wins or losses.
- The UI displays `Insufficient completed outcomes for conclusions.` when completed outcomes are too low.

### Tests

- Added tests for deterministic groupings/rankings, pending exclusion, low-sample warnings, raw-capture immutability, quarantined capture exclusion, non-study default exclusion, and post-capture outcome separation.

### Added

- Added Outcome Explorer v1.
- Added `Outcome Explorer` Study Engine tab with summary, score bucket, regime, scanner, sector, review-status, catalyst-cluster, catalyst-age-bucket, cluster-purity, and candidate detail views.
- Added outcome filters for score bucket and industry alongside existing date, ticker, score, regime, scanner, sector, review, cluster, confidence, purity, timestamp status, age bucket, and study-eligibility filters.
- Added completed/pending outcome separation and post-capture labeling.

### Safety

- Outcome Explorer v1 is research-only and does not fetch current market data, mutate raw captures, recalculate historical scores, alter scoring profiles, start Opportunity Score, optimize weights, use broker APIs, or write SQLite records.
- Pending outcomes are counted but excluded from completed-return math and are not treated as wins or losses.
- Quarantined captures are excluded by requiring outcome rows to match active raw-capture identities.

### Tests

- Added tests for deterministic filters, deterministic summary metrics, pending outcome exclusion, quarantined/orphan outcome exclusion, non-study default exclusion, preopen inclusion, raw-capture immutability, and post-capture label separation.

### Added

- Added Headline Deduplication / Source Quality v1.
- Added deterministic headline fingerprinting and in-memory catalyst event grouping.
- Added `Headline Dedup` Study Engine tab with duplicate event summary, source reliability, cluster dedup impact, and ticker dedup impact views.
- Added source/provider reliability metrics for exact, unknown, future, and invalid timestamp rates, duplicate/syndicated rate, unique event count, and average headlines per event.
- Added source and minimum duplicate count filters.

### Safety

- Headline Dedup v1 is research-only and does not change Momentum Score, Opportunity Score, scoring profiles, optimizer behavior, broker behavior, SQLite storage, or raw captures.
- Future timestamp headlines are warned in source-quality reporting and are not treated as fresh.
- Dedup results are rebuilt in memory from stored data; no `headline-events.json` file is written in v1.

### Tests

- Added tests for deterministic fingerprinting, deterministic duplicate grouping, raw-capture immutability, quarantine exclusion, non-study default exclusion, preopen inclusion, future/unknown timestamp warnings, source reliability, and duplicate-count filtering.

### Added

- Added Catalyst Cluster Explorer v2 refinement.
- Added deterministic catalyst classification confidence, rule names, explicit/fallback labels, fallback reasons, cluster purity, and explicit match statistics.
- Added provider timestamp-quality summaries by provider, catalyst cluster, and ticker.
- Added Catalyst Explorer quality filters for minimum confidence, minimum purity, and minimum exact timestamp percentage.
- Added additional deterministic catalyst buckets for product/platform launch, capital markets/financing, legal/regulatory, leadership/strategic update, index/fund flow, and price-action/no-catalyst-detail.

### Safety

- Catalyst Cluster Explorer v2 remains research-only and does not change scores, scoring profiles, raw captures, optimizer behavior, broker behavior, or SQLite storage.
- Future timestamp headlines remain excluded from clustering and freshness-style analysis while still appearing in timestamp-quality warnings.

### Tests

- Added tests for deterministic classification confidence, purity, provider timestamp quality, fallback labeling, threshold filters, future timestamp exclusion, and raw-capture immutability coverage.

### Added

- Added Catalyst Date / Age Engine v1 in the Study Engine.
- Added `Catalyst Age` tab with audit totals, headline age bucket distribution, cluster-by-age summary, ticker-level summary, and headline-level details.
- Added timestamp statuses: `EXACT_TIMESTAMP`, `DATE_ONLY`, `ESTIMATED`, `UNKNOWN_TIMESTAMP`, `FUTURE_TIMESTAMP`, and `INVALID_TIMESTAMP`.
- Added age buckets: `<1h`, `1-4h`, `4-12h`, `12-24h`, `1-3d`, `3d+`, `unknown`, and `invalid_future`.
- Added age filters for ticker, catalyst cluster, timestamp status, and age bucket.

### Safety

- Catalyst age is measurement-only and does not alter `momentum_score_v1`, score profiles, existing scores, or scoring output.
- Future timestamps are warned and excluded from freshness-style analysis.
- Unknown timestamps remain unknown and are not treated as fresh.

### Tests

- Added tests for exact/date-only/estimated/unknown/future/invalid timestamps, deterministic age buckets, raw-capture immutability, quarantine exclusion, preopen inclusion rules, and age filters.

### Added

- Added legacy non-study capture cleanup command for quarantining unwanted non-market-day `morning`/`evening` captures while preserving valid `preopen` captures.
- Added derived CSV backup and prune behavior for legacy cleanup.

### Fixed

- Quarantined unwanted 2026-06-07 Sunday `morning` and `evening` captures with missing calendar metadata.
- Rebuilt/pruned derived analysis and outcome rows so ordinary Study Engine views no longer include those unwanted Sunday captures.

### Safety

- Legacy cleanup does not mutate raw captures in place.
- Legacy cleanup preserves valid active `preopen` captures.
- Legacy cleanup prunes existing outcome rows to active analysis identities without fetching current market data.

### Tests

- Added tests for Sunday legacy cleanup, preopen preservation, derived-row pruning, Study default exclusion, and Replay default hiding behavior.

### Added

- Added Catalyst Cluster Explorer v1 in the Study Engine.
- Added deterministic stored-headline catalyst grouping for earnings beat, guidance raise, analyst actions, AI infrastructure, AI partnership, contract/customer wins, FDA/biotech events, merger/acquisition, sector sympathy, macro-only, weak/vague catalyst, no clear catalyst, and unknown/uncategorized.
- Added catalyst cluster detail view with matching headlines, ticker, capture time, source, timestamp status, article age, freshness label, score, review status, outcome status, max gain/drawdown, and stored URLs.
- Added explicit timestamp handling: missing timestamps remain unknown and future timestamps are excluded with report warnings.
- Added `docs/FUTURE_IDEAS.md`.

### Safety

- Catalyst clusters read active raw captures plus derived stores only.
- Catalyst clusters do not fetch current market data, mutate raw captures, recalculate historical scores, start optimizer work, start broker integration, or perform SQLite migration.

### Tests

- Added tests for stored-data-only catalyst clustering, raw-capture immutability, quarantine exclusion, non-study filtering, missing timestamp behavior, missing outcome warnings, deterministic counts and representative headlines, and future timestamp exclusion.
