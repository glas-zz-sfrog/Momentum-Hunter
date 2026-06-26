# Test Harness Reliability v1

Date: 2026-06-26

Purpose: prevent Momentum Hunter validation from getting trapped by long-running Qt unittest modules or orphaned `python.exe` processes.

This is a test-harness policy and tooling slice only. It does not change scanner logic, scoring math, readiness rules, alert thresholds, outcome classification, trade-planning rules, SQLite authority, broker behavior, or raw captures.

## Core Rule

Do not run broad Qt unittest modules unattended.

Use safe backend/storage/evidence groups, one bounded subprocess per module, and isolated Qt smoke probes only when UI behavior must be checked.

If a command times out:

- stop the sequence
- record the exact command
- terminate only the stuck test `python.exe` process
- do not retry or continue into a broader suite until the failing boundary is understood

## Safe Runner

Use:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --list
```

Run a safe group:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group evidence --timeout 60
```

Run one module from a safe group:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group evidence --only tests.test_active_alert_reliability --timeout 30
```

The runner:

- disables bytecode writes through `PYTHONDONTWRITEBYTECODE=1`
- runs each module in a separate subprocess
- applies a timeout to each module
- reports `PASS`, `FAIL`, or `TIMEOUT`
- does not run known risky Qt modules

## Safe Test Groups

### Backend Safe

General non-Qt behavior checks:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group backend --timeout 60
```

Use this for scanner-adjacent parsing, scoring explainability, scheduling policy, capture integrity, outcome math, catalyst/news analytics, and pure model/storage behavior.

### Storage Safe

SQLite and derived-storage checks:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group storage --timeout 60
```

Use this after SQLite additive-slice work, read-model work, validation work, and user-state mirror work.

### Evidence Safe

Active monitor, alert, outcome, and evidence-report checks:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group evidence --timeout 60
```

Use this after alert/evidence/autopilot/reporting changes.

## Bounded UI Smoke Policy

UI verification should use isolated offscreen probes, not broad Qt unittest modules.

Every Qt smoke probe should:

- set `QT_QPA_PLATFORM=offscreen`
- set `PYTHONDONTWRITEBYTECODE=1`
- patch timers/startup/scheduled work
- create exactly one `QApplication`
- construct only the needed window/dialog
- close and delete the window
- print one explicit `*_OK` marker
- run a process check afterward

Process check:

```powershell
Get-Process python,pythonw -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,StartTime,Path |
  Sort-Object StartTime |
  Format-Table -AutoSize
```

Existing Momentum Hunter `pythonw` windows may remain open. Stale test `python.exe` processes should not.

## Do Not Run Unattended

These modules have historically involved Qt lifecycle behavior or combined GUI harness risk and should not be used as routine unattended validation:

- `tests.test_gui_states`
- `tests.test_daily_workflow`
- `tests.test_morning_review_workspace`
- `tests.test_review_workflow`

If a test from one of these modules is needed, extract the smallest isolated probe or run one exact test under a bounded process with a follow-up process check.

## Known Slow/Risky Areas

| Area | Risk | Preferred check |
| --- | --- | --- |
| Combined Qt lifecycle unittest groups | May stall and leave `python.exe` alive | Isolated offscreen probes |
| Research Lab / Readiness Gate | Can do heavy report construction | Non-blocking loader probe |
| Full app screenshot tooling | Can depend on app state and display behavior | Run manually when visual proof is required |
| Live/provider checks | Can block on network/provider behavior | Use mocked tests or explicit provider-health commands |
| SQLite import validation | Can touch derived mirrors | Run storage group; do not promote SQLite authority |

## Stop Conditions

Stop validation immediately if:

- a bounded command times out
- a Qt probe leaves a `python.exe` test runner alive
- a command starts fetching live data unexpectedly
- source-of-truth files or raw captures appear in `git status`
- a test would require changing scoring/readiness/alert/trade-planning behavior

## Recovery Procedure

1. Capture the exact command that hung.
2. Run the process check.
3. Kill only the spawned test `python.exe` process.
4. Confirm no leftover test `python.exe` remains.
5. Document the failing boundary in the current milestone report.
6. Replace the broad test with a smaller isolated probe before continuing.

## Recommended Validation Pattern

For autonomous backend work:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group backend --timeout 60
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group storage --timeout 60
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group evidence --timeout 60
```

For focused work, prefer one module:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group evidence --only tests.test_active_alert_reliability --timeout 30
```

This keeps validation boring, bounded, and recoverable.
