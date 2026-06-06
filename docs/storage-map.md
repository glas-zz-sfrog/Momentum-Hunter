# Momentum Hunter Storage Map

Momentum Hunter separates immutable market observations from derived research artifacts. Raw captures are the source of truth; everything else should be rebuilt, edited, or replaced without changing those raw files.

## Raw captures

- Path: `MomentumHunterData/data/captures/YYYY-MM-DD/{morning|evening|manual}.json`
- Path: `MomentumHunterData/data/captures/YYYY-MM-DD/{morning|evening|manual}.md`
- Owner: capture engine
- Mutability: immutable after creation
- Purpose: point-in-time record of what Momentum Hunter knew at capture time
- Integrity: external SHA-256 records in `MomentumHunterData/data/integrity/capture_manifest.json`

Raw capture files must not store later review decisions, outcomes, score recalculations, study summaries, or AI annotations.

New raw captures also exclude user decision fields (`selected`, `reviewed`, `review_status`), user notes, and score-breakdown text such as score reasons. Those belong in separate review/derived stores.

Raw capture files must not be edited to add hashes or metadata after creation. Capture metadata lives outside the raw files.

## Review decisions

- Path: `MomentumHunterData/data/review-decisions.json`
- Owner: candidate review workflow
- Mutability: append/update by candidate identity
- Stores: `review_status`, decision timestamp, optional decision note
- Identity: `capture_id/date/session/provider/scanner/ticker`

Review decisions are user journal records. They reference raw captures but do not modify them.

## Derived outcomes

- Path: `MomentumHunterData/data/analysis-outcomes.csv`
- Owner: outcome updater
- Mutability: rebuildable
- Stores: future return labels, outcome windows, max gain/drawdown

Outcomes are labels computed after capture time. They can use future bars for labeling, but they must not be written back into raw captures.

## Score breakdowns

- Current status: not yet persisted as a dedicated store
- Future path: `MomentumHunterData/data/score-breakdowns.json` or SQLite equivalent
- Owner: scoring engine
- Mutability: rebuildable by engine version
- Stores: score components, rule weights, and “Why this score?” explanations

Score breakdowns must reference raw capture identity and engine version. They must not be written into raw captures.

## Study reports

- Source paths: `MomentumHunterData/data/analysis-captures.csv`, `MomentumHunterData/data/analysis-outcomes.csv`
- UI location: Study Engine dialog
- Mutability: disposable/rebuildable
- Stores: aggregate summaries, score buckets, filtered historical summaries

Study results should be treated as derived views. They are useful research output, not source-of-truth capture data.

Persisted study reports, when added, should live under `MomentumHunterData/data/studies/` and should be safe to delete/rebuild.

## Future optimizer results

- Current status: not implemented
- Future path: `MomentumHunterData/data/optimizer/`
- Mutability: disposable/rebuildable
- Stores: candidate scoring weight experiments and aggregate recommendation output

Optimizer output is always derived research. It must never mutate raw captures.

## Provider raw snapshots

- Current status: not persisted as a dedicated provider snapshot store yet
- Future path: `MomentumHunterData/data/provider-snapshots/{provider}/YYYY-MM-DD/...`
- Mutability: immutable after creation
- Purpose: preserve provider responses separately from normalized candidate captures

When provider snapshots are added, they should be hashed and tracked the same way as raw captures.

## Integrity index

- Path: `MomentumHunterData/data/integrity/capture_manifest.json`
- Owner: capture storage and integrity audit
- Mutability: updated only when a raw capture file is first created
- Purpose: detect raw capture JSON/MD file changes after creation

The manifest is not the source of truth for market data. It is an audit index for raw file integrity.

Each manifest record stores:

- `created_at`
- `capture_time`
- `capture_date`
- `session`
- `provider`
- `scanner`
- `capture_version`
- `hash_algorithm = sha256`
- `source_hash`

## Files That May Be Updated

- `review-decisions.json`: user decisions and notes
- `analysis-captures.csv`: normalized derived analysis rows
- `analysis-outcomes.csv`: future outcome labels
- `watchlist-*.json` and `watchlist-report-*.md`: user-facing derived watchlist artifacts
- `integrity/capture_manifest.json`: external raw capture integrity metadata
- `integrity/raw_capture_integrity_audit.*`: latest audit output
- `backups/derived-rebuild/YYYYMMDD-HHMMSS/`: backed-up derived CSVs before rebuilds

## Integrity Validation

Run:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.integrity_audit
```

The audit:

- verifies manifest raw captures still exist
- verifies SHA-256 hashes
- detects modified raw captures
- detects missing raw captures
- warns about pre-manifest/untracked raw captures
- detects derived CSV/review records that reference missing raw captures or missing tickers
- writes CSV and Markdown reports under `MomentumHunterData/data/integrity/`

Overall statuses:

- `PASS`: all tracked raw captures are present and hash-clean, with no orphaned derived records
- `WARN`: no integrity failures, but legacy raw captures are untracked
- `FAIL`: at least one raw capture is modified/missing, or a derived record points to a missing source capture/ticker

## Recovery From Audit Failures

- `MODIFIED`: do not trade from that snapshot until the original raw file is restored from backup, Git history, OneDrive history, or another machine.
- `MISSING`: restore the missing raw JSON/MD file from backup, or quarantine/delete derived rows that reference it.
- `ORPHANED_DERIVED_RECORD`: rebuild derived CSV/outcome/review data from available raw captures, or remove the derived row if the raw source cannot be recovered.
- `UNTRACKED`: legacy pre-manifest captures can still be viewed, but they cannot be proven immutable from creation time. Future captures will be tracked automatically.

## Rebuilding Derived Data

If `analysis-captures.csv` or `analysis-outcomes.csv` drifts from raw captures, rebuild them from source-of-truth captures:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.rebuild_derived_data
```

The rebuild command:

- writes a before-rebuild audit report
- backs up existing derived CSVs under `MomentumHunterData/data/backups/derived-rebuild/`
- registers legacy untracked raw captures in the external manifest
- rebuilds `analysis-captures.csv` only from raw capture JSON files
- rebuilds `analysis-outcomes.csv` from the rebuilt analysis CSV
- verifies raw capture hashes did not change during the rebuild
- writes an after-rebuild audit report

The backup directory is the quarantine area for old orphaned derived rows. Do not copy old rows back into live analysis files unless they can be traced to a raw capture.
