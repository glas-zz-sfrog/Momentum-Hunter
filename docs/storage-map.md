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

- Path: `MomentumHunterData/data/score-breakdowns.json`
- Owner: scoring engine
- Mutability: rebuildable by engine version
- Stores arithmetic reconciliation, caps, floors, bonuses, penalties, component raw inputs, and GUI `Why [score]?` explanations

Score breakdowns reference raw capture identity and score engine version. They must not be written into raw captures.

Current schema:

- `schema_version`
- `updated_at`
- `score_engine_version`
- `records`
- each record includes `capture_id`, `capture_date`, `capture_time`, `session`, `provider`, `scanner`, `ticker`, `score_engine_version`, `score_profile`, `score_regime`, `final_score`, `computed_final_score`, `components`, `bonuses`, `penalties`, `caps`, `floors`, `overrides`, and `reconciliation_status`

Historical records that cannot be fully reconstructed are marked `legacy` or `incomplete`; they are warnings, not clean current-engine proof. This is the foundation for future Replay Mode because the app can show what score explanation was available for a specific capture without changing the raw capture.

## Study reports

- Source paths: `MomentumHunterData/data/analysis-captures.csv`, `MomentumHunterData/data/analysis-outcomes.csv`
- UI location: Study Engine dialog
- Mutability: disposable/rebuildable
- Stores: aggregate summaries, score buckets, filtered historical summaries

Study results should be treated as derived views. They are useful research output, not source-of-truth capture data.

Persisted study reports, when added, should live under `MomentumHunterData/data/studies/` and should be safe to delete/rebuild.

## Candidate Timeline and Replay Mode

- UI entry: select a candidate and click `View Timeline`
- Data layer: `momentum_hunter/replay.py`
- Source inputs: active raw captures, `score-breakdowns.json`, `review-decisions.json`, and `analysis-outcomes.csv`
- Mutability: read-only view model; no replay operation modifies raw captures or derived stores

Replay Mode classifies fields by source:

- `raw capture`: point-in-time market/candidate facts known at capture time
- `derived score explanation`: stored `Why [score]?` record tied to capture identity, ticker, and score engine version
- `later review decision`: user decision and notes recorded after capture
- `later outcome label`: post-capture performance labels from outcomes CSV

Outcome values are always labeled as calculated after capture. Replay views must not present outcomes as information known at the replayed moment.

Quarantined captures are excluded from timelines by default. If `Show quarantined captures` is enabled, replay rows are marked `Quarantined - Not Trusted for Study Use` and remain read-only. Quarantined captures are not re-added to active analysis CSVs or study results.

Timeline/replay warnings include duplicate replay identities, missing score breakdowns, legacy/incomplete score breakdowns, missing outcome labels, and quarantined source references. Missing optional derived data is shown honestly instead of invented.

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
- `score-breakdowns.json`: rebuildable score explanation records
- `watchlist-*.json` and `watchlist-report-*.md`: user-facing derived watchlist artifacts
- `integrity/capture_manifest.json`: external raw capture integrity metadata
- `integrity/raw_capture_integrity_audit.*`: latest audit output
- `backups/derived-rebuild/YYYYMMDD-HHMMSS/`: backed-up derived CSVs before rebuilds
- `quarantine/raw-captures/YYYYMMDD-HHMMSS/`: raw captures removed from active study use but retained for recovery/audit

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
- `QUARANTINED`: a raw capture was deliberately removed from active source-of-truth use and retained outside `data/captures`.

Modified raw captures must never be silently re-blessed. The recovery order is:

1. Restore the original raw JSON/MD from backup, Git history, OneDrive history, or another trusted machine.
2. If the original cannot be restored, quarantine the current modified files and rebuild derived data.
3. Only re-baseline with an explicit signed recovery note that says who approved it, when, and why. Do not update `source_hash` just to make the audit pass.

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

## Rebuilding Score Breakdowns

If `score-breakdowns.json` is missing or stale, rebuild it from active raw captures:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.rebuild_score_breakdowns
```

The rebuild command:

- reads only active raw capture JSON files under `data/captures`
- excludes quarantined captures because they live outside `data/captures`
- writes `MomentumHunterData/data/score-breakdowns.json` atomically
- backs up any previous score-breakdown store under `MomentumHunterData/data/backups/score-breakdowns/`
- reports counts for `complete`, `legacy`, `incomplete`, and `failed`

Audit score breakdowns with:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.score_breakdown_audit
```

The score-breakdown audit detects missing breakdowns for active scored candidates, duplicate identities, missing engine versions, malformed component lists, arithmetic mismatches, unexplained cap/floor data, quarantined-source references, and legacy/incomplete records.

## Quarantining Bad Raw Captures

If a raw capture cannot be trusted, move it out of active captures:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.quarantine_capture 2026-06-06 morning --reason "Manifest hash mismatch; excluded from studies."
.\.venv\Scripts\python.exe -m momentum_hunter.rebuild_derived_data
```

If the audit shows `MODIFIED`, use the modified-capture recovery command:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.recover_modified_captures --reason "Manifest hash mismatch; original unavailable; quarantined pending recovery review."
```

The quarantine command:

- moves `{session}.json` and `{session}.md` from `data/captures/YYYY-MM-DD/` into `data/quarantine/raw-captures/YYYYMMDD-HHMMSS/`
- moves active manifest records into `quarantined_records`
- writes timestamped recovery notes with original manifest metadata, current file metadata, hash mismatch evidence, and the recovery decision
- keeps the files available for investigation
- keeps auditing the quarantine copies for existence and SHA-256 drift
- preserves review decisions and marks decisions tied to quarantined captures as quarantined
- excludes the snapshot from rebuilt analysis CSVs, outcome CSVs, and Study Engine results
