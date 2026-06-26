# SQLite Read Model & Cutover Design v1 Final Report

Momentum Hunter remains file-authoritative. This milestone added read-only SQLite report surfaces and a design-only cutover plan for future user-authored state migration. It did not change runtime source-of-truth behavior.

## Scope Completed

- Added a design-only user-state cutover plan for `candidate_reviews`, `watchlist_items`, and `entry_plans`.
- Added read-only SQLite report generation for Candidate Story, Evidence, Watchlist/Plans, System Readiness, and file-vs-SQLite comparison.
- Added CLI support through `python -m momentum_hunter.sqlite_reports`.
- Added focused non-Qt tests for read models, CLI output, JSON/Markdown generation, source-file non-mutation, matching comparison counts, mismatch reporting, and missing-database behavior.
- Updated README, changelog, and storage map documentation.

## Runtime Safety

This milestone did not:

- make SQLite authoritative
- mutate raw captures
- overwrite review decisions, watchlists, or entry plans
- change scanner logic
- change scoring math
- change readiness rules
- change alert generation
- change outcome classification
- change trade-planning rules
- change UI workflows

## Reports Created

The live CLI generated:

```text
MomentumHunterData/data/reports/sqlite-candidate-story-read-model-latest.json
MomentumHunterData/data/reports/sqlite-candidate-story-read-model-latest.md
MomentumHunterData/data/reports/sqlite-evidence-read-model-latest.json
MomentumHunterData/data/reports/sqlite-evidence-read-model-latest.md
MomentumHunterData/data/reports/sqlite-watchlist-read-model-latest.json
MomentumHunterData/data/reports/sqlite-watchlist-read-model-latest.md
MomentumHunterData/data/reports/sqlite-system-readiness-read-model-latest.json
MomentumHunterData/data/reports/sqlite-system-readiness-read-model-latest.md
MomentumHunterData/data/reports/sqlite-read-model-comparison-latest.json
MomentumHunterData/data/reports/sqlite-read-model-comparison-latest.md
```

## Live Report Summary

| Report | Status | Key Result |
| --- | --- | --- |
| Candidate Story | OK | 197 candidate stories |
| Evidence | OK | 2 alerts, 1 completed outcome, 0 pending outcomes, 1 unscorable outcome, 710 minute bars |
| Watchlist/Plans | OK | 17 mirrored review-watchlist decisions, 8 watchlist artifacts, 0 complete plans, 26 incomplete plans |
| System Readiness | PASS | SQLite validation status PASS, no missing slices |
| Comparison | PASS | 13 matching count checks, 0 mismatches, 0 unavailable comparisons |

## File-vs-SQLite Match Status

The read-model comparison passed against the current file-authoritative sources.

- Matching counts: 13
- Mismatches: 0
- Unavailable comparisons: 0
- Warnings: 0

## User-State Cutover Status

User-state cutover is not safe to implement yet. SQLite mirrors are additive and read-only for operational purposes.

Cutover remains blocked until these are implemented and tested:

- explicit storage-mode selection
- backup-before-write enforcement
- restore-over-live workflow
- stale-mirror detection in runtime flows
- conflict-resolution UI or CLI
- SQLite-to-file export/recovery
- dual-write validation if chosen
- user confirmation before any source-of-truth transition

## Validation

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_sqlite_reports tests.test_sqlite_queries tests.test_sqlite_validation tests.test_sqlite_user_state_store tests.test_user_state_diff tests.test_user_state_safety
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_reports --all
```

Results:

- Syntax check: PASS
- Focused tests: PASS, 27 tests
- Live read-model CLI: PASS, all five report pairs generated
- Process check: PASS, no leftover Python test processes

## Recommended Next Task

Keep SQLite in additive read-model mode. The next safe storage milestone is a read-only UI/report consumer audit: identify which existing operator/research screens can eventually read from SQLite without changing write paths, and define the exact fallback behavior when SQLite is stale or unavailable.
