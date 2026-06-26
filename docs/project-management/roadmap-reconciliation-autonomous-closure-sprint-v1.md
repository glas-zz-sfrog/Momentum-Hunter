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
