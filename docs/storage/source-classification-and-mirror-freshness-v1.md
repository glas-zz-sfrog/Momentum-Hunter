# Source Classification and Mirror Freshness v1

Date: 2026-06-26

## Purpose

Momentum Hunter remains file-first. SQLite is an additive mirror for offline analysis, report generation, and future read-model testing. This document defines the current source classes, the SQLite mirror freshness checks, and the cleanup rules that prevent silently rewriting history or user-authored state.

## Source Classes

| Class | Meaning | Mutation Policy |
| --- | --- | --- |
| Raw capture | Original point-in-time scan files under `MomentumHunterData/data/captures/` | Immutable. Never rewrite in place. Restore or quarantine on failure. |
| Derived analysis index | Rebuildable CSV/index files such as `analysis-captures.csv` | Rebuild only from trusted raw captures. Not raw history. |
| Derived evidence store | Alert, outcome, minute-bar, evidence, and readiness reports | May mature or regenerate. Preserve source files and mirror separately. |
| User state | Review decisions and entry plans | User-authored. Back up before cutover or recovery. Never overwrite silently. |
| User artifact | Watchlists and reports | Preserve as generated user artifacts. Mirror only in explicit user-state workflows. |
| Integrity metadata | Capture manifests and quarantine metadata | Store outside raw captures. Never use to silently re-bless modified captures. |
| SQLite mirror | Additive database at `MomentumHunterData/data/momentum-hunter.sqlite3` | Derived mirror only. Not authoritative yet. |

## Registry

Source definitions live in:

```text
momentum_hunter/source_registry.py
```

The registry records:

- source name
- category
- authority
- mutability
- path/pattern
- mirrored SQLite tables
- importer
- whether it is included in `all-safe`
- preservation rule
- cleanup rule

## Mirrored Tables

| SQLite table | File source | Importer | Included in `all-safe` |
| --- | --- | --- | --- |
| `provider_quality_checks` | `reports/data-quality-latest.json` | `import_provider_quality_report` | Yes |
| `opportunity_alerts` | `opportunity-alerts.json` | `import_opportunity_alerts` | Yes |
| `alert_outcomes` | `opportunity-alerts.json` | `import_opportunity_alerts` | Yes |
| `minute_bars` | `opportunity-minute-bars.json` | `import_minute_bars` | Yes |
| `evidence_runs` | Evidence/report JSON files | `import_evidence_runs` | Yes |
| `evidence_metrics` | Evidence/report JSON files | `import_evidence_runs` | Yes |
| `system_status_events` | Active monitor, autopilot, outcome, readiness, data-quality, market-tape reports | `import_system_status_events` | Yes |
| `captures` | `analysis-captures.csv` plus raw capture file references | `import_capture_candidate_index` | Yes |
| `capture_candidates` | `analysis-captures.csv` | `import_capture_candidate_index` | Yes |
| `candidate_reviews` | `review-decisions.json` | `import_user_state` | No |
| `watchlist_items` | `watchlist-*.json` | `import_user_state` | No |
| `entry_plans` | `entry-plans.json` | `import_user_state` | No |

## Mirror Freshness Report

Command:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_mirror_freshness
```

Outputs:

```text
MomentumHunterData/data/reports/sqlite-mirror-freshness-latest.json
MomentumHunterData/data/reports/sqlite-mirror-freshness-latest.md
```

The report compares:

- current source file hashes
- source row/event counts
- SQLite rows with matching source path and hash
- total SQLite table rows
- latest source modification timestamp
- latest SQLite import timestamp

## Status Rules

| Status | Meaning |
| --- | --- |
| `PASS` | Current file source rows match SQLite rows for the current source hash. |
| `WARN` | Source is missing or unreadable but not clearly stale/failing. |
| `FAIL` | An `all-safe` mirror table does not match the current source hash/count. |
| `INFO` | A non-`all-safe` user-state mirror needs explicit import/cutover workflow. |

Overall status is:

- `FAIL` if any `all-safe` table fails freshness.
- `WARN` if warnings exist without failures.
- `PASS` if all required mirrors match current sources.

## Cleanup And Preservation Rules

Raw captures:

- Do not modify raw capture JSON/MD files.
- If raw capture integrity fails, restore the original if available.
- If restore is unavailable, quarantine with a recovery note.
- Never re-baseline silently.

Derived analysis:

- `analysis-captures.csv` may be rebuilt from trusted raw captures.
- SQLite mirror rows may be refreshed from current derived sources.
- Stale mirror rows for latest-style report sources may be removed by importers when the source file regenerates with a new identity.

User state:

- `review-decisions.json`, `entry-plans.json`, and `watchlist-*.json` remain file-authoritative.
- User-state SQLite import is not part of `all-safe`.
- User-state migration requires backup, diff, and cutover simulation first.

Reports:

- Latest reports may regenerate.
- Timestamped reports should be preserved where generated.
- Report mirrors are diagnostic and additive.

## Current Milestone 1 Validation

During Offline Platform Maturity Sprint v1, the new mirror freshness report initially detected stale `system_status_events` rows after fresh preflight reports were generated.

Resolution:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_migration --slice all-safe
.\.venv\Scripts\python.exe -B -m momentum_hunter.sqlite_mirror_freshness
```

Final result:

```text
Overall status: PASS
Warnings: 0
```

This confirms the freshness report can detect stale mirrors and that `all-safe` refresh restores parity without mutating raw captures or user-authored state.
