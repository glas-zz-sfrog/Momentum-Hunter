# ARGUS-DATA-004 Intraday TradePlan Horizon

Status: `COMPLETE`

## Result

TradePlan now has a versioned, prospective same-session `INTRADAY` contract.
`OPENING_BREAKOUT` is one setup family alongside `CONTINUATION_BREAKOUT`,
`PULLBACK`, and `RECLAIM`; it is not the horizon model. Technical and
authority-proven catalyst drivers use the same identity and lifecycle rules.

## Contract

- Schema 1/profile `same-session-intraday-plan-v1` binds the symbol, session,
  family, driver, source setup and evidence, entry/stop/targets, validity and
  expiry times, forced-flat boundary, lifecycle state, predecessor/replacement
  identity, plan ID, and SHA-256 record fingerprint.
- Lifecycle states are `PENDING_ENTRY`, `TRIGGERED`, `MISSED_ENTRY`, `EXPIRED`,
  and `INVALIDATED`; terminal states cannot be reopened.
- Opening entries begin after the completed 09:30-09:34 ET range and expire at
  10:30 ET by default. Continuation defaults to 45 minutes; pullback and reclaim
  default to 30 minutes. Regular entry cutoff is 15:30 ET and forced flat is
  15:55 ET, with explicit early-close handling.
- Later producers may supply explicit same-session windows without changing the
  core contract.
- Catalyst plans require `SUPPORTED` attribution and a bound attribution
  fingerprint.

## Setup Replacement

- A level crossed before the opening plan exists produces immutable
  `MISSED_ENTRY`; it is not moved upward or renamed.
- A reclaim is a new plan with a new identity, a terminal opening/continuation
  breakout predecessor, predecessor fingerprint, and replacement reason.
- Pullback plans cannot masquerade as reclaim predecessors, and predecessor or
  source-evidence contradictions fail closed.

## Runtime Boundaries

- The opening report producer uses exactly five completed, reconciled canonical
  Schwab bars for 09:30-09:34 ET. Missing, duplicated, wrong-source,
  wrong-symbol, unreconciled, malformed, or late-created evidence fails closed.
- Risk Governor checks lifecycle authority at the current decision time.
- Active Monitor recalculates timing authority at each refresh while preserving
  original evidence.
- Historical workstation snapshots pass their persisted observation clock;
  live simulation uses the live clock.
- Shadow independently checks plan equality, schema/profile, source binding,
  levels, targets, timing, lifecycle, plan ID, and fingerprint.

## Verification

- Python compileall: pass.
- Focused cross-module suite: 153 passed before final broad-test repairs.
- Full Python discovery: 1,271 passed in 746.245 seconds.
- Full .NET solution: 251 passed.
- `git diff --check`: pass.
- Direct coverage includes all setup families, catalyst attribution, expiry,
  invalidation, legal/illegal transitions, weekends, early/regular sessions,
  missing and malformed bars, duplicate/source tampering, plan-ID/fingerprint
  tampering, immutable missed entries, and successor reclaim identity.

## Protected Review

- Composite score weights, rank, alert thresholds, RVOL semantics, replay,
  capture schedule, service behavior, providers, candle stores, account binding,
  position sizing, broker/order behavior, and transmission are unchanged.
- No database/schema, package, credential, environment, UI, raw capture,
  generated report, or production market-data file changed.
- Historical evidence remains immutable under its prior profiles.

## Remaining Limits

- The opening capture is the first producer; continuous later-session setup
  discovery remains future work, but it no longer requires a new horizon model.
- DATA-005 remains the account-aware allocator and sizing gate.
- Official Shadow remains unarmed and `0 / 30`.
- R034 remains a separate destructive approval gate.
