# ARGUS-REGIME-001 Rolling Market And Sector Regime

## Classification

`IMPLEMENTED_PENDING_INTEGRATION`

Implementation commit: `a4b3de0`

Stacked base: MONITOR-001 closeout `d2b77c2`; canonical ancestor `1d0ca95`

## Result

This isolated branch adds a dormant offline engine for rolling market and sector
context. It consumes already-canonical terminal bars and an explicit policy. It
does not fetch data, choose production thresholds, score candidates, create a
TradePlan, evaluate risk, select a trade, or contact a broker.

## Contract

- Approved labels: `RISK_ON`, `RISK_OFF`, `MIXED`, `SECTOR_ROTATION`,
  `VOLATILITY_SHOCK`, `EVENT_RISK`, and `DATA_STALE`.
- Full policy definition and fingerprint, derivation profile, benchmark/sector
  symbols, exact source/bar identities, input hash, evaluation/latest-bar clocks,
  sufficiency/confidence, previous snapshot, transition reason, event-risk
  identity, and per-symbol metrics are immutable snapshot evidence.
- Inputs require terminal canonical states and fail on future bars, insufficient
  market depth, staleness, internal gaps, cross-benchmark skew, mixed per-symbol
  sources, invalid OHLCV, or contradictory identities.
- Atomic append-only JSON validates sequence, prior-snapshot chain, strict clock
  chronology, deterministic fingerprint, exact duplicate replay, and tampering.
- Candidate fan-out is bounded, preserves caller order, reports missing sector
  context as unavailable, requests reevaluation only after a real transition,
  and always carries score authority `NONE`.

## Hardening Found During Self-Review

1. The first pass stored only policy version and hash. The final snapshot embeds
   the complete policy definition and independently verifies its identity.
2. The first pass accepted any nonempty source-state label. The final engine
   accepts only terminal canonical `RECONCILED`, `CORRECTED`, or
   `HISTORY_ONLY_GAP_FILL` bars.
3. The final store also enforces strictly increasing evaluation time and proves
   that an atomic replace failure preserves the prior ledger.

## Verification

- Compileall: pass.
- Focused regime suite: 29/29 pass.
- Bounded candle collector/backfill, persistence, candidate lifecycle, and
  technical-breakout suite: 145/145 pass.
- Full Python discovery before final hardening: 1,379/1,379 pass.
- Final full Python discovery: 1,381/1,381 pass in 266.269 seconds.
- `git diff --check`: pass.
- Secret scan: no credential-shaped values.
- Capability scan: no network, provider, broker/order, scoring, readiness,
  TradePlan, Risk Governor, selection, or execution import/call.
- No existing production module imports `rolling_market_regime`.

## Protected Boundaries

No existing runtime, provider, account, broker, adapter, order, scoring,
readiness, selector, TradePlan, Shadow, service, scheduler, Engine Host, WPF,
package, schema, credential, raw capture, generated production report, or
production configuration file changed. Canonical `master`, Monday's jobs, the
installed service, Shadow state, and Alpaca Paper state were not touched.

## Remaining Work

- Do not merge or activate this branch while the integration lane is frozen.
- A later integration task must supply a reviewed production policy and wire
  only canonical R032 bars through the approved lifecycle boundary.
- `EVENT-001` may proceed offline as the next parallel task.
- Monday's direct A003 Paper lifecycle proof remains the separate market-hours
  acceptance gate.
