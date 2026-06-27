# User-State Disaster Recovery and Cutover Simulation v1

Date: 2026-06-26

## Purpose

Momentum Hunter user state is valuable. Review decisions, watchlists, and entry plans represent Steven's trading judgment and workflow history. Before SQLite can become authoritative for any user-state area, Momentum Hunter must prove backup, restore, diff, rollback, and conflict detection behavior with synthetic data.

This milestone adds a simulation harness only. It does not cut over to SQLite and does not mutate production user-state files.

## User-State Sources

| Source | Role | Current authority |
| --- | --- | --- |
| `MomentumHunterData/data/review-decisions.json` | Review status, delayed review metadata, notes | File authoritative |
| `MomentumHunterData/data/entry-plans.json` | Entry plans, plan completeness, thesis/risk notes | File authoritative |
| `MomentumHunterData/data/watchlist-*.json` | Generated/user watchlist artifacts | File authoritative artifact |
| SQLite user-state tables | Additive mirror/safety cage | Not authoritative |

SQLite tables involved:

- `candidate_reviews`
- `watchlist_items`
- `entry_plans`

## Command

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.user_state_cutover_simulation
```

Outputs:

```text
MomentumHunterData/data/reports/user-state-cutover-simulation-latest.json
MomentumHunterData/data/reports/user-state-cutover-simulation-latest.md
```

## Simulation Scenarios

| Scenario | Purpose |
| --- | --- |
| Clean import | Prove source files and SQLite mirror match after import. |
| Missing watchlist row | Prove a missing SQLite mirror row is detected. |
| Stale entry plan | Prove file changes after import are detected as stale SQLite mirror values. |
| Duplicate review | Prove duplicate review identity warnings are surfaced. |
| Conflicting interested/rejected | Prove conflicting statuses for the same candidate identity are detected. |
| Malformed entry plan | Prove malformed entry-plan records are warned and skipped. |
| Incomplete entry plan | Prove incomplete plans remain visible before cutover. |
| Backup restore validation failure | Prove a broken backup is caught before restore. |
| Rollback simulation | Prove backup contents can restore into a safe target directory. |
| Source files unchanged | Prove import/diff simulation does not mutate source JSON files. |

## Safety Rules

- Synthetic fixtures are used.
- Production `review-decisions.json` is not touched.
- Production `entry-plans.json` is not touched.
- Production `watchlist-*.json` files are not touched.
- Production evidence stores are not populated with synthetic data.
- SQLite remains an additive mirror.
- File-based user state remains authoritative.

## Cutover Gate

SQLite user-state cutover should remain blocked until all of the following are true:

1. A live user-state backup exists.
2. Restore validation passes.
3. User-state diff passes or known differences are explicitly accepted.
4. The cutover simulation passes.
5. Rollback procedure is documented and tested.
6. Steven approves the cutover.

## Current Milestone 2 Validation

Expected test command:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_user_state_cutover_simulation tests.test_user_state_safety tests.test_user_state_diff tests.test_sqlite_user_state_store
```

Expected CLI command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.user_state_cutover_simulation
```

The simulation should report:

```text
Overall status: PASS
Scenarios: 10
Failed scenarios: 0
```

## Deferred

- Actual user-state cutover.
- SQLite becoming authoritative for review decisions.
- SQLite becoming authoritative for entry plans.
- SQLite becoming authoritative for watchlists.
- Any UI changes that depend on SQLite user-state authority.
