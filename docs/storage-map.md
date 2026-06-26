# Momentum Hunter Storage Map

Momentum Hunter separates immutable market observations from derived research artifacts. Raw captures are the source of truth; everything else should be rebuilt, edited, or replaced without changing those raw files.

## Raw captures

- Path: `MomentumHunterData/data/captures/YYYY-MM-DD/{morning|evening|preopen|manual}.json`
- Path: `MomentumHunterData/data/captures/YYYY-MM-DD/{morning|evening|preopen|manual}.md`
- Owner: capture engine
- Mutability: immutable after creation
- Purpose: point-in-time record of what Momentum Hunter knew at capture time
- Integrity: external SHA-256 records in `MomentumHunterData/data/integrity/capture_manifest.json`

Raw capture files must not store later review decisions, outcomes, score recalculations, study summaries, or AI annotations.

New raw captures also exclude user decision fields (`selected`, `reviewed`, `review_status`), user notes, and score-breakdown text such as score reasons. Those belong in separate review/derived stores.

Raw capture files must not be edited to add hashes or metadata after creation. Capture metadata lives outside the raw files.

## Market-calendar scheduling

- Shared policy module: `momentum_hunter/scheduling.py`
- Policy version: `market-calendar-v1`
- Target exchange: `XNYS`
- Calendar implementation: built-in NYSE/Nasdaq full-day market calendar with weekends and standard full-day exchange holidays; early closes and unscheduled special closures are not modeled yet.

Future automated captures follow this policy:

- `morning`: 7:00 AM CT on market-open days only
- `evening`: 7:00 PM CT after market-open days only, including Friday evening
- `preopen`: 7:00 PM CT on the calendar day immediately before the next market-open day when the prior calendar day was not market-open
- `manual`: allowed on any calendar day

The Windows scheduled tasks can still fire daily. The headless capture job exits cleanly with a logged skip reason when no capture is appropriate:

- `SKIP_NOT_MARKET_DAY`
- `SKIP_NOT_PREOPEN_GAP_REVIEW_DAY`
- `SKIP_DUPLICATE_CAPTURE`
- `SKIP_OUTSIDE_CAPTURE_WINDOW`

New raw captures store these calendar classification fields at creation time:

- `capture_session`
- `capture_calendar_status`
- `is_market_open_day`
- `is_study_eligible`
- `next_market_session_date`
- `scheduling_policy_version`

Existing historical raw captures are not rewritten. Derived readers classify legacy captures from `capture_time`, `capture_date`, and `session` where possible. If a legacy record cannot be classified confidently, it is treated as `UNKNOWN` and excluded from ordinary study statistics.

## Review decisions

- Path: `MomentumHunterData/data/review-decisions.json`
- Owner: candidate review workflow
- Mutability: append/update by candidate identity
- Stores: `review_status`, decision timestamp, optional decision note, delayed-review metadata, quarantine metadata
- Identity: `capture_id/date/session/provider/scanner/ticker`

Review decisions are user journal records. They reference raw captures but do not modify them.

Delayed-review metadata is stored here when a decision is made after the freshness threshold but while the capture is still valid for next-session review. Fields may include:

- `delayed_review`
- `review_delay_minutes`
- `review_context_state`

These are later user-action facts, not capture-time facts, and must not be written into raw captures.

## Entry plans

- Path: `MomentumHunterData/data/entry-plans.json`
- Owner: watchlist discipline workflow
- Mutability: append/update by candidate identity
- Stores: trigger, stop, thesis, invalidation, max loss, position size idea, planned hold time, plan notes, `plan_complete`, warnings, and update timestamp
- Identity: `capture_id/date/session/provider/scanner/ticker`

Entry plans are user planning records for candidates promoted to Watchlist. They reference raw captures but do not modify them. Current/manual scans and valid next-session review snapshots can create or edit plans; expired, historical, replay, research, and quarantined views are read-only.

Incomplete-plan warnings are derived from missing trigger, stop, invalidation, and max-loss fields. Watchlist reports include entry-plan fields as later user annotations.

## Derived outcomes

- Path: `MomentumHunterData/data/analysis-outcomes.csv`
- Owner: outcome updater
- Mutability: rebuildable
- Stores: future return labels, outcome windows, max gain/drawdown, expected outcome session dates, per-horizon outcome states, reason codes, and outcome calculation version

Outcomes are labels computed after capture time. They can use future bars for labeling, but they must not be written back into raw captures.

Outcome rows distinguish maturity/data-quality states for each horizon:

- `pending_not_mature`: the expected market session has not matured yet
- `complete`: the expected market session has a usable price bar and return label
- `provider_data_missing`: the expected market session has matured, but the provider did not return a usable bar
- `calculation_failed`: the row cannot be calculated because required capture inputs are missing or invalid
- `ineligible_capture`: the source capture is excluded from ordinary study outcome calculations
- `calendar_mapping_error`: the expected outcome session could not be mapped to a valid market-open day

The outcome updater uses `expected_next_day_session_date` and `expected_five_day_session_date` so holiday/weekend gaps are explicit. For example, a June 18, 2026 capture has an expected next-day outcome session of June 22, 2026 because June 19 was Juneteenth and the market was closed.

## Score breakdowns

- Path: `MomentumHunterData/data/score-breakdowns.json`
- Owner: scoring engine
- Mutability: rebuildable by engine version
- Stores arithmetic reconciliation, caps, floors, bonuses, penalties, component raw inputs, and GUI `Why [score]?` explanations

Score breakdowns reference raw capture identity and score engine version. They must not be written into raw captures. The identity key includes `score_engine_version`, so future engines can store side-by-side records for the same capture and ticker without rewriting history.

Current schema:

- `schema_version`
- `updated_at`
- `score_engine_version`
- `records`
- each record includes `capture_id`, `capture_date`, `capture_time`, `session`, `provider`, `scanner`, `ticker`, `score_engine_version`, `score_profile`, `score_regime`, `final_score`, `computed_final_score`, `compact_summary`, `components`, `bonuses`, `penalties`, `caps`, `floors`, `overrides`, and `reconciliation_status`

The GUI `Why [score]?` dialog shows:

- compact summary: grouped contribution lines such as Volume, Catalyst, Freshness, and Risk/Penalty
- detailed components: raw inputs, rule text, before/after contribution, category, and explanation
- reconciliation: subtotal, floor, cap, computed score, displayed score, and status

In `momentum_score_v1`, Freshness is stored as a zero-point context component. This makes article freshness visible for analysis without changing the current scoring engine output.

Historical records that cannot be fully reconstructed are marked `legacy` or `incomplete`; they are warnings, not clean current-engine proof. This is the foundation for future Replay Mode because the app can show what score explanation was available for a specific capture without changing the raw capture.

## Study reports

- Source paths: `MomentumHunterData/data/analysis-captures.csv`, `MomentumHunterData/data/analysis-outcomes.csv`
- UI location: Research Lab dialog
- Mutability: disposable/rebuildable
- Stores: aggregate summaries, score buckets, filtered historical summaries

Study results should be treated as derived views. They are useful research output, not source-of-truth capture data.

Persisted study reports, when added, should live under `MomentumHunterData/data/studies/` and should be safe to delete/rebuild.

The Research Lab area excludes rows where `is_study_eligible` is false by default. This keeps weekend, holiday, `preopen`, and manual observations out of ordinary market-session performance statistics unless the user explicitly enables non-trading-day/preopen inclusion.

## Reliability reports

- Paths:
  - `MomentumHunterData/data/reports/data-quality-latest.json`
  - `MomentumHunterData/data/reports/data-quality-latest.md`
  - `MomentumHunterData/data/reports/evidence-autopilot-latest.json`
  - `MomentumHunterData/data/reports/evidence-autopilot-latest.md`
  - `MomentumHunterData/data/reports/system-readiness-latest.json`
  - `MomentumHunterData/data/reports/system-readiness-latest.md`
- Owners:
  - `momentum_hunter/data_quality.py`
  - `momentum_hunter/evidence_autopilot_reliability.py`
  - `momentum_hunter/system_readiness.py`
- Mutability: disposable/rebuildable latest reports
- Stores: provider/market-tape quality, scanner field reliability, evidence-autopilot status, outcome evidence health, and section-level system readiness

Reliability reports are derived operator trust artifacts. They read existing raw captures, derived stores, monitor status, evidence status, and watchlist state, then write latest report files. They must not mutate raw captures, rewrite score values, change readiness rules, alter alert thresholds, or modify trade-planning rules.

## SQLite foundation

- Path: `MomentumHunterData/data/momentum-hunter.sqlite3`
- Owner: `momentum_hunter/sqlite_store.py`, `momentum_hunter/sqlite_migration.py`
- Mutability: additive derived mirror only
- Current additive slices: `provider_quality_checks` imported from `MomentumHunterData/data/reports/data-quality-latest.json`; `opportunity_alerts` and `alert_outcomes` imported from `MomentumHunterData/data/opportunity-alerts.json`; `minute_bars` imported from `MomentumHunterData/data/opportunity-minute-bars.json`; `evidence_runs` and `evidence_metrics` imported from structured evidence/status JSON reports; `system_status_events` imported from structured status/readiness JSON reports; `captures` and `capture_candidates` imported from `MomentumHunterData/data/analysis-captures.csv`; `candidate_reviews`, `watchlist_items`, and `entry_plans` imported as additive mirrors from file-authoritative user-state stores

SQLite is not the runtime source of truth yet. Existing raw captures, CSVs, JSON state stores, Markdown reports, and status files remain in place. The SQLite foundation currently provides schema initialization, idempotent migration tracking, a low-risk import path for provider/data-quality report rows, an additive evidence mirror for opportunity alerts and embedded alert outcomes, an additive minute-bar mirror for alert-validation market data, an additive evidence-run/metric mirror for structured reliability and evidence reports, an additive system-status mirror for readiness/provider/monitor status events, an additive capture/candidate index over the derived analysis CSV, and an additive user-state mirror guarded by backup/restore validation and dry-run diff reports.

Evidence slice reports are written to:

```text
MomentumHunterData/data/reports/sqlite-import-all-safe-latest.json
MomentumHunterData/data/reports/sqlite-import-all-safe-latest.md
MomentumHunterData/data/reports/sqlite-evidence-import-latest.json
MomentumHunterData/data/reports/sqlite-evidence-import-latest.md
MomentumHunterData/data/reports/sqlite-minute-bars-import-latest.json
MomentumHunterData/data/reports/sqlite-minute-bars-import-latest.md
MomentumHunterData/data/reports/sqlite-evidence-runs-import-latest.json
MomentumHunterData/data/reports/sqlite-evidence-runs-import-latest.md
MomentumHunterData/data/reports/sqlite-system-status-import-latest.json
MomentumHunterData/data/reports/sqlite-system-status-import-latest.md
MomentumHunterData/data/reports/sqlite-capture-index-import-latest.json
MomentumHunterData/data/reports/sqlite-capture-index-import-latest.md
MomentumHunterData/data/reports/sqlite-user-state-import-latest.json
MomentumHunterData/data/reports/sqlite-user-state-import-latest.md
MomentumHunterData/data/reports/sqlite-user-state-diff-latest.json
MomentumHunterData/data/reports/sqlite-user-state-diff-latest.md
MomentumHunterData/data/reports/sqlite-candidate-story-read-model-latest.json
MomentumHunterData/data/reports/sqlite-candidate-story-read-model-latest.md
MomentumHunterData/data/reports/sqlite-evidence-read-model-latest.json
MomentumHunterData/data/reports/sqlite-evidence-read-model-latest.md
MomentumHunterData/data/reports/sqlite-watchlist-read-model-latest.json
MomentumHunterData/data/reports/sqlite-watchlist-read-model-latest.md
MomentumHunterData/data/reports/sqlite-system-readiness-read-model-latest.json
MomentumHunterData/data/reports/sqlite-system-readiness-read-model-latest.md
MomentumHunterData/data/reports/sqlite-read-model-comparison-latest.json
MomentumHunterData/data/reports/sqlite-read-model-comparison-latest.md
MomentumHunterData/data/reports/sqlite-shadow-compare-latest.json
MomentumHunterData/data/reports/sqlite-shadow-compare-latest.md
MomentumHunterData/data/reports/sqlite-validation-latest.json
MomentumHunterData/data/reports/sqlite-validation-latest.md
```

The evidence slice preserves pending, completed, and terminal unscorable alert outcomes exactly as they appear in `opportunity-alerts.json`. The minute-bars slice preserves OHLCV rows from `opportunity-minute-bars.json` keyed by symbol, timestamp, and source. The evidence-runs slice imports structured evidence JSON only: `evidence-autopilot-status.json`, `alert-outcome-update-status.json`, `evidence-autopilot-latest.json`, `evidence-health-report-*.json`, `reliability-report-*.json`, and `alert-performance-report-*.json`. The system-status slice imports structured status JSON only: `active-monitor-status.json`, `evidence-autopilot-status.json`, `alert-outcome-update-status.json`, `system-readiness-latest.json`, `data-quality-latest.json`, and `market-tape-health-*.json`. The capture-index slice imports the derived analysis CSV and records raw capture JSON source hashes where the active raw file exists. The user-state slice mirrors `review-decisions.json`, `watchlist-*.json`, and `entry-plans.json` into SQLite after backup/restore validation. JSON/CSV/report files remain authoritative; SQLite is a read-only analytics mirror.

User-state safety reports are written to:

```text
MomentumHunterData/backups/user-state/YYYYMMDDHHMMSS/manifest.json
MomentumHunterData/data/reports/user-state-backup-latest.json
MomentumHunterData/data/reports/user-state-backup-latest.md
MomentumHunterData/data/reports/user-state-restore-validation-latest.json
MomentumHunterData/data/reports/user-state-restore-validation-latest.md
```

The user-state dry-run diff is generated with:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_validation --slice user-state
```

The diff compares file-authoritative review, watchlist, and entry-plan records against the SQLite mirror. It reports missing rows, extra rows, changed values, malformed records, conflicts, stale imports, warnings, and a recommended next action. It never repairs or overwrites live files.

Read-only query helpers live in `momentum_hunter/sqlite_queries.py`. They summarize table counts, alert evidence state, alerts by symbol, outcomes by alert ID, minute bars by symbol/time range, evidence runs by date range, latest provider quality checks, latest system status events, candidate capture trails, first/latest captures, peak-score captures, mirrored review decisions, mirrored watchlist items, mirrored entry plans, latest user-state import summaries, and user-state diff conflicts from SQLite without mutating source files or redirecting runtime workflows.

Read-only report helpers live in `momentum_hunter/sqlite_reports.py`. They generate SQLite-powered latest JSON/Markdown reports for Candidate Story, Evidence, Watchlist/Plans, System Readiness, and file-vs-SQLite comparison. These reports validate SQLite when practical, label missing or unavailable comparisons honestly, and never mutate source JSON/CSV/Markdown files, raw captures, or user-authored state.

Read-only source-mode helpers live in `momentum_hunter/read_models.py`. They expose `file`, `sqlite`, and `shadow` report-summary modes through `MOMENTUM_HUNTER_READ_MODEL_SOURCE`, defaulting to `file`. Shadow mode compares file-authoritative summaries with SQLite read-model summaries and writes `sqlite-shadow-compare-latest.*` through the SQLite reports CLI. This is a diagnostic bridge only; it does not redirect runtime UI workflows.

SQLite validation lives in `momentum_hunter/sqlite_validation.py`. It compares mirrored row counts against the current authoritative source files and writes `sqlite-validation-latest.json` / `.md` reports. Validation includes per-symbol counts, earliest/latest timestamps, alert/outcome completed-pending-unscorable counts, minute-bar counts, capture counts, source file paths and hashes, import timestamps, schema version, missing slices, and warnings. Validation is read-only and does not modify source files or SQLite rows.

Do not make raw captures, review decisions, watchlist state, or entry plans SQLite-authoritative until backup, conflict handling, hash validation, recovery behavior, UI confirmation, rollback, and cutover strategy are implemented and tested. The design-only user-state cutover plan is documented in `docs/storage/sqlite-user-state-cutover-plan-v1.md`; it does not activate cutover behavior.

## Historical Cluster Display

- UI location: Research Lab dialog, `Catalyst - Historical Setups` tab
- Data layer: `momentum_hunter/historical_clusters.py`
- Source inputs: active immutable raw captures, `score-breakdowns.json`, `review-decisions.json`, and `analysis-outcomes.csv`
- Mutability: research-only view; cluster generation reads stored data and does not mutate raw captures or derived stores

Historical clusters are labeled `HISTORICAL CLUSTERS — RESEARCH ONLY`.

The v1 cluster engine is deterministic. It groups candidates with keyword and context rules only; it does not call AI services, fetch current market data, or recalculate historical scores. Score-component summaries come from stored score-breakdown records tied to the historical identity.

The `Recurring Clusters` view groups repeated historical appearances by ticker, sector, and scanner preset. It reuses Replay Mode identity rows and therefore keeps capture-time facts, stored score explanations, later review decisions, and later outcome labels separate. Selecting an appearance can open point-in-time Replay Mode without fetching current market data or recalculating historical scores.

Default cluster views exclude quarantined captures because quarantined files live outside active `captures/`, and they exclude rows where `is_study_eligible` is false. Non-study-eligible captures can be included explicitly for weekend, holiday, preopen, or manual-capture research.

Cluster metrics use only available outcome labels. Missing outcome data and small sample sizes are warnings, not silently filled values. Outcome fields are later-derived labels, not information known at the original capture time.

## Catalyst Cluster Explorer

- UI location: Research Lab dialog, `Catalyst - Clusters` tab
- Data layer: `momentum_hunter/catalyst_clusters.py`
- Source inputs: active immutable raw captures, stored news/catalyst headlines in captures, `score-breakdowns.json`, `review-decisions.json`, and `analysis-outcomes.csv`
- Mutability: research-only view; catalyst clustering reads stored data and does not mutate raw captures or derived stores

Catalyst clusters are labeled `CATALYST CLUSTERS — RESEARCH ONLY`.

The v2 catalyst engine is deterministic. It uses rule-based headline classification only and does not call AI services, fetch current market data, recalculate historical scores, start optimizer work, write SQLite records, or touch broker APIs.

The v2 report adds derived in-memory research metrics:

- classification confidence: deterministic `HIGH`, `MEDIUM`, or `LOW` plus a numeric rule score
- explicit rule used: the matching rule name for explicitly classified headlines
- fallback reason: why the engine fell back to Sector Sympathy, No Clear Catalyst, or Unknown/Uncategorized
- purity: percent of cluster headlines supported by explicit rules instead of fallback classification
- explicit/fallback match counts and explicit match percentage
- provider timestamp quality: exact, unknown, future, and invalid timestamp rates by provider, catalyst cluster, and ticker

These metrics are generated at view/report time from stored data and are not persisted into raw captures.

Headline timestamps are interpreted only relative to the capture time:

- known timestamp: article age is calculated at capture time
- missing timestamp: freshness is `UNKNOWN_TIMESTAMP`
- future timestamp: headline is excluded from catalyst clustering and counted in report warnings

Future timestamp rows remain visible in timestamp-quality summaries, but they are excluded from the cluster rows used for catalyst research and freshness-style analysis.

Outcome values in the catalyst detail view are post-capture labels from `analysis-outcomes.csv`. They are displayed for research context only and must not be treated as information known during the capture.

Default catalyst views exclude quarantined captures because quarantined files live outside active `captures/`, and they exclude rows where `is_study_eligible` is false. Non-study-eligible captures can be included explicitly for weekend, holiday, preopen, or manual-capture research.

## Headline Deduplication / Source Quality

- UI location: Research Lab dialog, `Catalyst - Headline Dedup` tab
- Data layer: `momentum_hunter/headline_events.py`
- Source inputs: active immutable raw captures, stored news/catalyst headlines in captures, catalyst cluster classifications, catalyst age/timestamp metrics, and `analysis-outcomes.csv` for display context only
- Mutability: research-only view; dedup generation reads stored data and does not mutate raw captures or derived stores

Headline Dedup is labeled `HEADLINE DEDUP / SOURCE QUALITY — RESEARCH ONLY`.

Headline Dedup v1 creates in-memory derived catalyst event records at report time. It does not write `headline-events.json` yet. If persistence is added later, the file must live outside immutable raw captures and be treated as rebuildable derived data.

Event grouping uses deterministic headline fingerprints:

- lowercase
- strip punctuation
- remove source boilerplate where practical
- remove ticker prefixes where practical
- collapse whitespace
- remove common filler words

Each in-memory event includes event ID, representative headline, tickers, sources, first/latest seen capture times, earliest known publication timestamp, timestamp status summary, duplicate headline count, unique source count, catalyst cluster, confidence, notes, and warnings.

Source reliability is derived by provider/source and reports exact, unknown, future, and invalid timestamp rates, duplicate/syndicated rate, unique event count, and average headlines per event. These reliability metrics are context only and do not affect Momentum Score, Opportunity Score, score profiles, or recommendations.

Default Headline Dedup views exclude quarantined captures because quarantined files live outside active `captures/`, and they exclude rows where `is_study_eligible` is false. Preopen, weekend, holiday, and manual captures can be included explicitly.

## Outcome Explorer

- UI location: Research Lab dialog, `Readiness - Outcome Explorer` tab
- Data layer: `momentum_hunter/outcome_explorer.py`
- Source inputs: active immutable raw captures, `analysis-captures.csv`, `analysis-outcomes.csv`, `score-breakdowns.json`, `review-decisions.json`, catalyst cluster context, catalyst age context, and headline dedup/source quality context
- Mutability: research-only view; outcome exploration reads stored data and does not mutate raw captures or derived stores

Outcome Explorer is labeled `OUTCOME EXPLORER — POST-CAPTURE DATA`.

Outcome rows are post-capture labels from `analysis-outcomes.csv`. They are separated from capture-time facts and must not be treated as information known during the original scan.

Pending outcomes are counted as pending but excluded from completed-return math. They are not treated as wins or losses. Summary and comparison metrics use completed rows only for completed-return averages, medians, win rate, best winner, and worst loser.

Outcome Explorer excludes quarantined captures by requiring each outcome row to match an active raw-capture identity. It excludes non-study-eligible captures by default unless the user explicitly enables non-trading-day/preopen inclusion.

No new persisted outcome-explorer store is created in v1. The report is rebuilt from immutable raw captures and derived stores at view/report time.

## Opportunity Research

- UI location: Research Lab dialog, `Readiness - Opportunity Research` tab
- Data layer: `momentum_hunter/opportunity_research.py`
- Source inputs: active immutable raw captures, `analysis-captures.csv`, `analysis-outcomes.csv`, `score-breakdowns.json`, `review-decisions.json`, catalyst cluster context, catalyst age context, and headline dedup/source reliability context
- Mutability: research-only view; opportunity research reads stored data and does not mutate raw captures or derived stores

Opportunity Research is labeled `OPPORTUNITY RESEARCH — RESEARCH ONLY`.

Opportunity Research v1 creates no new persisted store. It is a report-time measurement framework over stored data and post-capture outcome labels.

The framework groups outcomes by score bucket, market regime, scanner preset, sector, industry, catalyst cluster, catalyst confidence, cluster purity, catalyst age bucket, review status, source reliability bucket, duplicate-rate bucket, and selected combinations.

Outcome values are post-capture labels from `analysis-outcomes.csv`, not capture-time facts. Pending outcomes are counted as pending but excluded from completed-return math and are never treated as wins or losses.

Opportunity Research excludes quarantined captures by using active raw-capture identities inherited from Outcome Explorer. It excludes non-study-eligible captures by default unless the user explicitly enables non-trading-day/preopen inclusion.

Opportunity Research v1 does not create Opportunity Score, optimize weights, alter scoring profiles, fetch current market data, mutate raw captures, start broker integration, or start SQLite migration.

## Opportunity Monitor Targets

- Data layer: `momentum_hunter/monitor_targets.py`
- User-defined symbol store: `MomentumHunterData/data/opportunity-monitor-symbols.json`
- Report output: `MomentumHunterData/data/reports/opportunity-monitor-targets-*.csv`, `.json`, and `.md`
- Source inputs: `review-decisions.json`, `entry-plans.json`, trade-planning report JSON files under `MomentumHunterData/data/reports/`
- Mutability: derived operator preference/report store; may be updated by operator actions or target-resolver runs; must not mutate raw captures

Opportunity Monitor Targets v1 resolves the active watch universe from watchlist decisions, interested decisions, saved entry plans, execution-ready trade-planning rows, and user-defined symbols. It deduplicates by symbol and records source reasons such as `watchlist`, `interested`, `entry_plan`, `execution_ready`, and `user_defined`.

The main dashboard can add and remove user-defined monitor symbols. Those edits update `opportunity-monitor-symbols.json` only; they do not modify raw captures, review decisions, entry plans, score breakdowns, or historical reports.

This layer does not fetch market data, create alerts, place orders, recalculate scores, or modify historical raw captures. It exists so a future continuous polling loop has a deterministic list of symbols to monitor.

## Active Monitor Cycles

- Data layer: `momentum_hunter/active_monitor.py`
- Status store: `MomentumHunterData/data/active-monitor-status.json`
- Background runner store: `MomentumHunterData/data/active-monitor-runner.json`
- Report output: `MomentumHunterData/data/reports/active-monitor-cycle-*.csv`, `.json`, and `.md`
- Refreshed target tape output: `MomentumHunterData/data/reports/active-monitor-refresh-*.json`
- Source inputs: monitor target reports, trade-planning report JSON files, optional raw capture JSON when explicitly refreshing a trade-planning report
- Derived outputs: monitor target reports, opportunity alert reports, active monitor cycle summaries
- Mutability: derived monitoring artifacts only; must not mutate raw captures

Active Monitor Cycle v1 ties together target resolution and alert detection. It resolves the active monitoring universe, filters opportunity alert detection to that universe, records missing target symbols that are not present in the current trade-planning report, and writes a cycle summary showing target counts, matched trade rows, new alerts, active alerts, tracked alerts, and state transitions.

The cycle runner can optionally refresh a trade-planning report from a raw capture using existing trade-planning logic. That refresh may fetch quote data when explicitly requested, but any fetched values are written only to derived trade-planning reports and monitor-cycle artifacts.

When a monitor target is missing from the source trade-planning report, the cycle runner writes a derived `active-monitor-coverage-*.json` report containing `MONITORING_ONLY` coverage rows. Coverage rows are not scanner candidates, do not contain capture-time raw facts, and must remain labeled with `COVERAGE_ROW_NOT_FROM_SCANNER` / `MISSING_SCANNER_CONTEXT` warnings. If quote tape is supplied or explicitly fetched, coverage rows may include price, bid/ask, spread, volume, premarket data, and RVOL policy fields for alert monitoring.

When `--refresh-target-market-data` or the dashboard `Refresh target quotes` option is enabled, the cycle runner writes a derived `active-monitor-refresh-*.json` report that refreshes market tape for active monitor targets already present in the source trade-planning report. The report metadata records the source report, refreshed symbols, readiness recalculation count, readiness change count, and the warning that readiness was recalculated only in the derived monitor artifact. This gives alert detection fresher price/RVOL/readiness inputs without rewriting raw captures or silently changing the source trade-planning report.

Loop runs update `active-monitor-status.json` before each cycle, after successful cycles, and after failures. The status file records `RUNNING`, `IDLE`, or `FAILED`, completed cycle count, interval, last cycle time, next cycle time, last report path, warnings, and last error. This file is derived runtime state and may be overwritten by monitor runs.

The GUI can launch the loop as a background Python process via `momentum_hunter/active_monitor_runner.py`. Runner state is stored in `active-monitor-runner.json` with PID, command, interval, quote-fetch setting, state, and last error. This store is process-control metadata only and may be overwritten by Start/Stop Monitor actions.

The GUI reads the latest `active-monitor-cycle-*.json` file for the main-dashboard Active Monitor panel. This is a read-only display of derived monitoring state.

## Opportunity Alerts

- UI location: main dashboard, `Execution Ready` group with `Active Alerts` and `State Transitions`
- Data layer: `momentum_hunter/opportunity_alerts.py`
- Alert store: `MomentumHunterData/data/opportunity-alerts.json`
- Monitor state: `MomentumHunterData/data/opportunity-monitor-state.json`
- Observation history: `MomentumHunterData/data/opportunity-price-observations.json`
- Minute-bar validation store: `MomentumHunterData/data/opportunity-minute-bars.json`
- Minute-bar updater status: `MomentumHunterData/data/alert-outcome-update-status.json`
- Report output: `MomentumHunterData/data/reports/opportunity-alerts-*.csv`, `.json`, and `.md`
- Source inputs: trade-planning report JSON files under `MomentumHunterData/data/reports/`
- Mutability: derived validation store; may be appended/updated by alert-engine runs; must not mutate raw captures

Opportunity Alert Engine v1 compares the latest trade-planning report to the prior monitor state and records timestamped alerts for state transitions, RVOL threshold crosses, breakout/reclaim events, and short-window price expansion. Each alert stores the exact market/planning context known at alert time, including bid, ask, spread, volume, RVOL, suggested entry, stop, targets, catalyst text, market regime, event-mode flag, and source report.

Catalyst/news summary changes create `BREAKING_NEWS_CATALYST` alerts when the current monitored catalyst text changes from the previous monitor snapshot. These alerts are deterministic string-change alerts from stored monitor data; they do not call an AI service or fetch news directly.

Each alert-engine run also appends timestamped price observations derived from the trade-planning report. Pending alerts are evaluated from observation history using fixed-time returns, 15/30/60-minute MFE and MAE, target/stop hits, stop-before-target ordering, and a deterministic classification of `SUCCESSFUL`, `FAILED`, `NOISE`, `LATE`, or `PENDING`. Permanently unscorable alerts receive terminal data-quality classifications such as `UNSCORABLE_MISSING_ENTRY_PRICE` or `UNSCORABLE_INVALID_TIMESTAMP` with `outcome.status = UNSCORABLE_OUTCOME`. Outcome updates modify only the derived alert store; they must not rewrite original alert facts or raw captures.

`momentum_hunter/alert_outcome_updater.py` can update pending alert outcomes from one-minute bars. It persists bars in `opportunity-minute-bars.json` and updates `opportunity-alerts.json` with 5/15/30/60-minute returns, MFE/MAE from high/low bars, target/stop hits, stop-before-target ordering, and deterministic classification. This is derived validation data only; it must not mutate raw captures, scanner records, score breakdowns, or source trade-planning artifacts.

The dashboard `Update Alert Outcomes` control writes the latest updater summary to `alert-outcome-update-status.json`, including alert counts, completed/pending/unscorable counts, symbols processed, bar count, and warnings. This status file is derived operator metadata and may be overwritten by future updater runs.

Learning summaries are generated from derived alert records by alert type, symbol, readiness state, and market regime. Summaries include win rate, average returns, average MFE/MAE, target hit rate, and stop hit rate. These summaries are research evidence only; they must not be treated as trade recommendations.

### Alert Performance Analytics

- Data layer: `momentum_hunter/alert_performance.py`
- Source input: `MomentumHunterData/data/opportunity-alerts.json`
- Report output: `MomentumHunterData/data/reports/alert-performance-report-*.json` and `.md`
- UI location: main dashboard, `Execution Ready` group, `Alert Performance` section
- Mutability: derived read-only analytics; report generation does not mutate raw captures, trade plans, readiness rules, monitor state, or alert-generation logic

Alert Performance Analytics v1 groups completed, pending, and unscorable alert outcomes by alert type, symbol, and readiness state. It reports alert count, completed/pending/unscorable counts, win rate, 5/15/30/60-minute returns, average MFE/MAE, and `SUCCESSFUL` / `FAILED` / `NOISE` / `LATE` rates. Pending and unscorable alerts are excluded from completed-return math. Small samples are labeled diagnostic only.

### Evidence Health And Reliability

- Data layer: `momentum_hunter/evidence_health.py`
- Autopilot layer: `momentum_hunter/evidence_autopilot.py`
- Scheduled runner: `tools/run_evidence_report_job.ps1`
- Scheduled task installer: `tools/install_evidence_report_tasks.ps1`
- Source inputs: `opportunity-alerts.json`, `opportunity-minute-bars.json`, `alert-outcome-update-status.json`, `active-monitor-status.json`, and `active-monitor-cycle-*.json`
- Autopilot status store: `MomentumHunterData/data/evidence-autopilot-status.json`
- Report output: `MomentumHunterData/data/reports/evidence-health-report-*.json`, `.md`, `reliability-report-*.json`, and `.md`
- Daily brief output: `MomentumHunterData/data/reports/daily-evidence-brief-YYYY-MM-DD.md`
- UI location: main dashboard, `Execution Ready` group, `Evidence Health` section
- Mutability: derived reporting only; must not mutate raw captures, alert facts, minute bars, trade plans, scoring, readiness logic, ranking, or monitoring rules

Evidence Health v1 measures whether the alert evidence pipeline is complete. It tracks alerts generated, alerts captured, alerts classified, completed outcomes, pending alerts, terminal unscorable alerts, stale pending alerts, missing minute bars, missing outcome data, incomplete outcome calculations, missing readiness states, and missing news snapshots. Terminal unscorable alerts are preserved for auditability but excluded from pending counts, completed outcome counts, and evidence thresholds.

Reliability reporting measures monitor-cycle count, successful cycles, failed cycles when the active-monitor status records failure, warning cycles, cycle reliability, alert completion rate, outcome job status, and missing-data incident count. The optional Windows scheduled tasks generate daily Evidence Health and weekly Reliability reports; installing those tasks does not change capture, alert, readiness, scoring, ranking, or trade-planning behavior.

Evidence thresholds are enforced as reporting gates only:

| Completed Alerts | Allowed Action |
| ---: | --- |
| `<25` | Collect evidence only |
| `25-49` | Identify patterns |
| `50-99` | Recommend investigations |
| `100+` | Recommend strategy modifications |

These gates do not change signal generation. They prevent premature optimization language in reports and dashboard summaries.

Evidence Autopilot v1 is orchestration only. It runs the existing monitor cycle, existing alert outcome updater, existing Evidence Health report, and daily evidence brief writer. It stores run status separately in `evidence-autopilot-status.json`. It must not duplicate or alter alert-generation rules, score calculations, readiness classification, ranking, or trade-planning logic.

## Catalyst Date / Age Engine

- UI location: Research Lab dialog, `Catalyst - Age` tab
- Data layer: `momentum_hunter/catalyst_age.py`
- Source inputs: active immutable raw captures, stored news/catalyst headlines in captures, `review-decisions.json`, and `analysis-outcomes.csv`
- Mutability: research-only view; age calculation reads stored data and does not mutate raw captures or derived stores

Catalyst Age is labeled `CATALYST AGE / FRESHNESS — RESEARCH ONLY`.

The v1 age engine is measurement only. It does not fetch current market data, recalculate historical scores, write score changes, start Opportunity Score, start optimizer work, write SQLite records, or touch broker APIs.

Timestamp status values:

- `EXACT_TIMESTAMP`: full timestamp parsed from stored headline data
- `DATE_ONLY`: date parsed without article time; confidence is partial
- `ESTIMATED`: stored headline marked as estimated; confidence is estimated
- `UNKNOWN_TIMESTAMP`: no usable stored timestamp
- `FUTURE_TIMESTAMP`: stored timestamp is later than capture time; excluded from freshness-style analysis
- `INVALID_TIMESTAMP`: stored timestamp could not be parsed

Age buckets are `<1h`, `1-4h`, `4-12h`, `12-24h`, `1-3d`, `3d+`, `unknown`, and `invalid_future`.

Unknown and invalid timestamps are counted separately and never receive HOT/FRESH treatment. Outcome values in the age tab are post-capture labels shown for research context only.

## Candidate Story, Timeline, and Replay Mode

- UI entry: select a candidate and click `Timeline / Replay`
- Data layer: `momentum_hunter/replay.py`
- Source inputs: active raw captures, `score-breakdowns.json`, `review-decisions.json`, and `analysis-outcomes.csv`
- Mutability: read-only view model; no story/timeline/replay operation modifies raw captures or derived stores

Candidate Story is the default operator presentation for Timeline / Replay. It builds a graph-first view from existing `TimelineRow` data: first/latest capture, first/latest price, move since first seen, score movement, peak score, trusted capture count, plain-language status, a capture-trail price/score chart, and simplified capture rows.

Candidate Story does not create a new persisted data store. It is derived display state built from raw captures and existing derived stores. Missing prices, relative volume, minute bars, 5D context, review annotations, and outcome labels are shown as missing instead of invented.

The dense metadata table remains available as `Advanced Capture Audit`.

Timeline rows expose capture time, session, provider, scanner preset, score, score profile/version, market regime, review status, outcome status, score-breakdown status, and trust classification. The replay detail dialog is labeled `POINT-IN-TIME REPLAY — READ ONLY`.

Timeline and Replay views also expose a visible audit identity strip for the selected row. It includes selected capture timestamp, capture ID, selected symbol, candidate row ID, candidate fingerprint, outcome record ID, source capture file/path, and the last refresh time for the row view. These identity fields are derived display metadata and do not modify raw captures.

Replay Mode classifies fields by source:

- `raw capture`: point-in-time market/candidate facts known at capture time
- `derived score explanation`: stored `Why [score]?` record tied to capture identity, ticker, and score engine version
- `later review decision`: user decision and notes recorded after capture
- `later outcome label`: post-capture performance labels from outcomes CSV

Outcome values are always labeled as calculated after capture. Replay views must not present outcomes as information known at the replayed moment.

Replay Mode labels `preopen` captures as `Pre-Open Gap Review`. Ordinary weekend, holiday, or manual captures are hidden from timelines by default; `Show non-trading-day captures` reveals them with a warning. Friday evening captures remain ordinary market-day evening captures.

Quarantined captures are excluded from timelines by default. If `Show quarantined captures` is enabled, replay rows are marked `Quarantined - Not Trusted for Study Use` and remain read-only. Quarantined captures are not re-added to active analysis CSVs or study results.

Timeline/replay warnings include duplicate replay identities, missing score breakdowns, legacy/incomplete score breakdowns, missing outcome labels, and quarantined source references. Missing optional derived data is shown honestly instead of invented.

## Future optimizer results

- Current status: not implemented
- Future path: `MomentumHunterData/data/optimizer/`
- Mutability: disposable/rebuildable
- Stores: candidate scoring weight experiments and aggregate recommendation output

Optimizer output is always derived research. It must never mutate raw captures.

## Provider raw snapshots

- Current status: not persisted as a dedicated provider snapshot store yet
- Future path: `MomentumHunterData/data/provider-snapshots/{provider}/YYYY-MM-DD/...`
- Mutability: immutable after creation
- Purpose: preserve provider responses separately from normalized candidate captures

When provider snapshots are added, they should be hashed and tracked the same way as raw captures.

## Integrity index

- Path: `MomentumHunterData/data/integrity/capture_manifest.json`
- Owner: capture storage and integrity audit
- Mutability: updated only when a raw capture file is first created
- Purpose: detect raw capture JSON/MD file changes after creation

The manifest is not the source of truth for market data. It is an audit index for raw file integrity.

Each manifest record stores:

- `created_at`
- `capture_time`
- `capture_date`
- `session`
- `provider`
- `scanner`
- `capture_version`
- `hash_algorithm = sha256`
- `source_hash`

## Files That May Be Updated

- `review-decisions.json`: user decisions and notes
- `analysis-captures.csv`: normalized derived analysis rows
- `analysis-outcomes.csv`: future outcome labels
- `score-breakdowns.json`: rebuildable score explanation records
- `opportunity-alerts.json`: derived alert validation records
- `opportunity-monitor-state.json`: latest per-symbol alert-engine comparison state
- `opportunity-price-observations.json`: derived monitor observation history used to update alert outcomes
- `watchlist-*.json` and `watchlist-report-*.md`: user-facing derived watchlist artifacts
- `integrity/capture_manifest.json`: external raw capture integrity metadata
- `integrity/raw_capture_integrity_audit.*`: latest audit output
- `backups/derived-rebuild/YYYYMMDD-HHMMSS/`: backed-up derived CSVs before rebuilds
- `quarantine/raw-captures/YYYYMMDD-HHMMSS/`: raw captures removed from active study use but retained for recovery/audit

## Integrity Validation

Run:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.integrity_audit
```

The audit:

- verifies manifest raw captures still exist
- verifies SHA-256 hashes
- detects modified raw captures
- detects missing raw captures
- warns about pre-manifest/untracked raw captures
- detects derived CSV/review records that reference missing raw captures or missing tickers
- writes CSV and Markdown reports under `MomentumHunterData/data/integrity/`

Overall statuses:

- `PASS`: all tracked raw captures are present and hash-clean, with no orphaned derived records
- `WARN`: no integrity failures, but legacy raw captures are untracked
- `FAIL`: at least one raw capture is modified/missing, or a derived record points to a missing source capture/ticker

## Recovery From Audit Failures

- `MODIFIED`: do not trade from that snapshot until the original raw file is restored from backup, Git history, OneDrive history, or another machine.
- `MISSING`: restore the missing raw JSON/MD file from backup, or quarantine/delete derived rows that reference it.
- `ORPHANED_DERIVED_RECORD`: rebuild derived CSV/outcome/review data from available raw captures, or remove the derived row if the raw source cannot be recovered.
- `UNTRACKED`: legacy pre-manifest captures can still be viewed, but they cannot be proven immutable from creation time. Future captures will be tracked automatically.
- `QUARANTINED`: a raw capture was deliberately removed from active source-of-truth use and retained outside `data/captures`.

Modified raw captures must never be silently re-blessed. The recovery order is:

1. Restore the original raw JSON/MD from backup, Git history, OneDrive history, or another trusted machine.
2. If the original cannot be restored, quarantine the current modified files and rebuild derived data.
3. Only re-baseline with an explicit signed recovery note that says who approved it, when, and why. Do not update `source_hash` just to make the audit pass.

## Rebuilding Derived Data

If `analysis-captures.csv` or `analysis-outcomes.csv` drifts from raw captures, rebuild them from source-of-truth captures:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.rebuild_derived_data
```

The rebuild command:

- writes a before-rebuild audit report
- backs up existing derived CSVs under `MomentumHunterData/data/backups/derived-rebuild/`
- registers legacy untracked raw captures in the external manifest
- rebuilds `analysis-captures.csv` only from raw capture JSON files
- rebuilds `analysis-outcomes.csv` from the rebuilt analysis CSV
- verifies raw capture hashes did not change during the rebuild
- writes an after-rebuild audit report

The backup directory is the quarantine area for old orphaned derived rows. Do not copy old rows back into live analysis files unless they can be traced to a raw capture.

## Rebuilding Score Breakdowns

If `score-breakdowns.json` is missing or stale, rebuild it from active raw captures:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.rebuild_score_breakdowns
```

The rebuild command:

- reads only active raw capture JSON files under `data/captures`
- excludes quarantined captures because they live outside `data/captures`
- writes `MomentumHunterData/data/score-breakdowns.json` atomically
- backs up any previous score-breakdown store under `MomentumHunterData/data/backups/score-breakdowns/`
- reports counts for `complete`, `legacy`, `incomplete`, and `failed`

Audit score breakdowns with:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.score_breakdown_audit
```

The score-breakdown audit detects missing breakdowns for active scored candidates, duplicate identities, missing engine versions, malformed component lists, arithmetic mismatches, unexplained cap/floor data, quarantined-source references, and legacy/incomplete records.

## Quarantining Bad Raw Captures

If a raw capture cannot be trusted, move it out of active captures:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.quarantine_capture 2026-06-06 morning --reason "Manifest hash mismatch; excluded from studies."
.\.venv\Scripts\python.exe -m momentum_hunter.rebuild_derived_data
```

If the audit shows `MODIFIED`, use the modified-capture recovery command:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.recover_modified_captures --reason "Manifest hash mismatch; original unavailable; quarantined pending recovery review."
```

If a non-market-day `morning` or `evening` capture is accidentally created beside a valid `preopen` capture, use the legacy cleanup command:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.cleanup_legacy_captures 2026-06-07 --sessions morning evening
```

The legacy cleanup command:

- inspects only the requested date/session raw captures
- quarantines captures that lack calendar metadata or are non-study-eligible
- does not modify raw captures in place
- preserves active captures that are not targeted, such as valid `preopen` files
- backs up `analysis-captures.csv` and `analysis-outcomes.csv` under `MomentumHunterData/data/backups/legacy-cleanup/`
- rebuilds `analysis-captures.csv` from remaining active raw captures
- prunes `analysis-outcomes.csv` to active analysis identities without fetching current market data

The quarantine command:

- moves `{session}.json` and `{session}.md` from `data/captures/YYYY-MM-DD/` into `data/quarantine/raw-captures/YYYYMMDD-HHMMSS/`
- moves active manifest records into `quarantined_records`
- writes timestamped recovery notes with original manifest metadata, current file metadata, hash mismatch evidence, and the recovery decision
- keeps the files available for investigation
- keeps auditing the quarantine copies for existence and SHA-256 drift
- preserves review decisions and marks decisions tied to quarantined captures as quarantined
- excludes the snapshot from rebuilt analysis CSVs, outcome CSVs, and Study Engine results
