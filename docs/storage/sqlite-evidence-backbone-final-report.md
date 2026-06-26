# SQLite Evidence Backbone Program v1 Final Report

Momentum Hunter remains file-first. SQLite is now a validated additive read-only analytics mirror for provider quality, opportunity alerts, alert outcomes, minute bars, evidence reports, system status, and derived capture/candidate history.

## Commits

| Slice | Commit | Summary |
| --- | --- | --- |
| Foundation | `938f820` | Created SQLite schema/migration foundation and provider quality mirror. |
| Evidence Slice | `b93f815` | Mirrored `opportunity-alerts.json` and embedded alert outcomes. |
| Minute Bars Slice | `e2e11a1` | Mirrored `opportunity-minute-bars.json`. |
| Evidence Runs Slice | `0a69c8f` | Mirrored structured evidence/status reports into `evidence_runs` and `evidence_metrics`. |
| System Status Slice | `4264a28` | Mirrored active monitor, Evidence Autopilot, outcome updater, readiness, data-quality, and market-tape health status events. |
| Capture Index Slice | `0935f29` | Mirrored `analysis-captures.csv` into `captures` and `capture_candidates`. |
| Query Helpers | `fb6256c` | Added read-only query helpers over mirrored tables. |
| Unified Import CLI | `2f4855c` | Documented and validated `--slice all`. |
| Validation Report | `02a8007` | Added SQLite source-count validation reports. |

## Current Database

- Path: `MomentumHunterData/data/momentum-hunter.sqlite3`
- Schema version: `6`
- Source of truth: unchanged file-based stores
- SQLite role: additive analytics mirror only

## Latest Validated Counts

| Table / Source | Count |
| --- | ---: |
| `provider_quality_checks` | 3 |
| `opportunity_alerts` | 2 |
| `alert_outcomes` | 2 |
| `minute_bars` | 710 |
| `evidence_runs` | 14 |
| `evidence_metrics` | 378 |
| `system_status_events` | 16 |
| `captures` | 39 |
| `capture_candidates` | 642 |

## Commands

Run all safe additive imports:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_migration --slice all
```

Validate SQLite mirrors against current source files:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_validation
```

## Latest Reports

- `MomentumHunterData/data/reports/sqlite-import-latest.json`
- `MomentumHunterData/data/reports/sqlite-import-latest.md`
- `MomentumHunterData/data/reports/sqlite-evidence-import-latest.json`
- `MomentumHunterData/data/reports/sqlite-evidence-import-latest.md`
- `MomentumHunterData/data/reports/sqlite-minute-bars-import-latest.json`
- `MomentumHunterData/data/reports/sqlite-minute-bars-import-latest.md`
- `MomentumHunterData/data/reports/sqlite-evidence-runs-import-latest.json`
- `MomentumHunterData/data/reports/sqlite-evidence-runs-import-latest.md`
- `MomentumHunterData/data/reports/sqlite-system-status-import-latest.json`
- `MomentumHunterData/data/reports/sqlite-system-status-import-latest.md`
- `MomentumHunterData/data/reports/sqlite-capture-index-import-latest.json`
- `MomentumHunterData/data/reports/sqlite-capture-index-import-latest.md`
- `MomentumHunterData/data/reports/sqlite-validation-latest.json`
- `MomentumHunterData/data/reports/sqlite-validation-latest.md`

## Safety Notes

- Raw captures were not mutated.
- Existing JSON/CSV/Markdown outputs were not removed or replaced.
- Review decisions, entry plans, watchlists, and raw captures remain file-based.
- Scoring math, readiness rules, alert logic, outcome classification, scanner logic, and trade-planning rules were not changed.
- SQLite is not used as the runtime source of truth yet.

## Remaining File-Based Stores

- Raw captures and raw capture Markdown files
- Integrity manifest and quarantine notes
- Review decisions
- Entry plans
- Watchlists and watchlist reports
- Score breakdowns
- Analysis CSVs
- Opportunity alerts JSON
- Minute bars JSON
- Evidence/status JSON and Markdown reports

## Recommended Next SQLite Slice

The next safe slice is user-authored state planning, but only after an explicit backup/conflict design:

- `candidate_reviews`
- `entry_plans`
- `watchlist_items`

Until backup, restore, conflict resolution, and rollback behavior exist, these should remain file-authoritative.
