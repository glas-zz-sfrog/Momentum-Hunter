# SQLite Migration Foundation v1

Momentum Hunter is not moving to a SQLite-only runtime in this milestone. This foundation keeps the current JSON, Markdown, and CSV behavior intact while adding a small, testable SQLite adapter for derived diagnostic data.

## Safety Contract

- Do not mutate raw captures.
- Do not remove existing JSON, Markdown, or CSV outputs.
- Do not make SQLite the only source of truth yet.
- Do not change scoring, readiness, alert, trade-planning, scanner, broker, or automation behavior.
- Use SQLite as an additive derived mirror until migration confidence is proven.

## Current Storage Audit

| Data Area | Current Source Files | Owner Module / Function | Read / Write Behavior | Data Class | Migration Risk | Recommended Table | Keep / Export JSON Behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Raw captures | `MomentumHunterData/data/captures/YYYY-MM-DD/{morning,evening,preopen,manual}.json` and `.md` | `momentum_hunter.storage.save_daily_capture`, `load_capture_json`, `load_capture_report` | Created once, then read by scanner/replay/study/report builders | Raw immutable | High | `captures`, `capture_candidates` | Keep files as source of truth. SQLite mirror later only after hash validation. |
| Derived candidate CSV | `analysis-captures.csv` | `momentum_hunter.storage.append_analysis_rows`, `write_analysis_rows`; readers in study/replay/outcome modules | Rebuildable derived CSV from raw captures | Derived | Medium | `capture_candidates` | Keep CSV export until all study/report consumers are migrated. |
| Derived outcomes | `analysis-outcomes.csv` | outcome updater / rebuild modules | Rebuildable post-capture labels | Derived/computed | Medium | `alert_outcomes` for alerts, future `candidate_outcomes` if added | Keep CSV export; never write outcomes into raw captures. |
| Review states | `review-decisions.json` | `momentum_hunter.review.load_review_decisions`, `save_review_decisions`, `upsert_review_decision` | Mutable by operator workflow | User-authored journal | High | `candidate_reviews` | Keep JSON as source until bidirectional migration and backup strategy exist. |
| Watchlist artifacts | `watchlist-YYYY-MM-DD.json`, `watchlist-report-YYYY-MM-DD.md` | `momentum_hunter.storage.save_watchlist`, `save_watchlist_report`, `load_latest_watchlist` | User-facing artifacts generated from current review state | User/derived artifact | Medium | `watchlist_items` | Keep JSON/Markdown outputs. SQLite can mirror generated artifact metadata later. |
| Entry plans | `entry-plans.json` | `momentum_hunter.entry_plans.load_entry_plans`, `save_entry_plans`, `upsert_entry_plan` | Mutable user-authored trade plans | User-authored | High | `entry_plans` | Keep JSON as source until migration has backup, conflict, and recovery rules. |
| Opportunity alerts | `opportunity-alerts.json` | `momentum_hunter.opportunity_alerts.load_alerts`, `save_alerts` | Mutable derived alert store with terminal outcome state | Derived evidence | Medium | `opportunity_alerts`, `alert_outcomes` | Keep JSON as source while SQLite mirrors alert evidence later. |
| Alert outcomes status | `alert-outcome-update-status.json` | `momentum_hunter.alert_outcome_updater.save_update_report`, `load_update_report` | Latest status written by outcome updater | Computed status | Low | `evidence_runs`, `evidence_metrics` | Keep status JSON; SQLite can import summaries. |
| Minute bars | `opportunity-minute-bars.json` | `momentum_hunter.alert_outcome_updater.load_minute_bars`, `save_minute_bars` | Derived market-data cache | Derived provider data | Medium | `minute_bars` | Keep JSON cache until provider-quality and retention policy are designed. |
| Evidence reports | `reports/evidence-health-report-*`, `reports/reliability-report-*`, `evidence-autopilot-latest.*` | `momentum_hunter.evidence_health`, `momentum_hunter.evidence_autopilot_reliability` | Disposable reports from current evidence stores | Computed | Low | `evidence_runs`, `evidence_metrics` | Keep Markdown/JSON reports; SQLite stores normalized summaries. |
| Provider/data-quality reports | `reports/data-quality-latest.json`, `.md`, `market-tape-health-*` | `momentum_hunter.data_quality`, `momentum_hunter.market_tape_health` | Disposable diagnostic reports | Computed provider diagnostics | Low | `provider_quality_checks` | First SQLite vertical slice. Keep JSON/Markdown reports. |
| Replay/candidate story data | Raw captures plus `analysis-outcomes.csv`, `review-decisions.json`, `score-breakdowns.json` | `momentum_hunter.replay`, GUI replay helpers | Read-only composition of raw and derived stores | Mixed | Medium | Uses `captures`, `capture_candidates`, `candidate_reviews`, `alert_outcomes` later | Do not move yet. Replay must preserve point-in-time behavior first. |
| Score breakdowns | `score-breakdowns.json` | `momentum_hunter.score_breakdowns`, GUI Why Score view | Rebuildable by score-engine version | Derived explanation | Medium | future `score_breakdowns` table | Keep JSON; do not alter score values. |
| Capture health/status | `capture-failures/*.json`, `active-monitor-status.json`, `active-monitor-runner.json`, `evidence-autopilot-status.json` | `capture_health`, `active_monitor`, `active_monitor_runner`, `evidence_autopilot` | Latest status/failure records | Computed status | Low/Medium | `system_status_events`, `evidence_runs` | Keep JSON status files for UI compatibility. |
| Scheduler state | Windows scheduled tasks plus capture skip/failure JSON | tools scripts, scheduling/capture job modules | External scheduler invokes jobs, app reads derived status | External/system state | Medium | `system_status_events` | Do not rely on SQLite to schedule jobs yet. |
| Manifests/integrity | `integrity/capture_manifest.json`, audit CSV/MD | `momentum_hunter.storage`, `integrity`, `quarantine`, `rebuild_derived` | Manifest is mutable metadata, raw files remain immutable | Integrity metadata | High | future `capture_integrity` table | Keep manifest JSON as source until signed re-baseline policy exists. |

## Initial SQLite Schema Proposal

SQLite database path:

```text
MomentumHunterData/data/momentum-hunter.sqlite3
```

Timestamp convention:

- Store timestamps as ISO-8601 text with timezone offset when known.
- Store derived report generation time separately from source capture time.
- Never infer freshness from missing timestamps.

Raw vs derived distinction:

- Raw capture rows are immutable mirrors of raw files only after hash verification.
- User-authored state must remain conflict-safe and recoverable before moving.
- Computed/derived reports can be safely mirrored first because they are rebuildable.

### Tables

#### `schema_migrations`

- `version INTEGER PRIMARY KEY`
- `name TEXT NOT NULL`
- `applied_at TEXT NOT NULL`

Tracks idempotent migrations.

#### `captures`

- `capture_id TEXT PRIMARY KEY`
- `capture_date TEXT NOT NULL`
- `capture_time TEXT NOT NULL`
- `session TEXT NOT NULL`
- `provider TEXT NOT NULL`
- `scanner TEXT NOT NULL`
- `source_path TEXT NOT NULL UNIQUE`
- `source_hash TEXT`
- `capture_version TEXT`
- `is_quarantined INTEGER NOT NULL DEFAULT 0`
- Index: `(capture_date, session)`
- Purpose: future immutable mirror of raw capture metadata.

#### `capture_candidates`

- `candidate_id TEXT PRIMARY KEY`
- `capture_id TEXT NOT NULL`
- `ticker TEXT NOT NULL`
- `rank INTEGER`
- `score INTEGER`
- `price REAL`
- `percent_change REAL`
- `volume INTEGER`
- `relative_volume REAL`
- `market_cap INTEGER`
- `sector TEXT`
- `industry TEXT`
- `raw_json TEXT`
- Unique: `(capture_id, ticker, rank)`
- Index: `(ticker, capture_id)`

#### `candidate_reviews`

- `review_id TEXT PRIMARY KEY`
- `capture_id TEXT NOT NULL`
- `ticker TEXT NOT NULL`
- `review_status TEXT NOT NULL`
- `decision_timestamp TEXT NOT NULL`
- `decision_note TEXT`
- `review_context_state TEXT`
- `delayed_review INTEGER NOT NULL DEFAULT 0`
- Unique: `(capture_id, ticker)`

#### `watchlist_items`

- `watchlist_item_id TEXT PRIMARY KEY`
- `capture_id TEXT NOT NULL`
- `ticker TEXT NOT NULL`
- `watchlist_date TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `source_review_id TEXT`
- Unique: `(capture_id, ticker, watchlist_date)`

#### `entry_plans`

- `entry_plan_id TEXT PRIMARY KEY`
- `capture_id TEXT NOT NULL`
- `ticker TEXT NOT NULL`
- `trigger_condition TEXT`
- `stop_price REAL`
- `thesis TEXT`
- `invalidation TEXT`
- `max_loss TEXT`
- `position_size_idea TEXT`
- `planned_hold_time TEXT`
- `notes TEXT`
- `plan_complete INTEGER NOT NULL DEFAULT 0`
- `updated_at TEXT NOT NULL`
- Unique: `(capture_id, ticker)`

#### `opportunity_alerts`

- `alert_id TEXT PRIMARY KEY`
- `symbol TEXT NOT NULL`
- `alert_type TEXT NOT NULL`
- `timestamp TEXT NOT NULL`
- `current_state TEXT`
- `entry_price REAL`
- `bid REAL`
- `ask REAL`
- `spread_percent REAL`
- `rvol REAL`
- `source_json TEXT`
- Index: `(symbol, timestamp)`

#### `alert_outcomes`

- `alert_id TEXT PRIMARY KEY`
- `status TEXT NOT NULL`
- `classification TEXT NOT NULL`
- `return_5m REAL`
- `return_15m REAL`
- `return_30m REAL`
- `return_60m REAL`
- `mfe_60m REAL`
- `mae_60m REAL`
- `target_1_hit INTEGER`
- `target_2_hit INTEGER`
- `stop_hit INTEGER`
- `updated_at TEXT NOT NULL`

#### `minute_bars`

- `symbol TEXT NOT NULL`
- `timestamp TEXT NOT NULL`
- `open REAL`
- `high REAL`
- `low REAL`
- `close REAL`
- `volume INTEGER`
- `source TEXT`
- Primary key: `(symbol, timestamp, source)`

#### `evidence_runs`

- `run_id TEXT PRIMARY KEY`
- `run_type TEXT NOT NULL`
- `generated_at TEXT NOT NULL`
- `source_path TEXT`
- `source_hash TEXT`
- `summary_json TEXT`
- Unique: `(run_type, generated_at, source_hash)`

#### `evidence_metrics`

- `metric_id TEXT PRIMARY KEY`
- `run_id TEXT NOT NULL`
- `metric_name TEXT NOT NULL`
- `metric_value REAL`
- `metric_text TEXT`
- Unique: `(run_id, metric_name)`

#### `system_status_events`

- `event_id TEXT PRIMARY KEY`
- `event_type TEXT NOT NULL`
- `status TEXT NOT NULL`
- `occurred_at TEXT NOT NULL`
- `source_path TEXT`
- `details_json TEXT`
- Index: `(event_type, occurred_at)`

#### `provider_quality_checks`

- `check_id TEXT PRIMARY KEY`
- `generated_at TEXT NOT NULL`
- `symbol TEXT NOT NULL`
- `provider TEXT NOT NULL`
- `usable_market_tape INTEGER NOT NULL`
- `last_price REAL`
- `bid REAL`
- `ask REAL`
- `spread_percent REAL`
- `relative_volume REAL`
- `fields_returned TEXT`
- `missing_fields TEXT`
- `warnings TEXT`
- `source_report_path TEXT`
- `source_report_hash TEXT`
- Unique: `(generated_at, symbol, provider, source_report_hash)`
- Index: `(symbol, generated_at)`

## Migration and Versioning Strategy

- Use `schema_migrations` for forward-only, idempotent migrations.
- Version 1 creates the schema above.
- Runtime systems continue reading/writing current JSON and CSV files.
- SQLite imports are additive mirrors with source path and SHA-256 hash.
- Future migrations should use one vertical slice at a time and include export validation.

## First Vertical Slice

The first implemented slice is provider/data-quality reports:

- Source: `MomentumHunterData/data/reports/data-quality-latest.json`
- SQLite table: `provider_quality_checks`
- Reason: derived, low-risk, rebuildable, and useful for system trust.
- Existing JSON/Markdown reports remain the operator-facing artifact.

## Deferred Slices

- Raw captures: defer until hash manifest and quarantine behavior are fully mirrored.
- Review/watchlist/entry plans: defer until backup/restore and conflict handling are designed.
- Alerts/minute bars: likely next after provider-quality checks because they are evidence-critical but still derived.
