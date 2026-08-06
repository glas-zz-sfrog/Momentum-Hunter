# ARGUS-R033 Live Chart And Engine Host Integration

Status: `COMBINED_VERIFIED_PENDING_MASTER_INTEGRATION`

## Scope

R033 exposes the separate R032 Schwab one-minute candle store through a
versioned Python Engine Host contract and renders that evidence in WPF. It does
not schedule collection, call Schwab from WPF, change scoring/readiness, arm
Shadow, touch broker/order behavior, or perform the R034 legacy cutover.

## Implementation

- `WorkstationChartService` now reads intraday bars only from validated R032
  daily/symbol partitions and emits chart schema 2.
- Price-history versions are canonical; the latest stream version remains
  separately visible when history has not reconciled it.
- One-minute source bars aggregate deterministically to 5m and 15m without
  crossing session dates. Missing minutes remain gaps rather than interpolation.
- Daily reads only the separate, validated R032B `schwab-daily-candles-v1`
  store. Missing or tampered Daily evidence fails closed and never falls back
  to intraday, mock, legacy, or quote-derived candles.
- Engine Host and .NET contracts preserve provider and receipt timestamps,
  canonical/in-progress state, source, gap flags, discrepancy fields, and
  present/expected minute counts.
- WPF refreshes cached chart snapshots every five seconds. Timer refreshes skip
  overlap; explicit candidate/interval actions serialize behind an active read
  and then load the requested context.
- The quality band shows provider/state, latest completed and receipt times,
  age, gaps, corrections, unreconciled bars, and the newest in-progress minute.
  Corrected, provisional, and gapped candles receive distinct rendering.
- The ignored proof harness passes an explicit isolated Engine Host state
  directory directly to the existing connection options. Production startup,
  settings, environment handling, and canonical Engine Host defaults remain
  unchanged.
- Operational source, timing, integrity, and active-bar details wrap at narrow
  workstation widths. Candidate rows use a compact normalized readiness badge
  while preserving the complete persisted source-readiness code on hover.
- The chart viewport uses dense six-pixel target slots, keeps sparse evidence
  adjacent and right-aligned, and displays only the latest bounded window when
  stored history exceeds the pane capacity. Hover inspection uses that same
  viewport mapping and ignores intentionally empty history slots.

## Verification

- Python compileall: pass.
- Focused combined chart/backfill tests: 31/31 pass.
- Full Python discovery: 1,203/1,203 pass in 200.388 seconds after providing the
  isolated worktree its expected `.venv` junction.
- Focused density/readability tests: 26/26 pass.
- Full .NET solution: 250/250 pass.
- Release build: pass with zero warnings and zero errors.
- `git diff --check`: pass; only configured LF-to-CRLF worktree notices.
- A read-only R032B proof populated the isolated chart stores with 39,165
  minute-bar versions and 1,260 daily bars across NVDA, SHOP, ZETA, SPY, and
  IWM in about ten seconds. The 1m WPF proof renders 180 current-session bars.
  The combined service returns 180 validated Daily bars for every proof symbol,
  names Schwab as provider, and rejects tampered or legacy daily input.
- Source nonmutation: chart reads leave daily and Schwab inputs byte-identical.
- Protected-path review: no score, readiness, selection, TradePlan, Shadow,
  broker/order, service/scheduler, database/schema, package, environment,
  raw-capture, generated production report, or legacy-candle path changed.

The first combined broad Python discovery reported two environment-only failures
because the separate worktree did not contain `.venv`. A local ignored junction
to the canonical virtual environment restored the expected script path; both
affected tests passed directly and the complete rerun passed 1,203/1,203. A self-review
concurrency test initially hung because its test double discarded its own
release handle; the test-only defect was corrected, orphaned processes scoped
to the R033 worktree were stopped, and the final focused/full runs passed.
The final self-review removed proof-only environment overrides from production
startup and Engine Host connection code, then added fail-closed tests for
contradictory root/quality states, lineage labels, lifecycle counts, and latest-
bar timestamps. The proof harness now supplies isolation only through existing
connection options, leaving production environment handling unchanged.

## Visual Gate

The isolated WPF proof uses the populated external R032B store and copied,
ignored August 5 candidate evidence. Steven reviewed the density repair and
directed Git Steward to integrate the candle work on 2026-08-06.

- `ARGUS-R033-live-chart-ui-proof-1180x820.png`: 1180x820, 122242 bytes,
  SHA-256 `52A369882FF2C320D760E08EF262BB2B0BFD4CEB474152C84F1328E6304920A5`.
- `ARGUS-R033-live-chart-ui-proof-1920x1080.png`: 1920x1080, 145150 bytes,
  SHA-256 `9D7701490BE0AB1EE87376A7098AD531543B581165820F3D50F97F04292A6602`.
- Both proofs are nonblank. Automated inspection confirms visible stored candle
  bodies, wicks, and volume; Schwab source and stale state; complete wrapped
  timing/integrity/latest-bar text; concise `NEEDS DATA` candidate badges; and
  no Buy, Sell, Submit, Replace, Cancel, account, or live-order control.
- The proof-only Engine Host was stopped after capture and no matching process
  remains. Canonical WPF, service, scheduler, and Engine Host were not touched.

## Known Limits

- R032 remains manually invoked. R033 consumes new partitions but does not
  create them or install an unattended collector.
- Backfill is still explicitly invoked. Automatic bounded queueing when a new
  symbol enters the candidate/watchlist/selection universe remains follow-up
  work, along with a visible loading-history state.
- Reconnect, halt, and larger subscription behavior remain provider evidence
  limits; the consumer preserves resulting persisted states but does not invent
  behavior not present in the store.
- R034 remains a separate Steven-approved destructive task. The legacy CRWV
  JSON and mirrored SQLite rows remain untouched and cannot be used by R033.

## Safety Answers

- Does WPF contact Schwab or an account? No.
- Does R033 place, preview, replace, or cancel an order? No.
- Does it change score, readiness, Risk Governor, or Shadow eligibility? No.
- Can missing Schwab candles fall back to legacy or mock candles? No.
- Is a collector scheduled or installed? No.
- Is the legacy CRWV evidence deleted? No.
- Is the combined branch merge-ready? Yes. R032B and R033 are reconciled, Daily
  uses only the Schwab daily store, automated proof passes, and Steven's visual
  gate passes.
