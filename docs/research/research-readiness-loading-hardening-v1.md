# Research / Readiness Loading Hardening v1

Momentum Hunter's Research Lab and Readiness Gate are read-only analysis surfaces. They can perform heavier file/report aggregation than the daily operator dashboard, so their launch path must not freeze the main window.

## Current Load Path

Entry points:

- `MomentumHunterWindow.open_study_engine`
- `MomentumHunterWindow.open_readiness_gate`

Both paths use:

- `MomentumHunterWindow._run_report_loader`
- `ReportLoaderWorker`
- `QThread`
- non-modal loading dialog from `_show_loading_dialog`

This means the button click returns control to Qt quickly while report generation runs in a worker thread.

## Hardening Added

The shared report loader now tracks active report titles and ignores duplicate requests while the same report is already loading.

Example:

```text
Research Lab is already loading; please wait.
```

This avoids double-click or repeated navigation requests spawning duplicate expensive report builds.

## Timing Evidence

Bounded tests verify that:

- Research Lab launch returns before a deliberately slow report finishes.
- report failures produce visible feedback through `_show_action_blocked`.
- duplicate report-load requests do not create a second worker.
- worker cleanup clears active loader state after success and failure.

## Safety Rules

This hardening does not:

- change research calculations
- change readiness rules
- change scoring, alert, outcome, or trade-planning logic
- mutate raw captures
- switch any source of truth

## Remaining Risk

The heavy report builders themselves are still file/report aggregation functions. They are protected by the worker wrapper, but future work should continue extracting pure report preparation out of `app.py` and should keep adding focused non-Qt tests around each report builder.

## Validation

Focused validation command:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_report_loader_hardening
```

Related existing coverage:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_gui_states
```

Use the focused loader test during autonomous runs. Avoid broad Qt suites unless explicitly supervised.
