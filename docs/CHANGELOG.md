# Momentum Hunter Changelog

## 2026-06-07

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
