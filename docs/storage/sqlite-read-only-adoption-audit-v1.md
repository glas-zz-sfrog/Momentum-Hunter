# SQLite Read-Only Adoption Audit & Shadow Mode v1

Momentum Hunter remains file-authoritative. This audit identifies safe read-only SQLite adoption points without changing runtime source-of-truth behavior.

## Preflight Baseline

- Latest baseline commit before this milestone: `f55e246 Add SQLite read model reports`
- SQLite database: `MomentumHunterData/data/momentum-hunter.sqlite3`
- SQLite schema version: `7`
- SQLite validation status: `PASS`
- SQLite read-model comparison status: `PASS`
- SQLite shadow compare status: `PASS`

Current SQLite row counts:

| Table | Rows |
| --- | ---: |
| `provider_quality_checks` | 3 |
| `opportunity_alerts` | 2 |
| `alert_outcomes` | 2 |
| `minute_bars` | 710 |
| `evidence_runs` | 14 |
| `evidence_metrics` | 378 |
| `system_status_events` | 18 |
| `captures` | 39 |
| `capture_candidates` | 642 |

Current live read-model results:

| Report | Result |
| --- | --- |
| Candidate Story | 197 candidate stories |
| Evidence | 2 alerts, 1 completed outcome, 0 pending outcomes, 1 unscorable outcome |
| Watchlist/Plans | 17 mirrored watchlist review decisions, 8 watchlist artifacts, 0 complete plans, 26 incomplete plans |
| System Readiness | validation status `PASS`, no missing slices |
| Shadow Compare | `PASS`, no mismatches |

2026-06-26 follow-up validation found stale rows in the additive `system_status_events` mirror after mutable latest-status source files were regenerated. The system-status importer now removes stale rows for the same source path when the current source file parses to different event IDs. After repair, SQLite validation and shadow compare returned `PASS` with 18 current system-status events.

## Source Modes

Momentum Hunter now has a read-only facade in `momentum_hunter/read_models.py`.

Supported modes:

| Mode | Meaning | Runtime Default |
| --- | --- | --- |
| `file` | Use current JSON/CSV/Markdown-derived file summaries. | Yes |
| `sqlite` | Use SQLite read-model summaries. | No |
| `shadow` | Compare file summaries with SQLite summaries without changing what the app uses. | No |

Environment flag:

```text
MOMENTUM_HUNTER_READ_MODEL_SOURCE=file
MOMENTUM_HUNTER_READ_MODEL_SOURCE=sqlite
MOMENTUM_HUNTER_READ_MODEL_SOURCE=shadow
```

The default is `file`. No live UI workflow is switched to SQLite by this milestone.

## Adoption Surface Matrix

| Surface | Current File-Based Source | SQLite Read Model Available | Safe Read-Only Use? | Required Fallback | Risk | Test Requirements | Recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Candidate Story / Timeline | `analysis-captures.csv`, active raw captures, replay helpers, outcome CSV, review JSON | `captures`, `capture_candidates`, `candidate_reviews`, `entry_plans`; Candidate Story report | Partial | Fall back to existing Replay file/raw-capture path if SQLite missing, stale, or lacks identity fields | Medium | Point-in-time identity, raw-capture no-mutation, historical row parity, missing SQLite fallback | SQLite shadow compare only for UI; safe optional mode for report-only Candidate Story |
| Evidence reports | `opportunity-alerts.json`, `opportunity-minute-bars.json`, evidence report JSON | `opportunity_alerts`, `alert_outcomes`, `minute_bars`, `evidence_runs`; Evidence report | Yes for reports | Fall back to JSON alert/minute-bar stores | Low | Alert count parity, outcome class parity, unscorable preservation, minute-bar count parity | Safe read-only SQLite optional mode for CLI/report surfaces |
| Alert performance reports | `opportunity-alerts.json`, embedded outcomes, minute-bar outcomes | `opportunity_alerts`, `alert_outcomes`, `minute_bars` | Partial | Fall back to alert JSON until performance grouping parity is explicitly tested | Medium | Group-by alert type/symbol/readiness parity, completed-only math parity, unscorable exclusion | SQLite shadow compare only; add dedicated performance parity tests before optional mode |
| System Readiness / Health future UI | latest reliability/status JSON, active monitor status, evidence autopilot status | `system_status_events`, `provider_quality_checks`, `evidence_runs`; System Readiness report | Yes for summary reports | Fall back to latest status JSON files | Low | Status normalization parity, missing status-file warnings, stale import detection | Safe read-only SQLite optional mode for report summaries; keep UI default file-based |
| Watchlist / Plans reporting | `review-decisions.json`, `watchlist-*.json`, `entry-plans.json` | `candidate_reviews`, `watchlist_items`, `entry_plans`; Watchlist report | Yes for diagnostic reports only | Fall back to user-authored JSON/Markdown files | Medium | Backup/diff freshness, review-status parity, entry-plan completeness parity, no write-back | Safe read-only SQLite optional mode for reports; UI and writes remain file-authoritative |
| Research Lab | `analysis-captures.csv`, outcomes CSV, raw captures, cluster engines, score breakdown JSON | Partial via capture/evidence/user-state mirrors | Not yet | Existing file/research engines | High | Full study filters, non-study exclusion, cluster parity, outcome math parity, no score recalculation | Defer SQLite adoption; use SQLite only for diagnostics/shadow counts |
| Opportunity Research | `analysis-captures.csv`, `analysis-outcomes.csv`, clusters, score breakdowns, review JSON | Partial; no full outcome/research-feature mirror yet | Not yet | Existing file-based research path | High | Grouping parity, pending exclusion, sample warning parity, cluster metric parity | Defer |
| Outcome Explorer | `analysis-captures.csv`, `analysis-outcomes.csv`, clusters, review JSON | Partial; alert outcomes mirrored but study outcomes remain CSV-first | Not yet | Existing file-based outcome explorer | High | Study outcome parity, filter parity, completed/pending math parity | Defer |
| CLI reports | Existing report generators | SQLite report CLI and read-model facade | Yes | CLI can warn and fall back where caller chooses file mode | Low | CLI JSON/Markdown output, missing DB warnings, source non-mutation | Safe optional read-only SQLite mode |
| Dashboard summary cards | Mixed live app state, latest JSON reports, active monitor status, current capture context | Partial via read-model summaries and status events | Not by default | Existing dashboard state and JSON files | Medium | UI responsiveness, stale SQLite banner, fallback on missing DB, no workflow changes | Shadow compare only; no default UI switch |

## Read-Only Provider Facade

Module:

```text
momentum_hunter/read_models.py
```

Purpose:

- provide one read-only access point for file, SQLite, or shadow report summaries
- keep default behavior file-based
- allow CLI/report code to test SQLite summaries without moving UI writes or runtime state
- warn clearly if SQLite is missing, stale, or mismatched

The facade does not write files or database rows. Report writing remains in `sqlite_reports.py` and only writes derived reports under `MomentumHunterData/data/reports`.

## Shadow Compare Mode

CLI:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_reports --shadow-compare
```

Outputs:

```text
MomentumHunterData/data/reports/sqlite-shadow-compare-latest.json
MomentumHunterData/data/reports/sqlite-shadow-compare-latest.md
```

Shadow compare checks:

- Candidate Story candidate count
- Evidence alert/outcome/minute-bar counts
- Watchlist and entry-plan counts
- System-readiness status where comparable
- Evidence Autopilot state where comparable
- SQLite validation status and missing slices

It reports:

- matching fields
- mismatches
- unavailable fields
- missing data
- stale SQLite data
- fallback reason
- recommended action

## Safe Adoption Guidance

Safe now for optional SQLite read-only use:

- CLI report generation
- Evidence read-model reports
- Watchlist/Plans diagnostic reports
- System Readiness diagnostic reports
- Candidate Story report-only summaries

Keep shadow-only for now:

- Candidate Story / Timeline UI
- Dashboard summary cards
- Alert performance analytics

Defer:

- Research Lab
- Opportunity Research
- Outcome Explorer
- Any user-state write path

## Cutover Safety Boundary

SQLite still must not become authoritative for:

- raw captures
- review decisions
- watchlists
- entry plans
- study outcomes
- score breakdowns
- active UI workflow state

Before any runtime adoption, the calling surface must define:

- file fallback behavior
- stale SQLite detection
- warning language
- parity tests
- source-file non-mutation tests
- rollback behavior

## Testing Requirements

Minimum tests before optional SQLite mode is allowed on a surface:

- file mode remains default
- SQLite mode returns expected summaries
- missing SQLite DB warns cleanly
- shadow compare detects matches
- shadow compare detects mismatches
- source files are not mutated
- stale SQLite data is reported
- JSON/Markdown report generation works

## Recommendation

Proceed in this order:

1. Keep runtime UI file-based.
2. Use `sqlite_reports --shadow-compare` as the guardrail before any SQLite adoption.
3. Allow optional SQLite read mode only for CLI/report surfaces first.
4. Add dedicated parity tests before any Candidate Story, dashboard, Research Lab, Outcome Explorer, or Opportunity Research UI reads from SQLite.
