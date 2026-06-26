# Roadmap Reconciliation & Autonomous Closure Sprint v1

This sprint reconciles Momentum Hunter's overlapping directive tracks and closes objective, testable backend/workflow gaps while avoiding risky visual redesign work.

## Phase 0 Preflight

Preflight run date: 2026-06-26 Central Time

### Current Branch And Worktree

- Branch: `master`
- Worktree before Phase 0 documentation edits: clean

### Latest Known Commits

| Commit | Message |
| --- | --- |
| `09104c2` | Add SQLite read-only adoption audit |
| `f55e246` | Add SQLite read model reports |
| `e2dee40` | Add SQLite user state mirror |
| `09ba39c` | Add user state backup safety tools |
| `dddbf18` | Complete SQLite evidence backbone audit fixes |
| `114543e` | Add SQLite evidence backbone final report |
| `02a8007` | Add SQLite validation report |
| `2f4855c` | Document SQLite all-safe import workflow |
| `fb6256c` | Add SQLite read-only query helpers |
| `0935f29` | Add SQLite capture index slice |
| `4264a28` | Add SQLite system status slice |
| `0a69c8f` | Add SQLite evidence runs slice |

### SQLite Validation Baseline

- Command: `python -B -m momentum_hunter.sqlite_validation`
- Status: `PASS`
- SQLite schema version: `7`
- Warnings: `0`

Current SQLite row counts:

| Table | Rows |
| --- | ---: |
| `provider_quality_checks` | 3 |
| `opportunity_alerts` | 2 |
| `alert_outcomes` | 2 |
| `minute_bars` | 710 |
| `evidence_runs` | 14 |
| `evidence_metrics` | 378 |
| `system_status_events` | 16 |
| `captures` | 39 |
| `capture_candidates` | 642 |

### SQLite Read-Model Baseline

- Command: `python -B -m momentum_hunter.sqlite_reports --all`
- Candidate Story read model: `OK`
- Evidence read model: `OK`
- Watchlist/Plans read model: `OK`
- System Readiness read model: `PASS`
- File-vs-SQLite comparison: `PASS`
- Shadow compare: `PASS`

### Safe Baseline Tests

Command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_read_models tests.test_sqlite_reports tests.test_sqlite_queries tests.test_sqlite_validation tests.test_sqlite_user_state_store tests.test_user_state_diff tests.test_user_state_safety tests.test_reliability_reports tests.test_market_tape_health tests.test_outcomes
```

Result:

- `44` tests run
- Status: `OK`
- Runtime: about `7.5s`
- No broad Qt/UI tests were run.

One intentionally isolated test fixture produced a warning payload while proving stale/missing SQLite comparison behavior. The test result remained `OK`.

## Current Project State

Momentum Hunter currently has:

- scanner dashboard and scheduled capture foundation
- raw capture immutability and integrity tooling
- review decisions, watchlists, and entry plans stored outside raw captures
- Candidate Story / Timeline improvements
- evidence autopilot, active monitor, alerts, and alert outcome foundations
- system readiness and reliability report foundations
- additive SQLite mirrors for evidence, market data, system status, capture/candidate history, and user-authored state
- SQLite validation, read-model reports, and shadow compare

SQLite is a validated additive analytics mirror, not the runtime source of truth.

## Current Source-Of-Truth Rules

- Raw captures are immutable source-of-truth market observations.
- Review decisions, watchlists, and entry plans are user-authored file state.
- Derived CSV/JSON/Markdown reports remain active file-based outputs.
- SQLite mirrors are additive and read-only for runtime purposes.
- SQLite must not overwrite JSON, CSV, Markdown, raw captures, or user-authored files.

## Current Safety Constraints

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
- remove file-based fallback behavior
- blur engine/UI boundaries

## Known Unresolved Risks

- `momentum_hunter/app.py` remains very large and carries UI/workflow risk.
- Broad Qt unittest modules have a history of hanging and should not be run unattended.
- Some Phase 1B UI/workflow claims require renewed inspection before they can be called fully closed.
- Research Lab and Readiness responsiveness need bounded probes before further claims.
- Candidate Story chart readability may still need Steven inspection.
- Active alert sample size remains very small, so strategy conclusions remain locked.
- SQLite user-state cutover is explicitly not safe yet.

## Sprint Phases

| Phase | Purpose | Expected Output |
| --- | --- | --- |
| 0 | Preflight and sprint report | This document |
| 1 | Directive order and completion ledger | `argus-directive-order-ledger.md` |
| 2 | Close objective Phase 1B workflow gaps | focused fixes/tests or explicit deferrals |
| 3 | Research / Readiness responsiveness audit/repair | bounded load probes and safe fixes |
| 4 | SQLite read-only adoption reconciliation | verify or update completed shadow mode |
| 5 | System Readiness engine reconciliation | verify or improve backend readiness report |
| 6 | Evidence Autopilot reliability reconciliation | verify or improve reliability reports |
| 7 | Active alert evidence collection hardening | safe defensive reliability/reporting work |
| 8 | Test harness reliability | safe unattended-test guidance |
| 9 | `app.py` modularization audit and safe extraction | docs and possible pure-helper extraction |
| 10 | Candidate Story chart polish if safe | small readability fix or deferral |
| 11 | Final validation and report | sprint scoreboard |

## Stop Conditions

Stop and report immediately if:

- raw capture mutation risk appears
- user-authored files could be overwritten
- SQLite would need to become authoritative
- file-vs-SQLite comparison fails in a way suggesting data loss
- scoring/readiness/alert/outcome/trade-planning logic would need to change
- research freeze repair requires a major architecture decision
- UI changes become broad or subjective
- tests reveal a serious data-integrity defect
- a broad architecture decision is required

## Phase 0 Result

Phase 0 is complete. Current backend/storage baseline is green, and the sprint can proceed to the directive ledger.

## Phase 1 Result

Phase 1 is complete.

Output:

- `docs/project-management/argus-directive-order-ledger.md`

Commit:

- `6069844` - Add Argus directive order ledger

Summary:

- Reconciled the major Operator Dashboard, Phase 1B, Candidate Story, reliability, and SQLite directives.
- Classified each directive as complete, partial, in progress, or deferred.
- Captured known commit hashes where available.
- Identified the next objective workflow gaps before any further UI redesign.

## Phase 2 Result

Phase 2 verification is complete without runtime code changes.

Output:

- `docs/project-management/phase-1b-workflow-verification-2026-06-26.md`

Verified isolated probe markers:

- `CHECKBOX_WATCHLIST_PROBE_OK`
- `WHY_SCORE_FORMATTING_PROBE_OK`
- `RESEARCH_LOADER_PROBE_OK`
- `READINESS_LOADER_PROBE_OK`

Finding:

- The app paths passed isolated verification.
- A combined Qt unittest group still stalled after two tests, confirming the known Qt test-harness risk.
- The spawned `python.exe` processes were terminated and a final process check showed no leftover Python processes.

Remaining deferred Phase 1B-adjacent items:

- Pixel-level checkbox misclick testing requires a bounded Qt event harness.
- Active nav styling and midnight-blue active page canvas are Phase 2 visual redesign items.
- Candidate Story chart legend readability remains a focused polish item.
- Watchlist Center behavior when no current candidate set is loaded remains a separate workflow-design question.

Next phase:

- Phase 3: Research / Readiness responsiveness audit.

## Phase 3 Result

Phase 3 is complete without runtime code changes.

Output:

- `docs/project-management/research-readiness-responsiveness-audit-2026-06-26.md`

Measured backend report-builder times:

- `build_capture_study`: `0.014s`
- `build_outcome_maturity_report`: `0.047s`

Measured GUI entry-point return times:

- `open_study_engine`: `0.002s`
- `open_readiness_gate`: `0.001s`

Result:

- Research Lab and Readiness Gate are responsive on current data.
- The combined Qt unittest stall remains a test-harness problem, not a current app-path failure.
- No leftover Python processes were present after the probes.

Next phase:

- Phase 4: reconcile SQLite read-only adoption/shadow mode in the sprint scoreboard.

## Phase 4 Result

Phase 4 is complete.

Purpose:

- Reconcile SQLite Read-Only Adoption / Shadow Mode against the current file-authoritative data.

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_validation
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_reports --shadow-compare
.\.venv\Scripts\python.exe -B -m unittest tests.test_read_models tests.test_sqlite_reports
```

Initial finding:

- SQLite validation: `PASS`
- Focused read-model/report tests: `14` tests, `OK`
- Initial shadow compare: `WARN`
- Mismatch: `watchlist.incomplete_plans` file value `27`, SQLite value `26`

Action taken:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_migration --slice user-state
```

User-state mirror refresh result:

- Review records seen: `17`
- Watchlist records seen: `8`
- Entry plan records seen: `27`
- Entry plan records inserted into SQLite mirror: `1`
- Entry plan records updated in SQLite mirror: `26`
- Warnings: `0`

Final validation:

- SQLite validation: `PASS`
- Shadow compare: `PASS`
- Shadow warnings: `0`

Safety:

- File-authoritative user state was not overwritten.
- Raw captures were not mutated.
- SQLite remains additive/read-only for runtime behavior.
- No code changes were required.

Next phase:

- Phase 5: System Readiness engine reconciliation.

## Phase 5 Result

Phase 5 is complete.

Purpose:

- Ensure System Readiness includes the backend/storage trust signals needed for operator and autonomous evidence work.

Code changes:

- Added `SQLite Mirror` readiness section.
- Added `User-State Safety` readiness section.
- Added focused tests for PASS/WARN behavior for both new sections.

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_reliability_reports
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_validation --slice user-state
.\.venv\Scripts\python.exe -B -m momentum_hunter.system_readiness
```

Results:

- Reliability report tests: `5` tests, `OK`
- User-state diff: `PASS`
- Records in files: `52`
- Records in SQLite: `52`
- Missing in SQLite: `0`
- Extra in SQLite: `0`
- Changed values: `0`
- System Readiness latest report now includes:
  - `SQLite Mirror: READY`
  - `User-State Safety: READY`

Safety:

- System Readiness remains read-only.
- SQLite remains diagnostic/additive.
- File-authoritative user state was not overwritten.
- Raw captures were not mutated.
- No scanner, scoring, readiness, alert, outcome, or trade-planning logic changed.

Next phase:

- Phase 6: Evidence Autopilot reliability reconciliation.

## Phase 6 Result

Phase 6 is complete.

Purpose:

- Ensure Evidence Autopilot reliability reporting distinguishes a completed historical run from a current/active evidence loop.

Code changes:

- Added `latest_run_age_minutes`.
- Added `latest_run_stale`.
- Added `STALE_EVIDENCE_AUTOPILOT_RUN` warning when the latest completed run is older than 24 hours.

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_reliability_reports tests.test_evidence_autopilot
.\.venv\Scripts\python.exe -B -m momentum_hunter.evidence_autopilot_reliability
```

Results:

- Reliability/autopilot tests: `9` tests, `OK`
- Latest reliability report generated:
  - `MomentumHunterData/data/reports/evidence-autopilot-latest.json`
  - `MomentumHunterData/data/reports/evidence-autopilot-latest.md`
- Latest run age: `5131.779` minutes
- Latest run stale: `yes`
- New warning present: `STALE_EVIDENCE_AUTOPILOT_RUN`

Safety:

- Reporting-only change.
- No alert generation changes.
- No scoring changes.
- No readiness rule changes.
- No outcome classification changes.
- No trade-planning changes.

Next phase:

- Phase 7: Active Alert evidence hardening.

## Phase 7 Result

Phase 7 is complete.

Purpose:

- Harden active-alert evidence collection with read-only reliability reporting instead of changing signal logic.

Code changes:

- Added `momentum_hunter/active_alert_reliability.py`.
- Added `python -m momentum_hunter.active_alert_reliability`.
- Added latest report outputs:
  - `MomentumHunterData/data/reports/active-alert-reliability-latest.json`
  - `MomentumHunterData/data/reports/active-alert-reliability-latest.md`
- Added documentation:
  - `docs/alerts/active-alert-reliability-v1.md`

Report checks:

- active monitor status freshness
- latest monitor cycle readability and warnings
- alert counts by completed / pending / unscorable
- duplicate alert IDs
- duplicate symbol/timestamp/type semantic keys
- alert ID stability against the existing stable ID strategy
- missing alert price
- invalid alert timestamps
- missing source report references
- alert outcome updater handoff status
- SQLite `opportunity_alerts` and `alert_outcomes` mirror parity

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_active_alert_reliability
.\.venv\Scripts\python.exe -B -m momentum_hunter.active_alert_reliability
```

Focused test result:

- Active-alert reliability tests: `4` tests, `OK`

Safety:

- Reporting-only change.
- No alert thresholds changed.
- No scoring changes.
- No readiness rule changes.
- No outcome classification changes.
- No trade-planning changes.
- No market data fetching added.
- No raw capture mutation.
- SQLite remains diagnostic/additive.

Next phase:

- Phase 8: Test harness reliability.

## Phase 8 Result

Phase 8 is complete.

Purpose:

- Stop autonomous validation from drifting into broad Qt unittest modules that can hang and leave test `python.exe` processes alive.

Code changes:

- Added `tools/run_bounded_tests.py`.
- Added `docs/testing/test-harness-reliability-v1.md`.

Safe test lanes:

- `backend`
- `storage`
- `evidence`

The bounded runner:

- disables bytecode writes
- runs each module in its own subprocess
- applies a per-module timeout
- reports `PASS`, `FAIL`, or `TIMEOUT`
- excludes known risky broad Qt modules from the safe groups

Do-not-run-unattended modules:

- `tests.test_gui_states`
- `tests.test_daily_workflow`
- `tests.test_morning_review_workspace`
- `tests.test_review_workflow`

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --list
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group evidence --only tests.test_active_alert_reliability --timeout 30
```

Results:

- Safe group listing completed.
- Bounded evidence single-module validation completed: `tests.test_active_alert_reliability` passed.

Safety:

- Test tooling/documentation only.
- No application runtime behavior changed.
- No scanner, scoring, readiness, alert, outcome, trade-planning, SQLite authority, or raw capture behavior changed.

Next phase:

- Phase 9: Documentation and roadmap synthesis.

## Phase 9 Result

Phase 9 is complete.

Purpose:

- Reduce `app.py` risk through a low-risk pure helper extraction instead of broad UI redesign.

Audit:

- Added `docs/architecture/app-modularization-audit-v1.md`.
- Identified low/medium/high-risk extraction candidates.
- Deferred broad UI layout, Research Lab widget builders, Evidence Console layout, and chart rendering work.

Code changes:

- Added `momentum_hunter/score_explanation_view_model.py`.
- Moved score explanation HTML/view-model formatting out of `app.py`.
- Preserved the existing `momentum_hunter.app.format_score_breakdown_html` import path by importing the helper back into `app.py`.
- Reduced `app.py` from roughly `7,714` lines to roughly `7,434` lines.

Tests added:

- `tests/test_score_explanation_view_model.py`

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_score_explanation_view_model tests.test_score_breakdowns
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group backend --only tests.test_score_explanation_view_model --timeout 30
```

Results:

- Score explanation / score breakdown tests passed.
- Bounded safe runner validated the new score explanation module.

Safety:

- Formatting/view-model extraction only.
- No scoring math changed.
- No readiness rules changed.
- No alert thresholds changed.
- No outcome classification changed.
- No trade-planning behavior changed.
- No raw captures or user-authored files were modified.

Next phase:

- Phase 10: Candidate Story chart polish, only if safe.

## Phase 10 Result

Phase 10 is complete.

Purpose:

- Improve Candidate Story chart readability without changing timeline data, scoring, outcomes, capture logic, or charting scope.

Code changes:

- Replaced the tiny legend glyph with readable chip-style labels.
- Improved Price/Score/Capture marker legend contrast.
- Kept direct marker chips for First seen, Peak score, and Latest capture above the chart.
- Increased chart title and axis font readability.
- Strengthened chart plot/background/grid contrast.
- Left Intraday and 5D charting deferred.

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_replay
# Offscreen chart smoke probe: build Candidate Story chart, verify chart widget and legend chips construct, close QApplication cleanly.
```

Results:

- Replay tests passed.
- Candidate Story chart smoke probe passed.
- No leftover test `python.exe` processes remained.

Safety:

- Presentation-only change.
- No scoring math changed.
- No capture logic changed.
- No outcome logic changed.
- No alert/readiness/trade-planning behavior changed.
- No raw captures or user-authored stores were modified.

Next phase:

- Phase 11: Final validation and report.
