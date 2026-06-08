# Momentum Hunter Changelog

## 2026-06-07

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
