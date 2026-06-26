# SQLite User State Safety Cage v1 Final Report

Generated: 2026-06-25

## Goal

Prepare for future SQLite migration of user-authored state by adding audit documentation, backup, restore validation, conflict rules, additive SQLite mirror import, dry-run diff validation, and read-only query helpers.

SQLite remains additive only. File-based review, watchlist, and entry-plan stores remain authoritative.

## Commits Created

- `09ba39c Add user state backup safety tools`
- Final implementation commit: see Git history and completion handoff for the immutable hash

## Schema Version

- Before: `6`
- After: `7`

## Authoritative Files Discovered

- `MomentumHunterData/data/review-decisions.json`
- `MomentumHunterData/data/entry-plans.json`
- `MomentumHunterData/data/watchlist-2026-06-04.json`
- `MomentumHunterData/data/watchlist-2026-06-18.json`
- `MomentumHunterData/data/watchlist-report-2026-06-04.md`
- `MomentumHunterData/data/watchlist-report-2026-06-18.md`

Optional `MomentumHunterData/data/opportunity-monitor-symbols.json` was not present during backup and was reported as an optional missing file.

## Backup Package

- Backup path: `MomentumHunterData/backups/user-state/20260625213601`
- Backup report JSON: `MomentumHunterData/data/reports/user-state-backup-latest.json`
- Backup report Markdown: `MomentumHunterData/data/reports/user-state-backup-latest.md`
- Files included: 6
- Files considered: 7
- Required files missing: 0
- Optional files missing: 1

## Restore Validation

- Restore validation result: `PASS`
- Validation directory: `MomentumHunterData/backups/user-state/20260625213601/restore-validation`
- Files restored: 6
- Files checked: 7
- Missing files: 0
- Hash mismatches: 0
- Report JSON: `MomentumHunterData/data/reports/user-state-restore-validation-latest.json`
- Report Markdown: `MomentumHunterData/data/reports/user-state-restore-validation-latest.md`

## SQLite Mirror Import

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_migration --slice user-state
```

Report files:

- `MomentumHunterData/data/reports/sqlite-user-state-import-latest.json`
- `MomentumHunterData/data/reports/sqlite-user-state-import-latest.md`

Latest live import counts:

- Review records seen: 17
- Review records inserted: 0
- Review records updated: 0
- Review records skipped: 17
- Watchlist files seen: 2
- Watchlist records seen: 8
- Watchlist records inserted: 0
- Watchlist records updated: 0
- Watchlist records skipped: 8
- Entry-plan records seen: 26
- Entry-plan records inserted: 0
- Entry-plan records updated: 0
- Entry-plan records skipped: 26
- Complete entry plans: 0
- Incomplete entry plans: 26
- Warnings: none

The skipped counts prove the live import was idempotent after the initial import.

## Dry-Run Diff Validation

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_validation --slice user-state
```

Report files:

- `MomentumHunterData/data/reports/sqlite-user-state-diff-latest.json`
- `MomentumHunterData/data/reports/sqlite-user-state-diff-latest.md`

Latest live diff result:

- Overall status: `PASS`
- Records in files: 51
- Records in SQLite: 51
- Missing in SQLite: 0
- Extra in SQLite: 0
- Changed values: 0
- Conflicts: 0
- Malformed records: 0
- Stale imports: 0
- Warnings: none

## Mirrored In SQLite

- `candidate_reviews`
- `watchlist_items`
- `entry_plans`

Each mirror stores source path, source hash, source JSON where useful, and import timestamps.

## Still File-Authoritative

- `MomentumHunterData/data/review-decisions.json`
- `MomentumHunterData/data/entry-plans.json`
- `MomentumHunterData/data/watchlist-*.json`
- `MomentumHunterData/data/watchlist-report-*.md`

SQLite is not wired into runtime review, watchlist, entry-plan, or UI write paths.

## Tests Added

- `tests/test_user_state_safety.py`
- `tests/test_sqlite_user_state_store.py`
- `tests/test_user_state_diff.py`
- additions to `tests/test_sqlite_queries.py`

## Exact Tests Run

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_user_state_safety tests.test_sqlite_user_state_store tests.test_user_state_diff tests.test_sqlite_queries
```

Result: 17 tests passed.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_sqlite_store tests.test_sqlite_capture_index_store tests.test_sqlite_system_status_store tests.test_sqlite_validation tests.test_sqlite_user_state_store tests.test_user_state_diff tests.test_sqlite_queries
```

Result: 32 tests passed.

## Safety Notes

- Raw captures were not modified.
- Review/watchlist/entry-plan JSON files were not overwritten by SQLite.
- The restore command validates backups into a temporary validation directory only.
- The user-state diff is dry-run/report-only and does not repair data.
- The SQLite mirror remains additive; file-based behavior remains unchanged.

## Before SQLite Can Become Source Of Truth

1. Backup and restore validation must pass immediately before cutover.
2. Dry-run diff must report no unresolved conflicts.
3. A rollback plan must be tested.
4. UI confirmation must exist for any write-path migration.
5. A dual-write or one-way cutover strategy must be explicitly selected.
6. File export/recovery behavior must remain available.
7. A signed migration note must document which files stop being authoritative.

## Recommended Next Step

Design-only cutover plan for user-authored state, including rollback, UI confirmation, and one-way/dual-write strategy.
