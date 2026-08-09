# Continuous Intraday Implementation Sequence

## Status

`RECONCILED_TO_CURRENT_MASTER_2026-08-09`

This contract supersedes the stale execution status in source branch `bae053b`
while preserving its architecture and task identities. Source SHA-256:
`8E0BD2A683B9B192D1B017D79BCAB6D676BD66A2E854159308EBD0C11E68C30B`.

The authoritative scheduling state remains
[ROADMAP.md](../ROADMAP.md). This file defines the continuous-intraday program
order and protected boundaries; it does not authorize integration or runtime
activation.

## Program Rules

- Python owns market data, state, decisions, persistence, and execution logic.
- WPF reads versioned Engine Host snapshots and never owns a provider session.
- Every material source, setup, plan, score, selection, risk, allocation,
  cadence, broker-capability, or fill-model change receives a prospective
  identity and never rewrites old evidence.
- Provider facts are observed and versioned; unsupported semantics remain
  unavailable.
- FakeBroker remains the canonical automated execution boundary. Alpaca Paper
  integration requires terminal A003 acceptance and a separate serialized
  integration. Live transmission remains unauthorized.
- A scheduled-runtime pin blocks integration/installation only. Independent
  work may continue in isolated worktrees.

## Current Program Board

| Order | Capability | State | Evidence / next boundary |
| --- | --- | --- | --- |
| 1 | R031B live candle proof | `COMPLETE` | Canonical through `404c589`; closeout `06b3fa7`; accepted with limitations |
| 2 | R031C contract reconciliation | `COMPLETE` | Accepted observation shapes integrated before R032 |
| 3 | R032 incremental candle collector | `COMPLETE` | Canonical `5442fbb`; bounded reconciled store |
| 4 | R032B/R032C history and automatic backfill | `COMPLETE` | Canonical through `ad900e1`; minute/Daily depth and cache-first loading |
| 5 | R033 Engine Host/WPF charts | `COMPLETE` | Canonical through `af783da`; Steven accepted dense visual proof |
| 6 | DATA-002 time-normalized RVOL | `COMPLETE` | Canonical `876eb2e`; insufficient data fails closed |
| 7 | DATA-003 setup identity | `COMPLETE` | Canonical `c61b559`; missed breakout cannot become reclaim |
| 8 | DATA-004 intraday horizon | `COMPLETE` | Canonical `fc8a114`; opening is one setup family, not the model |
| 9 | DATA-005/DATA-005A account evidence | `COMPLETE` | Canonical `a2e5020`/`dff993c`; policy activation remains gated |
| 10 | MONITOR-001 candidate lifecycle | `VALIDATED_PENDING_INTEGRATION` | `d2b77c2`; integrate first in the dormant stack |
| 11 | REGIME-001 market/sector context | `VALIDATED_PENDING_INTEGRATION` | `f4deb18`; includes MONITOR lineage |
| 12 | EVENT-001 macro-event model | `VALIDATED_PENDING_INTEGRATION` | `b6e861a`; source/policy activation remains separate |
| 13 | CATALYST-002A provider-neutral evidence | `VALIDATED_PENDING_INTEGRATION` | `97ab34d`; live provider work remains CATALYST-002B |
| 14 | BREAKOUT-001 sequential capture | `READY` | Research-only events over canonical bars and MONITOR identity |
| 15 | BREAKOUT-002 prospective event study | `WAITING_DEPENDENCY` | Requires sufficient frozen BREAKOUT-001 cohort |
| 16 | PLAN-002 continuous immutable plans | `WAITING_DEPENDENCY` | Requires integrated evidence/context chain and accepted setup evidence |
| 17 | Alpaca A003 Paper lifecycle | `WAITING_EXTERNAL_TIME` | Direct market-hours lifecycle acceptance only; development remains active |
| 18 | DATA-005B provider-neutral allocation integration | `WAITING_DEPENDENCY` | Requires A003 truth and current-base reconciliation |
| 19 | SHADOW-025 continuous sample | `WAITING_DEPENDENCY` | Requires frozen continuous authority, allocation, visual, and evidence identities |

`UI-STREAMLINE-001` and worktree hygiene may proceed in parallel under their
own gates. R034 deletion remains separately approval-gated.

## Active Dependency Graph

```text
canonical candles + DATA-002/003/004/005A
  -> integrate MONITOR-001
  -> integrate REGIME-001
  -> integrate EVENT-001
  -> integrate CATALYST-002A
  -> BREAKOUT-001 research capture
  -> sufficient prospective cohort
  -> BREAKOUT-002 event study
  -> accepted setup/context evidence
  -> PLAN-002 continuous plan versions

Alpaca A003 live Paper acceptance
  -> A001-A003 current-base integration
  -> DATA-005B provider-neutral allocation integration
  -> prospective Paper engineering evidence

continuous authority chain + accepted allocation/execution evidence
  -> SHADOW-025 new prospective sample
```

The branches can be developed in parallel where the Roadmap marks them Ready,
but canonical integration is one candidate at a time in dependency order.

## Completed Contract Summary

### R031B / R031C

Observed Schwab `CHART_EQUITY` and `/pricehistory` during market hours. The
proof accepted one-minute transport with limitations: comparable OHLC matched,
some stream volume had fractional tails, and stream-only canonicality remained
false. The historical contract is preserved in
[ARGUS-R031B-live-candle-proof-adjudication.md](ARGUS-R031B-live-candle-proof-adjudication.md).

### R032 / R032B / R032C

Canonical Schwab candle evidence is source-specific, hash-validated, bounded,
atomic, idempotent, correction-aware, and gap/stale explicit. Historical
backfill supplies bounded one-minute and Daily depth. Cache-first automatic
loading coalesces requests and never fabricates another source.

### R033

Engine Host exposes versioned stored snapshots. WPF renders canonical 1m and
Daily bars plus deterministic 5m/15m aggregation, provider/freshness/gap state,
and dense chart history. WPF does not call Schwab.

### DATA-002 Through DATA-005A

RVOL is time-normalized and fail-closed; setup and successor identities are
immutable; same-session TradePlans support opening and later-session families;
reference sizing is nonexecutable; fresh account/portfolio evidence is required
before allocation. Broker capability and final numeric policy remain separate.

## Validated Pending Integration

### MONITOR-001

Integrate legal candidate transitions, evidence fingerprints, material-delta
triggers, stale/recovery rules, deduplication, and crash/replay idempotency.
Monitoring outage cannot become retrospective decision evidence. This commit is
the base dependency for REGIME/EVENT/CATALYST branches.

### REGIME-001

Integrate versioned market/sector context only after MONITOR. Regime is
sufficiency-gated context and cannot silently add score or initiate a trade.

### EVENT-001

Integrate the dormant source-neutral calendar/event model after its exact
MONITOR/REGIME ancestry. Authoritative sources and consequence windows remain
EVENT-002 work.

### CATALYST-002A

Integrate immutable provider-neutral catalyst revisions, attribution,
authority, content deduplication, stale/outage/recovery, and material deltas.
Live intake remains blocked until CATALYST-002B proves a provider/source
contract and bounded cadence.

## Ready Research Slice

### BREAKOUT-001

Persist research-only impulse, breakout, miss, failure, pullback, reclaim, and
exhaustion sequences using prior-window/no-lookahead rules, exact clocks,
distinct setup IDs, and explicit unavailable data. It receives no score,
readiness, TradePlan, selector, Risk Governor, or order authority.

### BREAKOUT-002 Gate

Do not draw outcome conclusions until a frozen prospective cohort is large
enough to preserve denominators, MFE/MAE, time-to-trigger, latency, spread,
regime, false-positive, missed-opportunity, and redundancy evidence.

## Plan And Sample Gates

PLAN-002 binds every continuous setup revision to an immutable TradePlan and a
fresh Risk Governor/allocation decision. It must preserve opportunity, setup,
plan, decision, source, context, predecessor, and supersession identities.

SHADOW-025 starts a new sample only after the authority-bearing chain is frozen.
It cannot reuse or backfill v1/v2/v3. FakeBroker and any later accepted Alpaca
Paper research lane must remain separately identified; neither authorizes live
orders.

## Integration Policy

1. Revalidate each candidate against current `master`.
2. Preserve stack order and source commit identity.
3. Require clean fast-forward-compatible history; never reset/rebase/force-push
   to manufacture compatibility.
4. Run full protected-path, secret, and regression proof appropriate to the
   changed code.
5. Merge/install/repin only in a deliberate integration window.
6. A validated branch is not canonical merely because it is pushed.
