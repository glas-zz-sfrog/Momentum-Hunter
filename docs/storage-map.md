# Momentum Hunter Storage Map

Momentum Hunter separates immutable market observations from derived research artifacts. Raw captures are the source of truth; everything else should be rebuilt, edited, or replaced without changing those raw files.

## Raw captures

- Path: `MomentumHunterData/data/captures/YYYY-MM-DD/{morning|evening|manual}.json`
- Path: `MomentumHunterData/data/captures/YYYY-MM-DD/{morning|evening|manual}.md`
- Owner: capture engine
- Mutability: immutable after creation
- Purpose: point-in-time record of what Momentum Hunter knew at capture time
- Integrity: new captures include JSON `integrity.created_at` and `integrity.source_hash`; raw JSON/MD file hashes are also tracked in `capture-integrity-manifest.json`

Raw capture files must not store later review decisions, outcomes, score recalculations, study summaries, or AI annotations.

New raw captures also exclude user decision fields (`selected`, `reviewed`, `review_status`), user notes, and score-breakdown text such as score reasons. Those belong in separate review/derived stores.

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

## Study reports

- Source paths: `MomentumHunterData/data/analysis-captures.csv`, `MomentumHunterData/data/analysis-outcomes.csv`
- UI location: Study Engine dialog
- Mutability: disposable/rebuildable
- Stores: aggregate summaries, score buckets, filtered historical summaries

Study results should be treated as derived views. They are useful research output, not source-of-truth capture data.

## Provider raw snapshots

- Current status: not persisted as a dedicated provider snapshot store yet
- Future path: `MomentumHunterData/data/provider-snapshots/{provider}/YYYY-MM-DD/...`
- Mutability: immutable after creation
- Purpose: preserve provider responses separately from normalized candidate captures

When provider snapshots are added, they should be hashed and tracked the same way as raw captures.

## Integrity index

- Path: `MomentumHunterData/data/capture-integrity-manifest.json`
- Owner: capture storage and integrity audit
- Mutability: updated only when a raw capture file is first created
- Purpose: detect raw capture JSON/MD file changes after creation

The manifest is not the source of truth for market data. It is an audit index for raw file integrity.
