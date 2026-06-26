# Night Shift Offline Platform Hardening Sprint v1

Start date: 2026-06-26

Purpose: use offline time to make Momentum Hunter more maintainable, testable, reliable, and ready for future operator/UI work without requiring visual inspection or live market-hours decisions.

## Starting Commit

```text
79e498c Complete roadmap reconciliation autonomous closure sprint
```

The worktree was clean at sprint start.

## Safety Constraints

This sprint must not:

- change scoring math
- change readiness thresholds
- change alert thresholds
- change outcome classification logic
- change trade-planning logic
- add broker integration
- add automated trading
- make SQLite authoritative
- overwrite user-authored files
- mutate raw captures
- remove existing JSON/CSV/Markdown outputs
- break file-based fallback behavior
- create an engine dependency on the UI
- perform broad visual UI redesign
- perform market-hours operational proof

## Starting Validation State

### SQLite Validation

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
| evidence_metrics | 378 |
| system_status_events | 18 |
| captures | 39 |
| capture_candidates | 642 |

### System Readiness

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.system_readiness
```

Result:

```text
Overall status: WARNING
```

Current warnings:

- Captures: a capture failure record exists at `MomentumHunterData/data/capture-failures/2026-06-22-070003-morning.json`.
- Active Monitor: monitor is IDLE and has warnings for target/source trade rows, coverage rows, missing market data, and no new opportunity alerts.
- Evidence Autopilot: latest completed run is stale, evidence threshold is locked below 25 completed alerts, and one alert is unscorable.
- Outcome Tracking: 1 completed alert, 0 pending alerts, 1 unscorable alert.

### SQLite Read Models

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_reports --all
```

Result:

| Report | Status |
| --- | --- |
| Candidate Story read model | OK |
| Evidence read model | OK |
| Watchlist read model | OK |
| System Readiness read model | PASS |
| File-vs-SQLite comparison | PASS |
| Shadow compare | PASS |

Latest generated reports:

- `MomentumHunterData/data/reports/sqlite-candidate-story-read-model-latest.json`
- `MomentumHunterData/data/reports/sqlite-evidence-read-model-latest.json`
- `MomentumHunterData/data/reports/sqlite-watchlist-read-model-latest.json`
- `MomentumHunterData/data/reports/sqlite-system-readiness-read-model-latest.json`
- `MomentumHunterData/data/reports/sqlite-read-model-comparison-latest.json`
- `MomentumHunterData/data/reports/sqlite-shadow-compare-latest.json`

## Planned Phases

| Phase | Name | Intended deliverable |
| --- | --- | --- |
| 0 | Preflight | This sprint kickoff record |
| 1 | `app.py` Modularization Round 2 | Additional low-risk view-model/helper extraction |
| 2 | Research / Readiness Loading Hardening | Timing audit and safe non-blocking hardening where practical |
| 3 | SQLite Backup / Maintenance Safety Layer | Backup and integrity-check CLI/report |
| 4 | Offline Evidence Pipeline Drill | Fixture/temp-directory evidence pipeline drill |
| 5 | Provider Field Quality Audit | Diagnostic provider field quality reports |
| 6 | System Readiness Enhancement | Clearer top-level readiness summary and priority issue |
| 7 | Test Harness Commands and Safe Suites | Autonomous test-suite docs/helper updates |
| 8 | Report and Artifact Index | Latest report index JSON/Markdown |
| 9 | Read-Only Analytics Query Pack | SQLite read-only analytics summaries |
| 10 | Final Validation and Sleep-Sprint Report | Final report and validation summary |

## Stop Conditions

Stop and report immediately if:

- raw capture mutation risk appears
- user-authored files could be overwritten
- SQLite would need to become authoritative
- file-vs-SQLite validation suggests data loss
- scoring/readiness/alert/outcome/trade-planning logic would need to change
- UI changes become broad or subjective
- provider changes would alter scanner behavior
- tests reveal a serious integrity defect
- a broad architecture decision is required

## Phase 0 Result

Phase 0 is complete.

Starting state is acceptable for offline platform work:

- Worktree clean.
- SQLite validation PASS.
- SQLite read models PASS/OK.
- System Readiness WARNING due to known operational/evidence state, not data-integrity failure.
- No raw capture or user-authored state mutation detected.

## Phase 1 Result

Phase 1 is complete.

Goal:

- Continue reducing `app.py` responsibility without visual redesign or behavior changes.

Implemented:

- Added `momentum_hunter/candidate_story_view_model.py`.
- Moved pure Candidate Story data/view-model helpers out of `app.py`:
  - `CandidateStoryPoint`
  - `CandidateStorySummary`
  - `build_candidate_story_summary`
  - Candidate Story status classification
  - capture/story formatting helpers
  - marker detail/spec preparation
- Left Qt table/chart construction in `app.py`.
- Preserved existing `momentum_hunter.app` import compatibility by importing the moved helpers back into `app.py`.
- Added `tests/test_candidate_story_view_model.py`.
- Added the new test module to `tools/run_bounded_tests.py` backend group.

Validation:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_candidate_story_view_model tests.test_replay
.\.venv\Scripts\python.exe -B -m py_compile momentum_hunter\app.py momentum_hunter\candidate_story_view_model.py tests\test_candidate_story_view_model.py
```

Result:

```text
22 tests passed
Syntax check passed
```

Safety:

- No visual layout change.
- No scoring change.
- No readiness change.
- No alert/outcome/trade-planning change.
- No raw capture or user-authored file mutation.
- `app.py` became smaller and less responsible.

## Phase 2 Result

Phase 2 is complete.

Goal:

- Make Research Lab and Readiness Gate safer to open without freezing the dashboard.

Implemented:

- Confirmed Research Lab and Readiness Gate already use a `QThread`-backed `ReportLoaderWorker` and non-modal loading dialog.
- Added a duplicate-loader guard so repeated clicks do not launch multiple workers for the same report title while one is already active.
- Preserved the existing loading dialog and failure feedback behavior.
- Added `docs/research/research-readiness-loading-hardening-v1.md`.
- Added focused bounded Qt tests in `tests/test_report_loader_hardening.py`.

Validation:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_report_loader_hardening
.\.venv\Scripts\python.exe -B -m py_compile momentum_hunter\app.py tests\test_report_loader_hardening.py
```

Safety:

- No research calculation changes.
- No readiness rule changes.
- No scoring, alert, outcome, or trade-planning changes.
- No raw capture or user-authored file mutation.
- No broad UI redesign.

## Phase 3 Result

Phase 3 is complete.

Goal:

- Add safe SQLite maintenance and backup tooling without making SQLite authoritative.

Implemented:

- Added `momentum_hunter/sqlite_maintenance.py`.
- Added read-only SQLite integrity/schema/table checks.
- Added timestamped SQLite backup snapshots under `MomentumHunterData/backups/sqlite/YYYYMMDD-HHMMSS/`.
- Added backup manifests with source/backup SHA-256, size, schema version, table counts, and backup validation status.
- Added latest JSON/Markdown reports at `MomentumHunterData/data/reports/sqlite-maintenance-latest.*`.
- Added focused tests in `tests/test_sqlite_maintenance.py`.

Validation:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_sqlite_maintenance
.\.venv\Scripts\python.exe -B -m py_compile momentum_hunter\sqlite_maintenance.py tests\test_sqlite_maintenance.py
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_maintenance --check
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_maintenance --backup
```

Production result:

```text
SQLite maintenance status: PASS
Integrity check: ok
Schema version: 7
Backup: MomentumHunterData/backups/sqlite/20260626-013518/
Backup validation: PASS
```

Safety:

- Check mode opens SQLite read-only.
- Backup mode copies the database and validates the copy.
- No source DB hash change was detected during tests.
- No raw captures, user-authored files, scoring, readiness, alerts, outcomes, or trade plans were changed.

## Phase 4 Result

Phase 4 is complete.

Goal:

- Prove the evidence pipeline can execute offline without live market data or production evidence pollution.

Implemented:

- Added `momentum_hunter/offline_evidence_drill.py`.
- The drill creates a synthetic fixture workspace, writes a fixture alert and minute bars, runs the existing alert outcome updater, imports the fixture evidence into a fixture SQLite DB, validates the fixture mirror, and writes a report.
- Added latest JSON/Markdown outputs at `MomentumHunterData/data/reports/offline-evidence-drill-latest.*`.
- Added focused tests in `tests/test_offline_evidence_drill.py`.

Validation:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_offline_evidence_drill
.\.venv\Scripts\python.exe -B -m py_compile momentum_hunter\offline_evidence_drill.py tests\test_offline_evidence_drill.py
.\.venv\Scripts\python.exe -B -m momentum_hunter.offline_evidence_drill
```

Production drill result:

```text
Offline drill status: PASS
Fixture symbol: DRILL
Alerts processed: 1
Outcomes completed: 1
SQLite fixture validation: PASS
Production alert store mutated: False
```

Safety:

- Synthetic alerts/minute bars stay in a temporary fixture workspace.
- The fixture workspace is cleaned after the run.
- Production `opportunity-alerts.json` hash was unchanged.
- No live provider calls were made.
- No scoring, readiness, alert threshold, outcome classification, trade-planning, raw capture, or user-authored state changes.

## Phase 5 Result

Phase 5 is complete.

Goal:

- Build a diagnostic foundation for scanner/provider field reliability, especially fields such as relative volume, market cap, volume, price, and timestamps.

Implemented:

- Added `momentum_hunter/provider_field_quality.py`.
- Added a CLI:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.provider_field_quality
```

- The audit reads stored `analysis-captures.csv` rows and checks:
  - provider
  - scanner
  - symbol
  - field name
  - present/missing state
  - zero values
  - impossible values
  - stale capture timestamps
  - source endpoint/path
  - confidence
  - usability
  - fallback source placeholder
- Fields audited:
  - price
  - percent change
  - volume
  - relative volume
  - average volume
  - market cap
  - bid
  - ask
  - spread
  - premarket price
  - premarket volume
  - headline timestamp
- Added latest JSON/Markdown outputs:
  - `MomentumHunterData/data/reports/provider-field-quality-latest.json`
  - `MomentumHunterData/data/reports/provider-field-quality-latest.md`
- Added focused tests in `tests/test_provider_field_quality.py`.

SQLite handling:

- The audit does not write field-level rows to SQLite because the current `provider_quality_checks` table stores symbol-level market-tape checks, not field-level scanner audit rows.
- The report records this explicitly as `SKIPPED_UNSUPPORTED_SCHEMA`.

Validation:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_provider_field_quality
.\.venv\Scripts\python.exe -B -m py_compile momentum_hunter\provider_field_quality.py tests\test_provider_field_quality.py
.\.venv\Scripts\python.exe -B -m momentum_hunter.provider_field_quality
```

Production audit result:

```text
Provider field quality status: WARN
Source rows: 642
Audit rows: 7704
SQLite write status: SKIPPED_UNSUPPORTED_SCHEMA
Top warnings: STALE_CAPTURE_TIMESTAMP, ZERO_RELATIVE_VOLUME
Report warnings: STALE_CAPTURE_ROWS, PROVIDER_FIELD_WARNINGS_PRESENT, SKIPPED_UNSUPPORTED_SCHEMA
```

Safety:

- Diagnostic reporting only.
- No provider behavior changes.
- No scanner threshold changes.
- No scoring changes.
- No readiness, alert, outcome, or trade-planning changes.
- No raw capture or user-authored state mutation.

## Phase 6 Result

Phase 6 is complete.

Goal:

- Make System Readiness more useful as a future dashboard foundation by providing a clear top-level answer and priority issue.

Implemented:

- Enhanced `momentum_hunter/system_readiness.py`.
- Added top-level report fields:
  - `status_reason`
  - `highest_priority_issue`
  - `recommended_next_action`
  - `section_status_counts`
  - `changes_since_previous`
- Added stale active-monitor detection with `STALE_ACTIVE_MONITOR_CYCLE` when the latest monitor cycle is older than the readiness freshness threshold.
- Added stale Evidence Autopilot visibility through the existing autopilot reliability report.
- Added stale SQLite mirror detection with `STALE_SQLITE_MIRROR` when latest SQLite import metadata is too old.
- Added `Active Alert Reliability` as a readiness section.
- Added `Provider Field Quality` as a readiness section.
- Updated Markdown output so the executive summary appears before section details.
- Added focused tests in `tests/test_reliability_reports.py`.

Validation:

```powershell
.\.venv\Scripts\python.exe -B -m py_compile momentum_hunter\system_readiness.py tests\test_reliability_reports.py
.\.venv\Scripts\python.exe -B -m unittest tests.test_reliability_reports
.\.venv\Scripts\python.exe -B -m momentum_hunter.system_readiness
```

Production readiness result:

```text
System Readiness status: WARNING
Highest priority issue: Captures: A capture failure record exists.
Recommended next action: Open Capture Health for failure details.
Status counts: READY 8, WARNING 6, FAILED 0, UNKNOWN 0
New sections surfaced: Active Alert Reliability, Provider Field Quality
```

Safety:

- Reporting-only change.
- No readiness threshold changes.
- No scoring changes.
- No scanner/provider behavior changes.
- No alert, outcome, or trade-planning changes.
- No raw capture or user-authored state mutation.
- SQLite remains additive/read-only for this purpose.

## Phase 7 Result

Phase 7 is complete.

Goal:

- Make autonomous testing easier and less likely to hang.

Implemented:

- Added `docs/testing/autonomous-test-suites.md`.
- Added `momentum_hunter/test_plan.py`.
- The helper lists safe suites without running them:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.test_plan --list
.\.venv\Scripts\python.exe -B -m momentum_hunter.test_plan --json
```

- Defined suite lanes:
  - `storage-safe`
  - `sqlite-safe`
  - `evidence-safe`
  - `provider-safe`
  - `replay-safe`
  - `ui-bounded-safe`
  - `do-not-run-unattended`
- Reused the existing `tools/run_bounded_tests.py` runner for actual bounded execution.
- Added focused tests in `tests/test_test_plan.py`.

Validation:

```powershell
.\.venv\Scripts\python.exe -B -m py_compile momentum_hunter\test_plan.py tests\test_test_plan.py
.\.venv\Scripts\python.exe -B -m unittest tests.test_test_plan
.\.venv\Scripts\python.exe -B -m momentum_hunter.test_plan --list
```

Safety:

- Test-policy/tooling only.
- No full test framework rewrite.
- No application behavior changes.
- No scanner, scoring, readiness, alert, outcome, trade-planning, broker, SQLite-authority, raw-capture, or user-authored state changes.
