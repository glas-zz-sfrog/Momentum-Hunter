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
| 1 | Mutable source hygiene and mirror freshness program | Pending |
| 2 | User-state disaster recovery and cutover simulation | Pending |
| 3 | SQLite analytics, performance, and evidence census | Pending |
| 4 | Final validation and sprint closeout report | Pending |

## Milestone 0 Result

Milestone 0 is complete.

SQLite validation and shadow compare pass after the additive all-safe mirror refresh. System Readiness and Report Index both report warnings that should remain visible during the sprint, but neither warning requires changing trading logic or mutating raw captures.

SQLite remains an additive mirror. File-based JSON/CSV/Markdown outputs remain preserved and authoritative where they are currently the source of truth.
