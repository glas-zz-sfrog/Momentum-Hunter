# ARGUS-R034A Legacy Candle Consumer Migration

Status: `IMPLEMENTED_PENDING_MERGE`

## Result

Active minute-candle consumers no longer default to the retired CRWV JSON.
Outcomes, evidence health, data quality, file read models, technical-breakout
research, Daily symbol discovery, source registry, and SQLite reporting now use
terminal reconciled Schwab evidence or explicitly identify the old source as
retired. The exact production legacy path is write-blocked.

## Source Contract

- Canonical consumers accept only `RECONCILED`, `CORRECTED`, or
  `HISTORY_ONLY_GAP_FILL` records whose canonical candle is complete and names
  Schwab price history as its source.
- Stream-only, in-progress, malformed, mixed-source, and conflicting identities
  are excluded or fail closed.
- Explicit fixture paths remain supported for historical tests; they cannot
  silently become the production default.
- Prospective report producers carry `v2` engine identities while schema 1
  remains readable.

## Non-Destructive Boundary

The verifier can read hashes, counts, partition health, and source references.
It cannot write an archive, delete a file, modify SQLite, call a provider, query
an account, touch an order, or change runtime state. R034 remains a separate
destructive approval gate.

## Actual Verifier Evidence

- Status: `READY_FOR_DESTRUCTIVE_APPROVAL`.
- Legacy JSON: 710 CRWV bars, SHA-256
  `DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69`.
- SQLite: 710 matching rows and 710 total minute-bar rows.
- Schwab store: `HEALTHY`, 12,478 canonical bars across CHYM, IWM, SPY, and U.
- Blocking source references: 0.
- Inputs unchanged: true.
- Planned archive is outside active candle stores and must match the legacy hash
  before R034 can delete anything.

## Verification

- Compileall: pass.
- Focused tests: 44 passed.
- Full Python discovery: 1,225 passed.
- Full .NET solution: 251 passed.
- `git diff --check`: pass.
- Secret-value scan: no hits.
- Added network/account/order capability scan: no hits.
- No generated report, raw capture, package, schema, UI, score, readiness,
  replay, broker, credential, or transmission file changed.

## Remaining Gates

1. Commit and back up this feature branch.
2. Fast-forward the stacked R032C/R034A release into canonical `master`.
3. Repin the 26 remaining opening jobs and reload/verify the installed Engine
   Host once at the exact final release head.
4. Complete one live unseen-symbol R032C backfill proof.
5. Present R034's exact archive/deletion plan to Steven for explicit approval.
