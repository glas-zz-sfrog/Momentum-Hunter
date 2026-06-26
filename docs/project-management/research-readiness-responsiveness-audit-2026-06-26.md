# Research / Readiness Responsiveness Audit

Date: 2026-06-26

Scope: verify that Research Lab and Readiness Gate do not block the operator workflow.

This audit did not change scanner logic, scoring math, readiness rules, alert logic, outcome classification, trade-planning rules, SQLite authority, raw captures, or UI behavior.

## Result

Status: PASS

Research Lab and Readiness Gate both return control to the GUI immediately and complete via the background report-loader path on current data.

## Backend Report Builder Timing

Measured with bytecode disabled:

```text
build_capture_study: 0.014s -> StudySummary
build_outcome_maturity_report: 0.047s -> OutcomeMaturityReport
REPORT_BUILDER_TIMING_OK
```

Interpretation:

- Current backend report construction is not a bottleneck.
- If future freezes occur, likely causes are heavier research panels, modal UI rendering, or combined Qt test harness behavior rather than the current report builders.

## GUI Loader Timing

Measured with final modal dialogs patched out so the probe can observe loader return time without opening blocking windows:

```text
GUI_RESEARCH_RETURN=0.002s
GUI_READINESS_RETURN=0.001s
GUI_RESEARCH_READINESS_TIMING_OK
```

Interpretation:

- `open_study_engine()` returns quickly.
- `open_readiness_gate()` returns quickly.
- Both paths use `_run_report_loader` and do not synchronously block the dashboard entry point.

## Process Hygiene

Final process check:

```text
No leftover python.exe or pythonw.exe processes.
```

## Test-Harness Note

The Phase 1B combined Qt unittest group remains unsafe as a proof mechanism because it stalled after two tests in the previous verification pass. The Research and Readiness app paths passed isolated probes.

Recommendation:

- Continue using isolated Qt probes with explicit success markers.
- Avoid broad Qt unittest modules until a bounded Qt test runner exists.

## Open Risks

- Future heavy Research Lab panels can still become slow if new analytics are added directly to initial dialog construction.
- The current audit proves responsiveness on current data volume, not under a much larger multi-year dataset.
- Modal dialog rendering was intentionally patched out for the GUI return-time probe, so visual layout/rendering should still be inspected manually when UI changes are made.

## Recommended Next Action

Proceed to Phase 4: reconcile SQLite read-only adoption/shadow mode in the sprint scoreboard. No code repair is required for Research/Readiness responsiveness at this time.

