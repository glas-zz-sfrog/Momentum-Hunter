# ARGUS-0002 Daily Checklist Visibility

Date: 2026-06-27
Branch: `codex/ARGUS-0002-daily-checklist-visibility`
Owner: Argus Orchestrator
Status: Complete, pending Steven review

## Scope
Restore a clearly visible path to the existing Daily Checklist workflow in the Momentum Hunter UI with the smallest safe UI change possible.

## Office Roles
- `code_mapper`: Confirmed Daily Checklist report/dialog code exists and the existing button was created/wired but not mounted into the visible dashboard layout.
- `ui_operator_designer`: Recommended restoring a single Dashboard Session-area action rather than adding a new left-rail page or duplicate navigation.
- `builder`: Added the existing `Daily Checklist` button to the Dashboard Session grid and added focused regression coverage.
- `qa_regression`: Bounded verification used focused Daily Workflow GUI tests.
- `release_scribe`: Recorded this release report, task log, current state, and Argus changelog updates.

## Files Changed
- `momentum_hunter/app.py`
- `tests/test_daily_workflow.py`
- `docs/argus-office/reports/releases/ARGUS-0002-daily-checklist-visibility.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CURRENT_STATE.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`

## UI Path Restored
The Dashboard Session area now shows the existing `Daily Checklist` button beside the market controls. Clicking it opens the existing `Daily Workflow Checklist` dialog and reuses the existing checklist, warnings, and quick actions.

No new Daily page, navigation rail destination, workflow report model, or data store was added.

## Implementation Notes
- Reused the existing `self.daily_checklist_button` and `open_daily_workflow_checklist()` handler.
- Daily Checklist quick actions now close the checklist before invoking the existing target workflow, so follow-on dialogs and guard messages are visible to the operator.
- Added a focused test assertion that the button is mounted into a widget parent.
- Updated the existing dialog smoke test to open the checklist through `daily_checklist_button.click()`.
- Added focused quick-action coverage for `Open Morning Review`, `Generate Watchlist Report`, `Open Capture Health`, and `Open Readiness Gate`.
- Added the missing `latest_active_monitor_cycle_json_path` import needed for the main window to instantiate during verification.

## Tests or Checks Run
- `git branch --show-current`
- `git merge-base master HEAD`
- `git status --short`
- `rg`/static source mapping for Daily Checklist code and UI wiring
- `.\.venv\Scripts\python.exe -B -m unittest tests.test_daily_workflow`

Result: the focused Daily Workflow tests passed.

## Protected Areas
No changes were made to scoring logic, trade readiness logic, replay identity rules, historical capture selection, SQLite/database schema or migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, package/dependency files, generated data, market data/report outputs, or production config.

## Manual QA
1. Launch Momentum Hunter on this branch.
2. Confirm the Dashboard Session area shows exactly one `Daily Checklist` button beside the market controls.
3. Click `Daily Checklist`.
4. Confirm the `Daily Workflow Checklist` dialog opens with `Checklist` and `Warnings` tabs.
5. Confirm the dialog quick actions remain visible: `Open Morning Review`, `Generate Watchlist Report`, `Open Capture Health`, and `Open Readiness Gate`.
6. Click `Open Morning Review`; confirm the checklist closes and Morning Review opens, or a clear unavailable message appears if candidates are missing.
7. Click `Generate Watchlist Report`; confirm the checklist closes and either the existing watchlist generation flow runs or a clear message explains that Watchlist candidates are required.
8. Click `Open Capture Health`; confirm the checklist closes and Capture Health opens.
9. Click `Open Readiness Gate`; confirm the checklist closes and Readiness Gate opens or reports a visible load/error state.
10. Confirm no new left-rail page or duplicate Daily Checklist entry was added.

## Risks
- The visible path is restored on the Dashboard only. A future redesign may decide to make Daily Checklist a full Daily Workflow page, but that was intentionally out of scope.
- A missing import in `app.py` blocked the focused GUI test before the checklist assertion could run; it was fixed as a minimal verification unblocker.
- Full visual screenshot regeneration was not performed in this task.

## Open Questions
- Should a future UI task promote Daily Checklist into a full daily workflow page, or should it remain a Dashboard modal action?

## Recommendation
Steven should review the Dashboard path manually, then merge only if the single-button Dashboard access point feels obvious enough for daily operation. Recommended next task: repair screenshot-capture validation so UI screenshot evidence must be nonblank and have sane dimensions before it is trusted.
