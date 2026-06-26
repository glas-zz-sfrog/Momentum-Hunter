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

## Planned Slices

| Phase | Slice | Tables | Source files | Commit target |
| --- | --- | --- | --- | --- |
| 1 | Minute Bars Slice | `minute_bars` | `opportunity-minute-bars.json` | Complete: `Add SQLite minute bars slice` |
| 2 | Evidence Runs / Evidence Metrics Slice | `evidence_runs`, `evidence_metrics` | evidence autopilot status, evidence health reports, alert performance summaries, outcome update status | In progress: `Add SQLite evidence runs slice` |
| 3 | System Status Events Slice | `system_status_events` | active monitor status, evidence autopilot status, provider/data-quality/status reports | `Add SQLite system status slice` |
| 4 | Capture / Candidate Read-Only Index Slice | `captures`, `capture_candidates` | capture manifest, derived analysis CSVs, raw capture metadata where safe | `Add SQLite capture index slice` |
| 5 | Read-Only Query Helpers | read helpers over existing tables | SQLite mirrors only | `Add SQLite read-only query helpers` |
| 6 | Unified Import CLI | all safe slices | all mirrored evidence sources | `Add SQLite all-safe import workflow` |
| 7 | Validation / Integrity Report | validation reports | source files plus SQLite mirrors | `Add SQLite validation report` |
| 8 | Documentation and Final Report | docs only | current program evidence | final documentation update |

## Table Ownership

| Table | Owner module | Current slice | Authoritative source |
| --- | --- | --- | --- |
| `provider_quality_checks` | `momentum_hunter.sqlite_store` | Complete additive mirror | `data-quality-latest.json` |
| `opportunity_alerts` | `momentum_hunter.sqlite_store` | Complete additive mirror | `opportunity-alerts.json` |
| `alert_outcomes` | `momentum_hunter.sqlite_store` | Complete additive mirror | embedded outcomes in `opportunity-alerts.json` |
| `minute_bars` | `momentum_hunter.sqlite_store` | Complete additive mirror | `opportunity-minute-bars.json` |
| `evidence_runs` | `momentum_hunter.sqlite_store` | Phase 2 additive mirror | structured evidence/status JSON files |
| `evidence_metrics` | `momentum_hunter.sqlite_store` | Phase 2 additive mirror | structured evidence/status JSON files |
| `system_status_events` | `momentum_hunter.sqlite_store` | Planned Phase 3 | status/report files |
| `captures` | `momentum_hunter.sqlite_store` | Planned Phase 4 | raw captures and manifest |
| `capture_candidates` | `momentum_hunter.sqlite_store` | Planned Phase 4 | raw captures and derived candidate rows |

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
