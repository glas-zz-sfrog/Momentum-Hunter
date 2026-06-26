# SQLite Evidence Backbone Program v1

Momentum Hunter is still file-first. SQLite is an additive evidence mirror that makes future analytics faster and easier to query, but JSON/CSV/Markdown files remain the active source of truth.

## Safety Contract

- Do not mutate raw captures.
- Do not mutate existing JSON, CSV, or Markdown source files during import.
- Do not remove existing file-based outputs.
- Do not change scoring math, readiness rules, alert logic, outcome classification logic, scanner thresholds, trade-planning rules, broker behavior, or automated-trading behavior.
- Do not migrate user-authored state as authoritative until backup, conflict handling, and rollback rules exist.
- Preserve engine/UI separation.

## Completed Slices

| Slice | Commit | Tables | Source files | Source-of-truth status |
| --- | --- | --- | --- | --- |
| SQLite Migration Foundation v1 | `938f820` | Schema foundation plus `provider_quality_checks` | `MomentumHunterData/data/reports/data-quality-latest.json` | File reports remain authoritative |
| SQLite Evidence Slice v1 | `b93f815` | `opportunity_alerts`, `alert_outcomes` | `MomentumHunterData/data/opportunity-alerts.json` | JSON alert store remains authoritative |
| Minute Bars Slice | `e2e11a1` | `minute_bars` | `MomentumHunterData/data/opportunity-minute-bars.json` | JSON minute-bar cache remains authoritative |
| Evidence Runs / Evidence Metrics Slice | `0a69c8f` | `evidence_runs`, `evidence_metrics` | structured evidence/status JSON reports | JSON evidence reports remain authoritative |
| System Status Events Slice | `4264a28` | `system_status_events` | structured status/readiness JSON reports | JSON status reports remain authoritative |

## Current Preflight

- Current schema version before this program: `2`
- Existing tables: `schema_migrations`, `provider_quality_checks`, `opportunity_alerts`, `alert_outcomes`, `minute_bars`, `evidence_runs`, `evidence_metrics`, `system_status_events`, `captures`, `capture_candidates`, `candidate_reviews`, `watchlist_items`, `entry_plans`
- Current imported counts before Minute Bars Slice:
  - `provider_quality_checks`: 3
  - `opportunity_alerts`: 2
  - `alert_outcomes`: 2
  - `minute_bars`: 0

After Phase 1:

- Schema version: `3`
- `minute_bars`: 710
- Symbols mirrored: `CRWV`
- Minute-bar range: `2026-06-18T07:07:00-05:00` to `2026-06-18T18:59:53-05:00`

After Phase 2:

- Schema version: `4`
- `evidence_runs`: 14
- `evidence_metrics`: 378
- Run types mirrored:
  - `alert_outcome_update_status`: 1
  - `alert_performance`: 2
  - `evidence_autopilot_reliability`: 1
  - `evidence_autopilot_status`: 1
  - `evidence_health`: 7
  - `evidence_reliability`: 2

After Phase 3:

- Schema version: `5`
- `system_status_events`: 16
- Status counts:
  - `READY`: 8
  - `WARNING`: 8
- Event types mirrored:
  - `active_monitor_status`: 1
  - `alert_outcome_update`: 1
  - `data_quality:market_tape`: 1
  - `evidence_autopilot_status`: 1
  - `market_tape_health`: 1
  - `system_readiness:*`: 11

After Phase 4:

- Schema version: `6`
- `captures`: 39
- `capture_candidates`: 642
- Source: `MomentumHunterData/data/analysis-captures.csv`
- Source hash: `967af838ffabedb7846135ac724c8f0f6135123aa1b03c5cd58290b760a25afc`
- Warnings: none

## Planned Slices

| Phase | Slice | Tables | Source files | Commit target |
| --- | --- | --- | --- | --- |
| 1 | Minute Bars Slice | `minute_bars` | `opportunity-minute-bars.json` | Complete: `Add SQLite minute bars slice` |
| 2 | Evidence Runs / Evidence Metrics Slice | `evidence_runs`, `evidence_metrics` | evidence autopilot status, evidence health reports, alert performance summaries, outcome update status | Complete: `Add SQLite evidence runs slice` |
| 3 | System Status Events Slice | `system_status_events` | active monitor status, evidence autopilot status, provider/data-quality/status reports | Complete: `Add SQLite system status slice` |
| 4 | Capture / Candidate Read-Only Index Slice | `captures`, `capture_candidates` | derived analysis CSV plus raw capture file hashes where safe | Complete: `Add SQLite capture index slice` |
| 5 | Read-Only Query Helpers | query helpers over existing tables | SQLite mirrors only | Complete: `Add SQLite read-only query helpers` |
| 6 | Unified Import CLI | all safe slices | all mirrored evidence sources | Complete: validated existing `--slice all` workflow |
| 7 | Validation / Integrity Report | validation reports | source files plus SQLite mirrors | Complete: `Add SQLite validation report` |
| 8 | Documentation and Final Report | docs only | current program evidence | final documentation update |

## Table Ownership

| Table | Owner module | Current slice | Authoritative source |
| --- | --- | --- | --- |
| `provider_quality_checks` | `momentum_hunter.sqlite_store` | Complete additive mirror | `data-quality-latest.json` |
| `opportunity_alerts` | `momentum_hunter.sqlite_store` | Complete additive mirror | `opportunity-alerts.json` |
| `alert_outcomes` | `momentum_hunter.sqlite_store` | Complete additive mirror | embedded outcomes in `opportunity-alerts.json` |
| `minute_bars` | `momentum_hunter.sqlite_store` | Complete additive mirror | `opportunity-minute-bars.json` |
| `evidence_runs` | `momentum_hunter.sqlite_store` | Complete additive mirror | structured evidence/status JSON files |
| `evidence_metrics` | `momentum_hunter.sqlite_store` | Complete additive mirror | structured evidence/status JSON files |
| `system_status_events` | `momentum_hunter.sqlite_store` | Phase 3 additive mirror | status/report files |
| `captures` | `momentum_hunter.sqlite_store` | Phase 4 additive mirror | `analysis-captures.csv` plus raw capture source hashes |
| `capture_candidates` | `momentum_hunter.sqlite_store` | Phase 4 additive mirror | `analysis-captures.csv` |

## What Remains File-Based

- Raw captures and raw capture Markdown reports
- Capture integrity manifest and audit reports
- Review decisions
- Entry plans
- Watchlist JSON/Markdown artifacts
- Score breakdowns
- Analysis CSVs
- Opportunity alert JSON store
- Minute-bar JSON cache until Phase 1 completes
- Evidence and system status reports until later slices complete

## Phase 2 Evidence Runs Source Audit

The Evidence Runs slice imports structured JSON only. Markdown daily briefs and report Markdown files remain human-facing artifacts and are not imported in this phase.

Imported source patterns:

- `MomentumHunterData/data/evidence-autopilot-status.json`
- `MomentumHunterData/data/alert-outcome-update-status.json`
- `MomentumHunterData/data/reports/evidence-autopilot-latest.json`
- `MomentumHunterData/data/reports/evidence-health-report-*.json`
- `MomentumHunterData/data/reports/reliability-report-*.json`
- `MomentumHunterData/data/reports/alert-performance-report-*.json`

Each source file becomes one `evidence_runs` row. Scalar fields and list counts become `evidence_metrics` rows. Full source JSON is preserved in `summary_json`, and report paths remain in `report_paths_json`.

## Phase 3 System Status Source Audit

The System Status slice imports structured JSON only. It normalizes monitor, readiness, provider, and outcome-update status into queryable event rows while preserving the full source JSON in `details_json`.

Imported source patterns:

- `MomentumHunterData/data/active-monitor-status.json`
- `MomentumHunterData/data/evidence-autopilot-status.json`
- `MomentumHunterData/data/alert-outcome-update-status.json`
- `MomentumHunterData/data/reports/system-readiness-latest.json`
- `MomentumHunterData/data/reports/data-quality-latest.json`
- `MomentumHunterData/data/reports/market-tape-health-*.json`

Identity rules:

- `event_id = sha256("system_status_event", event_type, occurred_at, source_path)`
- `system-readiness-latest.json` creates one overall row and one row per readiness section.
- Latest/overwritten source files update the same event row when `event_type`, `occurred_at`, and source path remain stable.
- Status values are normalized for analytics as `READY`, `WARNING`, `FAILED`, `INFO`, or `UNKNOWN` where possible.

Missing-data behavior:

- Missing explicit status becomes `UNKNOWN`.
- Sources with warnings become `WARNING` unless an explicit failure/error is present.
- Missing source files passed explicitly are reported as warnings and create no event rows.

## Phase 4 Capture / Candidate Index Source Audit

The Capture Index slice imports `analysis-captures.csv` only. It does not parse, edit, or rewrite raw capture JSON files. When the active raw JSON exists at `MomentumHunterData/data/captures/YYYY-MM-DD/{session}.json`, the importer records the raw source path and SHA-256 hash for traceability. The analysis CSV remains authoritative for the indexed candidate fields.

Imported source:

- `MomentumHunterData/data/analysis-captures.csv`

Identity rules:

- `capture_id = sha256("capture", capture_date, capture_time, session, provider, scanner)`
- `candidate_id = sha256("capture_candidate", capture_id, ticker, rank)`
- Candidate uniqueness is `(capture_id, ticker, rank)`.
- Capture source rows update safely if the derived CSV changes while the capture identity stays the same.

Missing-data behavior:

- Missing raw capture JSON is warned as `RAW_CAPTURE_JSON_MISSING` but does not block indexing the CSV row.
- Missing capture-time or ticker fields are warned.
- Duplicate candidate identities in the CSV are warned and de-duplicated for SQLite import.

## Phase 5 Read-Only Query Helpers

The read-only query helper slice adds `momentum_hunter.sqlite_queries` for safe analytics access over the mirrored tables. It does not add schema, write reports, mutate source files, or redirect runtime workflows.

Helpers:

- `sqlite_backbone_summary`: schema version and table counts
- `alert_evidence_summary`: completed, pending, and unscorable alert-outcome counts
- `candidate_history_for_ticker`: capture/candidate history for one ticker from SQLite mirrors
- `latest_system_status`: latest status rows, optionally filtered by normalized status

## Phase 6 Unified Import CLI

The unified safe import path is:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_migration --slice all
```

Validated latest run:

- Schema version: `6`
- Provider quality: 3 rows, no warnings
- Opportunity alerts: 2 alerts / 2 outcomes, no warnings
- Minute bars: 710 CRWV bars, no warnings
- Evidence runs: 14 runs / 378 metrics, no warnings
- System status: 16 events, no warnings
- Capture index: 39 captures / 642 candidates, no warnings

The unified report is written to:

- `MomentumHunterData/data/reports/sqlite-import-latest.json`
- `MomentumHunterData/data/reports/sqlite-import-latest.md`

## Phase 7 SQLite Validation Report

The SQLite validation report is read-only:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_validation
```

Validated latest report:

- Overall status: `PASS`
- SQLite schema version: `6`
- Provider quality: source 3 / SQLite 3
- Opportunity alerts: source 2 / SQLite 2
- Alert outcomes: source 2 / SQLite 2
- Minute bars: source 710 / SQLite 710
- Evidence runs: source 14 / SQLite 14
- System status events: source 16 / SQLite 16
- Captures: source 39 / SQLite 39
- Capture candidates: source 642 / SQLite 642
- Warnings: none

Reports:

- `MomentumHunterData/data/reports/sqlite-validation-latest.json`
- `MomentumHunterData/data/reports/sqlite-validation-latest.md`

## Future Cutover Rules

SQLite cannot become authoritative until all of these are true:

1. Every mirrored slice has deterministic import tests and validation reports.
2. Source-file-to-SQLite counts, hashes, and identity keys can be audited.
3. User-authored state has backup, restore, conflict resolution, and rollback behavior.
4. Raw capture immutability and quarantine rules remain enforceable.
5. Existing GUI and CLI workflows can run from SQLite without losing file export behavior.
6. A signed migration note documents the exact cutover scope.

## Risks

| Risk | Mitigation |
| --- | --- |
| SQLite mirror silently diverges from source files | Add per-slice validation reports and source hashes. |
| Importing invalid market data creates misleading analytics | Skip invalid rows with warnings and preserve source files unchanged. |
| JSON schema drift causes bad rows | Parse through existing domain loaders where safe and add defensive raw validation where counts matter. |
| SQLite becomes accidental source of truth | Keep CLI/report language explicit and do not redirect runtime readers yet. |
| Migration scope becomes too broad | Use small vertical slices and clean commits. |
| Import performance degrades on historical capture index | Stop and design batching/indexing before Phase 4 if needed. |

## Recommended Program Exit State

At the end of this program, Momentum Hunter should be able to query provider quality, alerts, outcomes, minute bars, evidence runs, system status, and candidate/capture history from SQLite for read-only analytics while preserving all existing file-based workflows and exports.
