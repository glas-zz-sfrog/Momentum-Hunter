# SQLite Read-Only Adoption Audit & Shadow Mode v1 Final Report

Momentum Hunter remains file-authoritative. This milestone added a read-only adoption audit, a report-summary facade, and shadow comparison reporting so SQLite can be evaluated safely before any runtime adoption.

## Scope Completed

- Ran SQLite preflight validation and existing read-model report generation.
- Added `docs/storage/sqlite-read-only-adoption-audit-v1.md`.
- Added `momentum_hunter/read_models.py` as a read-only facade for `file`, `sqlite`, and `shadow` modes.
- Added `python -m momentum_hunter.sqlite_reports --shadow-compare`.
- Added `sqlite-shadow-compare-latest.json` and `.md` report generation.
- Added focused non-Qt tests for source-mode defaults, SQLite summaries, missing DB behavior, shadow matches, shadow mismatches, source-file non-mutation, and CLI report generation.
- Updated README, changelog, and storage map.

## Runtime Safety

This milestone did not:

- make SQLite authoritative
- mutate raw captures
- overwrite review decisions, watchlists, or entry plans
- change default UI behavior
- change scanner logic
- change scoring math
- change readiness rules
- change alert logic
- change outcome classification
- change trade-planning rules

## Adoption Surfaces Audited

| Surface | Recommendation |
| --- | --- |
| Candidate Story / Timeline | Shadow compare only for UI; safe optional SQLite mode for report-only Candidate Story summaries |
| Evidence reports | Safe optional SQLite read-only mode for reports |
| Alert performance reports | Shadow compare only until grouping parity tests exist |
| System Readiness / Health future UI | Safe optional SQLite read-only mode for summary reports; UI default remains file-based |
| Watchlist / Plans reporting | Safe optional SQLite read-only mode for diagnostic reports only |
| Research Lab | Defer |
| Opportunity Research | Defer |
| Outcome Explorer | Defer |
| CLI reports | Safe optional SQLite read-only mode |
| Dashboard summary cards | Shadow compare only; no default UI switch |

## Reports Generated

```text
MomentumHunterData/data/reports/sqlite-shadow-compare-latest.json
MomentumHunterData/data/reports/sqlite-shadow-compare-latest.md
```

Existing read-model reports were also regenerated during preflight:

```text
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
```

## Preflight Results

- SQLite schema version: `7`
- SQLite validation: `PASS`
- Existing read-model comparison: `PASS`
- Shadow compare: `PASS`
- Shadow warnings: `0`

SQLite table counts at preflight:

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

2026-06-26 follow-up: a rerun found that mutable latest-status source files could leave stale `system_status_events` rows in the SQLite mirror. The importer now removes stale rows for the same source path before validating current parsed events. The refreshed mirror removed 11 stale rows and validation returned `PASS`.

## Feature Flags

Added report-summary source mode support:

```text
MOMENTUM_HUNTER_READ_MODEL_SOURCE=file
MOMENTUM_HUNTER_READ_MODEL_SOURCE=sqlite
MOMENTUM_HUNTER_READ_MODEL_SOURCE=shadow
```

Default remains `file`. This flag is not wired into live UI workflows by this milestone.

## Validation

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_validation
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_reports --all
.\.venv\Scripts\python.exe -B -m unittest tests.test_read_models tests.test_sqlite_reports
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_reports --shadow-compare
```

Results:

- Syntax check: PASS
- Focused read-model/report tests: PASS, 14 tests
- Live SQLite validation: PASS
- Live SQLite reports: PASS
- Live shadow compare: PASS
- System-status stale-row cleanup: PASS, 11 stale rows removed during local mirror repair

## Recommended Next Step

Keep runtime UI file-based. The next safe milestone is one dedicated report-only adoption pilot: use the facade to power a CLI/report surface from SQLite optional mode, keep file fallback active, and require shadow compare PASS before the report is trusted.
