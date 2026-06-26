# Phase 1B Workflow Verification

Date: 2026-06-26

Scope: verify the objective Phase 1B operator-workflow fixes before continuing broader UI redesign work.

This verification did not change scanner logic, scoring math, readiness rules, alert logic, outcome classification, trade-planning rules, SQLite authority, or raw captures.

## Summary

Phase 1B workflow paths are present and passed isolated verification probes for:

- checked-row preservation during candidate selection and detail refresh
- Dashboard Interested to Watchlist Center synchronization
- Watchlist Center promotion to Watchlist status through the shared action path
- Why Score readable formatting
- Research Lab non-blocking loader behavior
- Readiness Gate non-blocking loader behavior

The combined Qt unittest group still exposed the known test-harness risk: multiple Qt lifecycle tests in one process can hang. The app paths passed when executed as isolated probes.

## Verification Results

| Area | Result | Evidence |
| --- | --- | --- |
| Checkbox / selection safety | PASS | `CHECKBOX_WATCHLIST_PROBE_OK` |
| Candidate detail refresh preserves checks | PASS | Same isolated probe selected another row and refreshed details while preserving the checked row. |
| Dashboard to Watchlist Center sync | PASS | Same isolated probe marked MDT Interested, opened Watchlist Center, then promoted to Watchlist. |
| Canonical Move Interested to Watchlist behavior | PASS | Dashboard and Watchlist Center both call `add_interested_to_watchlist`. |
| Why Score formatting | PASS | `WHY_SCORE_FORMATTING_PROBE_OK` |
| Research Lab non-blocking loader | PASS | `RESEARCH_LOADER_PROBE_OK` |
| Readiness Gate non-blocking loader | PASS | `READINESS_LOADER_PROBE_OK` |
| Broad/combined Qt unittest stability | FAIL / KNOWN HARNESS RISK | A combined targeted Qt unittest command printed two tests and then stalled. The spawned `python.exe` processes were terminated. |

## Commands And Probes

### Combined Qt Unittest Attempt

This command was intentionally stopped after it did not finish promptly:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -B -m unittest `
  tests.test_review_workflow.ReviewWorkflowGuiTests.test_dashboard_interested_candidate_updates_watchlist_center_immediately `
  tests.test_gui_states.GuiStateTests.test_checked_rows_survive_row_selection_and_detail_refresh `
  tests.test_gui_states.GuiStateTests.test_research_lab_open_returns_control_before_slow_report_finishes `
  tests.test_gui_states.GuiStateTests.test_score_breakdown_html_uses_readable_units_and_freshness_note `
  tests.test_gui_states.GuiStateTests.test_readiness_gate_failure_shows_visible_feedback `
  tests.test_gui_states.GuiStateTests.test_research_lab_failure_shows_visible_feedback
```

Observed result:

- Output reached `..`
- Process did not complete within the bounded wait
- Two `python.exe` processes from the test start time were terminated
- No `python.exe` or `pythonw.exe` processes remained afterward

Conclusion: do not use combined Qt unittest groups as the proof mechanism for Phase 1B. Use isolated probes or a dedicated bounded Qt runner.

### Isolated Verification Markers

The following isolated probes completed successfully:

```text
CHECKBOX_WATCHLIST_PROBE_OK
WHY_SCORE_FORMATTING_PROBE_OK
RESEARCH_LOADER_PROBE_OK
READINESS_LOADER_PROBE_OK
```

Final process checks after probes showed no leftover Python processes.

## Implementation Findings

### Implemented And Visible

- Candidate action buttons live above the candidate table.
- `Clear Checkmarks` is near the candidate table and only clears table checkmarks.
- Watchlist Center uses a summary/table backed by current candidates and review decisions.
- Research Lab and Readiness Gate use a non-blocking loading dialog path.
- Why Score labels use `Base Points` and `Applied Impact`.

### Implemented Internally

- Row selection and detail refresh call `_show_candidate_details` and `_refresh_row_states` without clearing checkboxes.
- `_refresh_row_states(clear_checks=True)` is only used by explicit bulk review/watchlist actions.
- Dashboard and Watchlist Center both route interested-to-watchlist movement through `add_interested_to_watchlist`.
- Research Lab and Readiness Gate report builders use `QThread` via `_run_report_loader`.

### Deferred Or Requires Manual UI Inspection

- Pixel-level "misclick near checkbox" behavior is not fully proven by the current non-event probes. The data path is safe, but true pointer-position testing would require a bounded Qt event harness.
- Active nav styling and midnight-blue active page canvas are broad visual redesign items and remain Phase 2, not Phase 1B.
- Candidate Story chart legend readability remains a separate polish item.
- Watchlist Center loading from historical user state when no current candidates are loaded is not part of this verification. Current Watchlist Center is tied to the loaded candidate set.

## Safety Notes

- No raw captures were modified.
- No JSON/CSV/Markdown user state was intentionally changed by this verification.
- SQLite remains additive and non-authoritative.
- No app behavior was changed in this pass.

## Recommended Next Action

Proceed to Phase 3: Research / Readiness responsiveness audit. Treat broad Qt unittest modules as unsafe unless wrapped by a bounded runner that kills only the spawned test process.

