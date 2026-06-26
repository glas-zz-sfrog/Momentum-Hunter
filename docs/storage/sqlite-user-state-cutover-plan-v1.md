# SQLite User State Cutover Plan v1

Status: design only

Momentum Hunter currently keeps user-authored state in JSON/Markdown files. SQLite mirrors that state additively, but SQLite is not the runtime source of truth. This document defines the future cutover choices and safety gates for candidate reviews, watchlist items, and entry plans.

## Scope

Potential future cutover targets:

- `candidate_reviews`
- `watchlist_items`
- `entry_plans`

Out of scope for this design:

- raw captures
- score calculations
- readiness rules
- alert logic
- outcome classification
- trade-planning logic
- broker/order integration
- UI workflow redesign

## Current Mode: File-Authoritative

Files remain authoritative:

- `MomentumHunterData/data/review-decisions.json`
- `MomentumHunterData/data/watchlist-*.json`
- `MomentumHunterData/data/watchlist-report-*.md`
- `MomentumHunterData/data/entry-plans.json`

SQLite tables are mirrors:

- `candidate_reviews`
- `watchlist_items`
- `entry_plans`

Properties:

- lowest risk
- simple rollback because files are still source of truth
- SQLite can support read-only reports and audits
- runtime write paths remain unchanged

This is the only approved production mode today.

## Option A: File-Authoritative With SQLite Read-Through

The runtime continues writing files, but read-only reporting and selected non-critical views can read from SQLite after validation passes.

Allowed uses:

- summary reports
- analytics queries
- consistency checks
- historical read models

Not allowed:

- editing reviews through SQLite
- editing entry plans through SQLite
- generating watchlist artifacts from SQLite-only state
- deleting or repairing file state from SQLite

Safety gate:

- latest `sqlite_validation` must pass
- latest `sqlite_validation --slice user-state` must pass
- backup and restore validation must pass

This should be the first runtime-adjacent step if any app surface starts reading SQLite.

## Option B: Dual-Write Mode

The runtime writes both file stores and SQLite in one transaction-like workflow.

Design requirement:

1. Write to a temporary backup file or create a pre-write backup.
2. Write file-authoritative JSON first.
3. Import/upsert the matching SQLite mirror row.
4. Run a targeted diff for the affected identity.
5. If SQLite write fails, keep the file write but mark SQLite mirror stale.

Pros:

- preserves file rollback
- exercises SQLite write path before full cutover
- makes stale mirror detection visible

Risks:

- two write targets can drift
- partial failures require clear operator-visible warnings
- code paths become more complex

Required before implementation:

- identity-specific diff helper
- write failure telemetry
- backup-before-write enforcement
- tests for partial failure and retry

## Option C: SQLite-Authoritative With File Export

SQLite becomes runtime source of truth. Files become exports/recovery artifacts.

Properties:

- highest operational simplicity after migration
- strongest query capability
- highest cutover risk

Required guarantees:

- every runtime user-state write goes through a SQLite repository layer
- every write can export file-compatible JSON
- backup and restore are tested
- downgrade plan exists
- UI confirms migration before first SQLite-authoritative run

This mode is not safe to implement yet.

## Option D: One-Way Migration

The system imports current files into SQLite, validates equality, then marks SQLite authoritative.

This is risky because failures after migration require rollback tooling and operator confidence.

If ever used, it must require:

- verified pre-migration backup
- PASS user-state diff
- signed migration note
- explicit user confirmation
- post-migration file export
- rollback command tested against the backup

## Source-Of-Truth Transition Rules

No source-of-truth transition may occur unless all are true:

1. A fresh user-state backup exists.
2. Restore validation into a temporary directory returns `PASS`.
3. `python -m momentum_hunter.sqlite_validation --slice user-state` returns `PASS`.
4. No missing, extra, changed, malformed, or stale user-state rows exist.
5. Runtime write-path tests cover review, watchlist, and entry-plan writes.
6. A rollback command has been tested against the backup.
7. File export from SQLite has been tested and compared to original files.
8. The UI clearly tells the operator which storage mode is active.
9. A signed migration note records date, reason, operator approval, and rollback path.

## Backup-Before-Write Requirement

Before any SQLite-authoritative or dual-write user-state mutation:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.user_state_safety backup
```

The backup must include:

- review decisions
- watchlist files
- entry plans
- manifest
- SHA-256 hashes
- app/schema version

If backup fails, no cutover write may run.

## Restore Strategy

Restore must not overwrite live files by default.

Safe restore sequence:

1. Validate backup into a temporary directory.
2. Show manifest, file counts, and hashes.
3. Require explicit confirmation to replace live user-state files.
4. Move current live files into a rollback quarantine folder.
5. Restore backup files.
6. Re-run SQLite import from restored files.
7. Run user-state diff.

Default restore command should be validation-only until a deliberate restore command is implemented.

## Conflict Handling

Conflicts are reported, not auto-resolved.

Conflict types:

- duplicate review identity
- same capture/ticker with different status
- watchlist item in file but not SQLite
- SQLite row missing from file
- changed entry-plan fields
- malformed source record
- missing timestamp
- stale SQLite source hash
- incomplete plan

Resolution precedence in current mode:

1. File value wins.
2. SQLite row is treated as stale.
3. Operator can re-import files to refresh SQLite.
4. No automatic delete from files or SQLite without explicit cleanup command.

## Stale SQLite Mirror Detection

Stale mirror signals:

- source hash mismatch
- file row missing in SQLite
- SQLite row extra compared with file
- changed mirrored value
- import timestamp older than file modified time
- malformed records skipped during import

Detection command:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_validation --slice user-state
```

The report must show:

- missing rows
- extra rows
- changed fields
- conflicts
- warnings
- recommended next action

## User Confirmation Requirements

Any future cutover UI or CLI must clearly show:

- current storage mode
- backup path
- restore validation result
- user-state diff result
- number of rows affected
- rollback path
- files that will stop being authoritative, if any

Confirmation text must distinguish:

- read-only SQLite reporting
- dual-write pilot
- SQLite-authoritative cutover

## CLI Recovery Commands

Existing safe commands:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.user_state_safety backup
.\.venv\Scripts\python.exe -m momentum_hunter.user_state_safety validate-restore MomentumHunterData\backups\user-state\YYYYMMDDHHMMSS
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_migration --slice user-state
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_validation --slice user-state
```

Future commands needed before cutover:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.user_state_restore --from-backup MomentumHunterData\backups\user-state\YYYYMMDDHHMMSS --dry-run
.\.venv\Scripts\python.exe -m momentum_hunter.user_state_restore --from-backup MomentumHunterData\backups\user-state\YYYYMMDDHHMMSS --apply
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_user_state_export --output MomentumHunterData\data\exports\user-state\
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_user_state_cutover --mode dual-write --confirm
```

## Test Requirements

Before dual-write:

- write review decision to file and SQLite mirror
- write entry plan to file and SQLite mirror
- generate watchlist file and SQLite mirror row
- partial SQLite failure leaves file valid and warns
- partial file failure prevents SQLite write
- user-state diff catches stale mirror after manual file edit
- source files remain recoverable from backup

Before SQLite-authoritative mode:

- import current files to SQLite
- export SQLite back to file-compatible JSON
- byte-for-byte or semantic comparison of exported state
- restore from backup
- rollback from SQLite-authoritative to file-authoritative
- UI mode display
- operator confirmation flow

## Cutover Status

SQLite user-state cutover is not safe to implement yet.

Reason:

- no dual-write repository layer exists
- no restore-over-live command exists
- no SQLite-to-file export command exists
- UI does not display storage mode
- rollback from SQLite-authoritative mode has not been tested

Recommended next step:

Build read-only SQLite reports first. Then design a dual-write repository layer with backup-before-write and identity-specific diff checks.

