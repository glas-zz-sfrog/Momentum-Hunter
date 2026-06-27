# Offline Platform Maturity Sprint v1

Start date: 2026-06-26

Purpose: mature Momentum Hunter's offline platform by improving source-of-truth hygiene, mirror freshness, user-state recovery planning, SQLite evidence coverage, analytics readiness, and validation reporting without changing trading behavior.

## Starting Commit

```text
8b96983 Complete offline platform hardening sprint
```

Branch:

```text
master
```

The worktree was clean at sprint start.

## Safety Constraints

This sprint must not:

- change scoring math
- change readiness rules
- change alert logic
- change outcome classification logic
- change trade-planning rules
- add broker integration
- add automated trading
- make SQLite authoritative
- overwrite user-authored files
- mutate raw captures
- mutate production evidence stores with synthetic data
- remove existing JSON/CSV/Markdown outputs
- break file-based fallback behavior
- create an engine dependency on the UI
- perform broad visual UI redesign

## Stop Conditions

Stop before implementation if:

- source-of-truth safety is unclear
- data integrity risk appears
- raw captures would need mutation
- user-authored state would be affected
- scoring, readiness, alert, outcome, or trade-planning logic would need to change
- a broad architecture decision is required

## Milestone 0 Preflight

### Initial SQLite Validation

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_validation
```

Initial result:

```text
Overall status: FAIL
```

Reason:

```text
The SQLite mirror was stale after new captures arrived.
Source captures: 41
SQLite captures: 39
Source capture candidates: 675
SQLite capture candidates: 642
```

This was a mirror freshness issue, not a raw-capture integrity issue.

### Safe SQLite Mirror Refresh

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_migration --slice all-safe
```

Result:

```text
Overall status: PASS
Warnings: 0
```

Capture mirror refresh:

| Metric | Count |
| --- | ---: |
| Analysis rows seen | 675 |
| Captures seen | 41 |
| Captures inserted | 2 |
| Captures updated | 39 |
| Candidates seen | 675 |
| Candidates inserted | 33 |
| Candidates updated | 642 |
| Source capture rows in SQLite | 41 |
| Source candidate rows in SQLite | 675 |

### Post-Refresh SQLite Validation

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_validation
```

Result:

```text
Overall status: PASS
Schema version: 7
Warnings: 0
```

Row counts:

| Table | Rows |
| --- | ---: |
| provider_quality_checks | 3 |
| opportunity_alerts | 2 |
| alert_outcomes | 2 |
| minute_bars | 710 |
| evidence_runs | 14 |
| evidence_metrics | 380 |
| system_status_events | 20 |
| captures | 41 |
| capture_candidates | 675 |

Capture session counts:

| Session | Captures |
| --- | ---: |
| morning | 18 |
| evening | 18 |
| manual | 2 |
| preopen | 3 |

### SQLite Shadow Compare

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_reports --shadow-compare
```

Result:

```text
Overall status: PASS
Warnings: 0
```

### System Readiness

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.system_readiness
```

Result:

```text
Overall status: WARNING
Ready sections: 8
Warning sections: 6
Failed sections: 0
Unknown sections: 0
```

Warnings:

- Last capture failure record exists: `MomentumHunterData\data\capture-failures\2026-06-22-070003-morning.json`
- `STALE_ACTIVE_MONITOR_CYCLE`
- `STALE_EVIDENCE_AUTOPILOT_RUN`

Highest priority issue:

```text
Captures: A capture failure record exists.
```

Recommended next action:

```text
Open Capture Health for failure details.
```

### Report Index

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.report_index
```

Result:

```text
Overall status: WARN
Report count: 15
Missing reports: 1
Stale reports: 2
Warnings: MISSING_REPORTS:1, STALE_REPORTS:2
```

## Sprint Milestones

| Milestone | Name | Status |
| --- | --- | --- |
| 0 | Preflight validation and sprint kickoff documentation | Complete |
| 1 | Mutable source hygiene and mirror freshness program | Complete |
| 2 | User-state disaster recovery and cutover simulation | Complete |
| 3 | SQLite analytics, performance, and evidence census | Complete |
| 4 | Final validation and sprint closeout report | Complete |

## Milestone 0 Result

Milestone 0 is complete.

SQLite validation and shadow compare pass after the additive all-safe mirror refresh. System Readiness and Report Index both report warnings that should remain visible during the sprint, but neither warning requires changing trading logic or mutating raw captures.

SQLite remains an additive mirror. File-based JSON/CSV/Markdown outputs remain preserved and authoritative where they are currently the source of truth.

## Milestone 1 Result

Milestone 1 is complete.

Added:

- `momentum_hunter/source_registry.py`
- `momentum_hunter/sqlite_mirror_freshness.py`
- `docs/storage/source-classification-and-mirror-freshness-v1.md`
- `tests/test_source_registry.py`
- `tests/test_sqlite_mirror_freshness.py`

Updated:

- `momentum_hunter/report_index.py`

The new source registry classifies raw captures, derived evidence files, user state, user artifacts, integrity metadata, and SQLite mirrors. The new mirror freshness report validates SQLite mirror tables against current source hashes/counts and distinguishes `all-safe` mirrors from explicit user-state import/cutover mirrors.

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_mirror_freshness
```

Report paths:

```text
MomentumHunterData/data/reports/sqlite-mirror-freshness-latest.json
MomentumHunterData/data/reports/sqlite-mirror-freshness-latest.md
```

During validation, the freshness report first detected stale `system_status_events` rows after new preflight reports were generated:

```text
Overall status: FAIL
Failure: system_status_events source 20 / current SQLite 5
```

After the additive all-safe refresh:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_migration --slice all-safe
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_mirror_freshness
```

Result:

```text
Overall status: PASS
Warnings: 0
```

Focused tests:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_source_registry tests.test_sqlite_mirror_freshness tests.test_sqlite_validation tests.test_report_index
```

Result:

```text
Ran 9 tests
OK
```

Safety notes:

- No raw captures were mutated.
- No user-authored state was imported or changed.
- SQLite remains an additive mirror.
- `review-decisions.json`, `entry-plans.json`, and `watchlist-*.json` remain outside `all-safe` and require explicit user-state cutover workflow.

## Milestone 2 Result

Milestone 2 is complete.

Added:

- `momentum_hunter/user_state_cutover_simulation.py`
- `tests/test_user_state_cutover_simulation.py`
- `docs/storage/user-state-disaster-recovery-and-cutover-simulation-v1.md`

Updated:

- `momentum_hunter/report_index.py`

The user-state cutover simulation uses synthetic fixtures and a temporary workspace under `MomentumHunterData/data/_tmp/`, then deletes that workspace by default. It does not touch production `review-decisions.json`, `entry-plans.json`, or `watchlist-*.json`.

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.user_state_cutover_simulation
```

Report paths:

```text
MomentumHunterData/data/reports/user-state-cutover-simulation-latest.json
MomentumHunterData/data/reports/user-state-cutover-simulation-latest.md
```

Result:

```text
Overall status: PASS
Scenarios: 10
Passed scenarios: 10
Failed scenarios: 0
```

Scenario coverage:

| Scenario | Detection Result | Observed Status |
| --- | --- | --- |
| clean_import | PASS | PASS |
| missing_watchlist_row | PASS | WARN |
| stale_entry_plan | PASS | WARN |
| duplicate_review | PASS | WARN |
| conflicting_review_status | PASS | WARN |
| malformed_entry_plan | PASS | WARN |
| incomplete_entry_plan | PASS | WARN |
| backup_restore_validation_failure | PASS | FAIL |
| rollback_simulation | PASS | PASS |
| source_files_unchanged | PASS | PASS |

Focused tests:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_user_state_cutover_simulation tests.test_user_state_safety tests.test_user_state_diff tests.test_sqlite_user_state_store tests.test_report_index
```

Result:

```text
Ran 15 tests
OK
```

Safety notes:

- Synthetic fixtures were used.
- Production user-state files were not mutated.
- Production evidence stores were not populated with synthetic data.
- SQLite remains an additive mirror.
- User-state cutover remains blocked until backup, restore validation, diff, simulation, rollback, and explicit approval all pass.

## Milestone 3 Result

Milestone 3 is complete.

Added:

- `momentum_hunter/sqlite_benchmarks.py`
- `momentum_hunter/evidence_census.py`
- `tests/test_sqlite_benchmarks.py`
- `tests/test_evidence_census.py`
- `docs/analytics/sqlite-evidence-census-v1.md`

Updated:

- `momentum_hunter/report_index.py`

Reports:

```text
MomentumHunterData/data/reports/sqlite-query-benchmark-latest.json
MomentumHunterData/data/reports/sqlite-query-benchmark-latest.md
MomentumHunterData/data/reports/evidence-census-latest.json
MomentumHunterData/data/reports/evidence-census-latest.md
MomentumHunterData/data/reports/candidate-data-completeness-latest.json
MomentumHunterData/data/reports/candidate-data-completeness-latest.md
```

Commands:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_benchmarks
.\.venv\Scripts\python.exe -B -m momentum_hunter.evidence_census
```

Results:

```text
SQLite Query Benchmark: PASS
Benchmark queries: 9
Max query time: 4.433 ms

Evidence Census: WARN
Warning: LOW_COMPLETED_ALERT_SAMPLE
Total alerts: 2
Completed alerts: 1
Pending alerts: 0
Unscorable alerts: 1
Captures: 41
Capture candidates: 675
Study eligible captures: 36
Minute bars: 710
Minute bar symbols: 1

Candidate Data Completeness: PASS
Candidate rows: 675
```

Focused tests:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_sqlite_benchmarks tests.test_evidence_census tests.test_sqlite_analytics tests.test_report_index
```

Result:

```text
Ran 13 tests
OK
```

Safety notes:

- Reports are read-only against SQLite.
- No raw captures were mutated.
- No user-authored state was mutated.
- No trading logic, scoring, readiness, alerts, outcomes, or trade plans were changed.
- The evidence census warning is expected: completed alert sample size remains too low for optimization.

## Milestone 4 Result

Milestone 4 is complete.

Final bounded validation confirmed the offline platform work is coherent, SQLite mirrors are current, and user-state cutover remains safely simulated rather than activated.

Final commands:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_source_registry tests.test_sqlite_mirror_freshness tests.test_user_state_cutover_simulation tests.test_sqlite_benchmarks tests.test_evidence_census tests.test_sqlite_validation tests.test_report_index tests.test_user_state_safety tests.test_user_state_diff tests.test_sqlite_user_state_store tests.test_sqlite_analytics
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_migration --slice all-safe
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_validation
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_reports --shadow-compare
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_mirror_freshness
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_benchmarks
.\.venv\Scripts\python.exe -B -m momentum_hunter.evidence_census
.\.venv\Scripts\python.exe -B -m momentum_hunter.user_state_cutover_simulation
.\.venv\Scripts\python.exe -B -m momentum_hunter.report_index
```

Final validation summary:

| Check | Result |
| --- | --- |
| Focused non-Qt tests | 31 tests OK |
| SQLite all-safe import | PASS |
| SQLite validation | PASS |
| SQLite shadow compare | PASS |
| SQLite mirror freshness | PASS |
| SQLite query benchmark | PASS |
| Evidence census | WARN: `LOW_COMPLETED_ALERT_SAMPLE` |
| Candidate data completeness | PASS |
| User-state cutover simulation | PASS |
| System readiness | WARNING: capture failure record plus stale monitor/autopilot signals |
| Report index | WARN: missing/stale report artifacts still need routine maintenance |

Final SQLite counts:

| Table | Rows |
| --- | ---: |
| provider_quality_checks | 3 |
| opportunity_alerts | 2 |
| alert_outcomes | 2 |
| minute_bars | 710 |
| evidence_runs | 14 |
| evidence_metrics | 380 |
| system_status_events | 20 |
| captures | 41 |
| capture_candidates | 675 |

Final report:

```text
docs/platform/offline-platform-maturity-sprint-v1-final-report.md
```

Safety notes:

- SQLite remains additive, not authoritative.
- File-based JSON/CSV/Markdown behavior remains preserved.
- Raw captures were not mutated.
- Production user-authored state was not changed.
- Synthetic user-state fixtures were temporary and cleaned up.
- No scoring, readiness, alert, outcome, scanner, or trade-planning logic was changed.
