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
