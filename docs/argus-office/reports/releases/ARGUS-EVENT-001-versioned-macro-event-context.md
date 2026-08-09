# ARGUS-EVENT-001 Versioned Macro-Event Context

## Classification

`IMPLEMENTED_PENDING_INTEGRATION`

Implementation commit: `ea30d71`

Stacked base: REGIME-001 closeout `f4deb18`; canonical ancestor `1d0ca95`

## Result

This isolated branch adds a dormant offline calendar and event-context engine.
It evaluates source-supplied windows under a caller-supplied policy. It does not
fetch events, choose production rules, score candidates, create TradePlans,
evaluate risk, select trades, or contact a broker.

## Contract

- Categories cover Federal Reserve decisions/speakers, inflation and jobs
  releases, relevant Treasury auctions, company earnings, holidays, early
  closes, and separately approved other events.
- Every event preserves stable source/event/revision identity, title, category,
  importance, evidence state, provider/receipt clocks, scheduled/risk/
  observation windows, market/sector/symbol scope, and fingerprint.
- Each calendar snapshot preserves validity, exact source identities, sorted
  event revisions, predecessor identity, sequence, and fingerprint.
- A complete embedded policy maps category plus minimum importance to
  `CAUTION` or `BLOCK_NEW_ENTRY`; no event produces bullish authority. Missing
  rules and active stale/unknown evidence must produce `DATA_STALE`.
- Bounded candidate fan-out preserves order, applies market events globally,
  confines symbol/sector events to their scope, and always carries score
  authority `NONE` plus trade-initiation capability false.

## Hardening Found During Self-Review

1. Cancelled events are filtered from active evidence even when the enclosing
   calendar has expired.
2. Snapshot builders cannot accept an arbitrary explicit sequence; each new
   snapshot must extend its predecessor exactly.
3. Final tests prove all approved categories are represented and source
   definitions are not mutated.

## Verification

- Compileall: pass.
- Focused event-context suite: 30/30 pass.
- Bounded REGIME-001, MONITOR-001, intraday-plan, and Shadow-selector suite:
  167/167 pass.
- Full Python discovery: 1,411/1,411 pass in 234.246 seconds.
- `git diff --check`: pass.
- Secret scan: no credential value; the sole broad-pattern hit was `sk-` inside
  the literal phrase `risk-policy`.
- Capability scan: provider/trading names occur only in forbidden-import tests;
  the implementation has no network, provider, broker/order, scoring,
  readiness, TradePlan, risk, selector, Engine Host, or Shadow import/call.
- No existing production module imports `macro_event_context`.

## Protected Boundaries

No existing runtime, provider, account, broker, adapter, order, scoring,
readiness, selector, TradePlan, Shadow, service, scheduler, Engine Host, WPF,
package, schema, credential, raw capture, generated production report, or
production configuration file changed. Canonical `master`, Monday's jobs, the
installed service, Shadow state, and Alpaca Paper state were not touched.

## Remaining Work

- Do not merge or activate this branch while the integration lane is frozen.
- A later source task must choose and prove an event provider; a later policy
  decision must freeze production windows and consequences prospectively.
- `CATALYST-002` may proceed offline as the next parallel task.
- Monday's direct A003 Paper lifecycle proof remains the separate market-hours
  acceptance gate.
