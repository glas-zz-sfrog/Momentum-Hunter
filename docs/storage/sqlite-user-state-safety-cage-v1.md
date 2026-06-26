# SQLite User State Safety Cage v1

Status: implementation in progress

Momentum Hunter remains file-first. This safety cage prepares for a future migration of user-authored state by adding audit, backup, restore validation, conflict detection, dry-run import, mirror validation, and rollback planning before any source-of-truth cutover.

## Preflight

- Worktree before implementation: clean
- SQLite schema before this program: `6`
- Latest SQLite evidence validation before this program: `PASS`
- Latest evidence backbone commit: `dddbf18 Complete SQLite evidence backbone audit fixes`

## Hard Boundary

This program must not:

- make SQLite the runtime source of truth
- overwrite user-authored JSON/Markdown files
- mutate raw captures
- change scoring math
- change readiness rules
- change alert logic
- change outcome-classification logic
- change trade-planning rules
- change UI workflows
- alter existing review/watchlist/entry-plan behavior

SQLite user-state tables are additive mirrors only.

## Authoritative User-State Files

| State | Source path | Owner module/functions | Authoritative? | User-authored? |
| --- | --- | --- | --- | --- |
| Candidate reviews | `MomentumHunterData/data/review-decisions.json` | `momentum_hunter.review.load_review_decisions`, `save_review_decisions`, `upsert_review_decision` | Yes | Yes |
| Entry plans | `MomentumHunterData/data/entry-plans.json` | `momentum_hunter.entry_plans.load_entry_plans`, `save_entry_plans`, `upsert_entry_plan` | Yes | Yes |
| Saved watchlists | `MomentumHunterData/data/watchlist-YYYY-MM-DD.json` | `momentum_hunter.storage.save_watchlist`, `load_watchlist`, `load_latest_watchlist` | Yes as user workflow artifacts | Yes/derived from user-selected candidates |
| Watchlist reports | `MomentumHunterData/data/watchlist-report-YYYY-MM-DD.md` | `momentum_hunter.storage.save_watchlist_report`, `load_latest_report` | No, derived display/report artifact | No |
| User monitor symbols | `MomentumHunterData/data/opportunity-monitor-symbols.json` | `momentum_hunter.monitor_targets.load_user_defined_symbols`, `save_user_defined_symbols`, `upsert_user_defined_symbol`, `remove_user_defined_symbol` | Yes when present | Yes |

Related runtime/evidence state such as `opportunity-monitor-state.json`, `active-monitor-status.json`, alert reports, and trade-planning reports is derived runtime state, not user-authored review/watchlist/entry-plan state. It is not part of the SQLite user-state source-of-truth migration.

## Candidate Review Fields

Stored under `review-decisions.json`:

- `identity.capture_id`
- `identity.capture_date`
- `identity.session`
- `identity.provider`
- `identity.scanner`
- `identity.ticker`
- `review_status`
- `decision_timestamp`
- `decision_note`
- `delayed_review`
- `review_delay_minutes`
- `review_context_state`
- `capture_status`
- `capture_quarantined_at`
- `capture_quarantine_reason`

Review status meanings:

- `unreviewed`: candidate has no actionable operator decision
- `interested`: candidate should remain under human observation
- `rejected`: candidate was reviewed and dismissed
- `watchlist`: candidate is staged for next-session watchlist/report/entry planning

User-authored values: review status, decision note, decision timestamp context, delayed-review metadata, quarantine annotation tied to decisions.

Derived values: candidate identity and capture metadata are context keys from the capture/review workflow.

Natural key: `identity.key = capture_id|capture_date|session|provider|scanner|ticker` with pipe escaping inside individual parts.

## Entry Plan Fields

Stored under `entry-plans.json`:

- `identity.*`
- `trigger`
- `stop`
- `thesis`
- `invalidation`
- `max_loss`
- `position_size`
- `planned_hold_time`
- `notes`
- `plan_complete`
- `updated_at`
- `warnings`

Completeness rules:

- missing `trigger` -> incomplete
- missing `stop` -> incomplete
- missing `invalidation` -> incomplete
- missing `max_loss` -> incomplete

User-authored values: trigger, stop, thesis, invalidation, max loss, size idea, planned hold time, notes, plan-complete intent.

Derived values: warnings and forced incomplete status when required fields are missing.

Natural key: same candidate identity key as reviews.

## Watchlist Fields

Saved watchlist JSON stores serialized `Candidate` records from selected/watchlist candidates. It includes market/scanner context, news, score, user notes, and candidate fields. Watchlist files are user workflow artifacts and remain file-authoritative.

Natural key for SQLite mirror: `watchlist_date + ticker + source file path` with optional capture identity if available. Current watchlist JSON does not reliably include the originating review identity, so SQLite import must preserve the raw source JSON and avoid claiming stronger identity than exists in the file.

## Backup Safety Model

Backup command:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.user_state_safety backup
```

Backup output:

- `MomentumHunterData/backups/user-state/YYYYMMDDHHMMSS/manifest.json`
- copied files under the backup directory using relative paths such as `data/review-decisions.json`
- latest report JSON/Markdown under `MomentumHunterData/data/reports/user-state-backup-latest.*`

The manifest records:

- source path
- backup relative path
- category
- required/optional
- authoritative flag
- user-authored flag
- file size
- SHA-256 hash
- backup timestamp
- SQLite schema version when supplied

Backup must never mutate source files.

## Restore Validation Model

Restore validation command:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.user_state_safety validate-restore MomentumHunterData\backups\user-state\YYYYMMDDHHMMSS
```

Restore validation copies backup files into a temporary validation directory only. It must not restore over live files.

Validation checks:

- manifest exists
- backup file count can be read
- every manifest file that existed at backup time exists in backup
- copied validation files preserve SHA-256 hashes
- missing optional files are reported but do not invalidate existing backups
- hash mismatches fail validation

Latest reports:

- `MomentumHunterData/data/reports/user-state-restore-validation-latest.json`
- `MomentumHunterData/data/reports/user-state-restore-validation-latest.md`

## Conflict Model

File-based state remains authoritative. SQLite mirrors must report conflicts and never auto-resolve them.

Rules:

- Duplicate candidate review records with the same identity key: report duplicate/malformed source warning; first valid loader result is authoritative for import.
- Same symbol with different review statuses across different captures: not a conflict; the capture identity separates decisions.
- Same symbol with different review statuses for the same capture identity: conflict; report `DUPLICATE_REVIEW_IDENTITY`.
- Watchlist item exists in file but not SQLite: dry-run diff reports `MISSING_IN_SQLITE`.
- SQLite mirror has a row not present in files: dry-run diff reports `EXTRA_IN_SQLITE`; do not delete it automatically.
- SQLite row differs from file row: dry-run diff reports `CHANGED_VALUE`; file value is authoritative.
- Entry plan edited after last import: dry-run diff reports `STALE_SQLITE_IMPORT` and changed fields.
- Missing timestamps: import with warning and preserve record where identity is valid; do not invent user decisions.
- Malformed files or records: skip malformed records with warnings; do not rewrite source.
- Incomplete entry plans: preserve as incomplete; do not fill missing fields.
- Deleted/removed watchlist items: report as `EXTRA_IN_SQLITE` until an explicit cleanup/cutover policy exists.
- Status precedence: no precedence is applied in v1; file status wins for a specific identity.

## Migration Risks

| Risk | Mitigation |
| --- | --- |
| User decisions overwritten | No reverse sync from SQLite to files in this program. |
| Entry-plan string fields lost through numeric coercion | Preserve raw JSON and string stop/trigger fields in SQLite mirror. |
| Watchlist files lack capture identity | Use conservative watchlist identity and preserve source JSON. |
| Duplicate historical decisions by symbol look like conflicts | Treat capture identity as part of the key. |
| Stale SQLite rows look authoritative | Diff report labels missing/extra/changed rows; files remain authoritative. |
| Backup cannot be restored | Restore validation must pass before any future cutover planning. |

## Future Cutover Requirements

SQLite cannot become authoritative for user state until all are true:

1. Backup and restore validation pass on real data.
2. Dry-run diff reports no unresolved conflicts.
3. A rollback plan exists and is tested.
4. UI confirmation exists for any write-path migration.
5. Dual-write or one-way cutover strategy is explicitly selected.
6. File exports remain available after cutover.
7. A signed migration note documents exactly which files become non-authoritative.
