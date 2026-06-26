# Autonomous Test Suites

Purpose: give Argus a safe validation menu that avoids broad Qt unittest hangs while still covering backend, storage, evidence, provider, replay, and bounded UI work.

This document changes testing policy only. It does not change scanner logic, scoring math, readiness thresholds, alert thresholds, outcome classification, trade-planning rules, broker behavior, SQLite authority, raw captures, or user-authored state.

## Quick List

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.test_plan --list
.\.venv\Scripts\python.exe -B -m momentum_hunter.test_plan --json
```

## Core Rules

- No full Qt unittest modules unattended.
- No parallel test commands.
- Use bytecode-disabled commands: `python -B` and `PYTHONDONTWRITEBYTECODE=1` when possible.
- Run one bounded module or suite at a time.
- If one command times out, stop and diagnose that command only.
- Kill only stuck test `python.exe` processes, never `pythonw` app windows unless explicitly asked.
- Prefer pure helper/view-model tests before UI probes.

## Suite Matrix

| Suite | Purpose | Recommended Command |
| --- | --- | --- |
| `storage-safe` | File-backed storage, raw-capture integrity, derived stores, source mutation checks | `.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group backend --timeout 60` |
| `sqlite-safe` | SQLite mirror, read model, validation, maintenance, migration slices | `.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group storage --timeout 60` |
| `evidence-safe` | Active monitor, alerts, outcomes, evidence health, reliability, analytics | `.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group evidence --timeout 60` |
| `provider-safe` | Provider errors, market tape health, provider field quality | `.\.venv\Scripts\python.exe -B -m unittest tests.test_provider_errors tests.test_market_tape_health tests.test_provider_field_quality` |
| `replay-safe` | Replay/Candidate Story/data-view point-in-time behavior | `.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group backend --only tests.test_candidate_story_view_model --only tests.test_data_view_state --timeout 30` |
| `ui-bounded-safe` | One isolated offscreen Qt behavior at a time | Use a one-off `QT_QPA_PLATFORM=offscreen` probe with timers/startup patched out |
| `do-not-run-unattended` | Broad Qt modules and visual harnesses | Do not run as an autonomous suite |

## Do Not Run Unattended

- `tests.test_gui_states`
- `tests.test_daily_workflow`
- `tests.test_morning_review_workspace`
- `tests.test_review_workflow`

If one of these areas must be verified, run one exact test under a bounded process or write a one-off probe that:

- sets `QT_QPA_PLATFORM=offscreen`
- patches startup, timers, and scheduled jobs
- constructs only the needed widget/window
- closes and deletes it
- prints one explicit `*_OK` marker
- runs a process check afterward

## Process Check

```powershell
Get-Process python,pythonw -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,StartTime,Path |
  Sort-Object StartTime |
  Format-Table -AutoSize
```

Existing Momentum Hunter `pythonw` windows may remain open. Stale test `python.exe` processes should not.

## Timeout Recovery

1. Stop the sequence.
2. Record the exact command.
3. Run the process check.
4. Stop only the stuck test `python.exe` process.
5. Confirm the process is gone.
6. Replace the broad test with a smaller helper test or isolated probe.
7. Continue only after the boundary is understood.

## Expected Runtime

| Suite | Expected Runtime |
| --- | --- |
| `provider-safe` | under 10 seconds |
| `replay-safe` | under 20 seconds |
| Focused single module | under 30 seconds |
| `storage-safe` | several minutes depending on SQLite slices |
| `evidence-safe` | several minutes depending on active-monitor/evidence tests |
| `ui-bounded-safe` | one probe at a time, under 30 seconds |

## Stop Conditions

Stop testing immediately if:

- a command times out
- a command unexpectedly fetches live/provider data
- raw captures appear modified
- user-authored review/watchlist/entry-plan files appear modified
- SQLite would need to become authoritative
- scoring, readiness, alert, outcome, or trade-planning logic would need to change to make tests pass

The point is boring, bounded validation. If testing starts to feel like a maze, reduce the scope until the failing boundary is obvious.
