# Continuous Intraday Implementation Sequence

## Program Rules

- Each runtime task receives its own Goal Charter and task branch from current
  canonical `master` unless Git Steward documents a safe stacked dependency.
- No task assumes unverified Schwab semantics.
- Every material scoring, selection, setup, plan, risk, fill-model, cadence, or
  source change receives a prospective version and never rewrites old evidence.
- Python owns market data, state, decisions, persistence, and FakeBroker.
- WPF reads versioned Engine Host snapshots and sends bounded operator commands;
  it never owns a provider session.
- FakeBroker remains the only automated execution boundary.
- Real-order transmission remains unavailable.

## Dependency Chain

```text
ROADMAP-002
  -> R031B live proof
  -> R031C branch reconciliation / contract freeze
  -> R032 central Streamer manager + candle collector
  -> R033 Engine Host + WPF live chart integration
  -> MONITOR-001 candidate lifecycle
  -> DATA-002 time-normalized RVOL
  -> REGIME-001 rolling market/sector regime
  -> EVENT-001 macro-event policy
  -> CATALYST-002 intraday catalyst updates
  -> BREAKOUT-001 sequential breakout research capture
  -> BREAKOUT-002 prospective breakout event study
  -> PLAN-002 immutable intraday plan versions
  -> SHADOW-025 new prospective continuous-intraday sample
```

`UI-STREAMLINE-001` may proceed in parallel only when it presents already
canonical states and does not invent provider, plan, risk, or execution truth.

## 1. ARGUS-R031B - Live Candle Proof And Adjudication

**Objective:** Observe actual Schwab Streamer and price-history behavior without
production persistence.

**Depends on:** Existing R031/R031A observer branch; clean canonical runtime;
suitable market window.

**Acceptance:** SPY, IWM, and one deterministic Hunter candidate observed;
arrival/update/reconciliation evidence captured; every contract question marked
verified, disproven, partial, or unverified; sole-account invariant passes; no
production mutation.

**Excludes:** Collector, service wiring, WPF, decisions, Shadow, broker calls.

## 2. ARGUS-R031C - Candle Branch Reconciliation And Contract Freeze

**Objective:** Reconcile accepted parts of `a39086c`/`b96f745`, observer work
`3272476`/`d6d7217`, and provisional R032A `35c59ee` onto current canonical
history without importing disproven assumptions.

**Depends on:** Terminal R031B adjudication.

**Acceptance:** Current-baseline branch; explicit commit ancestry map; every
R031B finding mapped to code/contract; synthetic tests reflect observed
semantics; no provider call in tests; clean fast-forward integration path;
legacy branch remains preserved.

**Excludes:** Production subscription, persistence, service installation.

## 3. ARGUS-R032 - Central Streamer Manager And Incremental Candle Collector

**Objective:** Implement the sole Python-owned Schwab Streamer session,
subscription manager, and bounded canonical one-minute candle persistence.

**Depends on:** R031C frozen contract.

**Acceptance:**

- single-session lease and duplicate-owner rejection;
- `/userPreference` sole-account revalidation before Streamer bootstrap;
- priority subscriptions with non-evictable P0 safety symbols;
- acknowledgement, entitlement, reconnect, resubscribe, backpressure, gap,
  duplicate, out-of-order, and correction handling;
- initial universe limited to current Hunter candidates, selected/near-trigger
  symbols, active FakeBroker symbols, SPY, IWM, and required sector ETFs;
- write-ahead/atomic persistence, idempotency, source lineage, and crash recovery;
- provisional/completed/reconciled/corrected/gap/stale states based only on R031B;
- no mixed Schwab/legacy source identity; and
- no account, position, order, or transaction method.

**Excludes:** WPF provider calls, scoring, selection, live orders, R034 deletion.

## 4. ARGUS-R033 - Engine Host And WPF Live Charts

**Objective:** Expose canonical candle snapshots through versioned Engine Host
contracts and render them in WPF.

**Depends on:** Verified R032 persisted evidence.

**Acceptance:** 1m canonical bars; deterministic 5m/15m aggregation; chart shows
source, latest completed/in-progress bar, age, gaps, stale and correction state;
no provider call or indicator authority in WPF; candidate/pin/link behavior does
not create new subscriptions outside the manager; screenshot and Steven visual
acceptance.

**Excludes:** Legacy deletion and production scoring.

## 5. ARGUS-MONITOR-001 - Candidate Lifecycle And Event Coordinator

**Objective:** Separate periodic discovery from bounded continuous monitoring
and persist legal candidate transitions.

**Depends on:** R032 canonical events; R033 is useful but not logically required.

**Acceptance:** All roadmap lifecycle states; transition validation; opportunity
and setup identity; evidence fingerprint; hysteresis/cooldown/minimum-delta
configuration; event deduplication; no cycle on every quote; stale/recovery
rules; crash/replay idempotency; discovery outage does not erase watch state;
monitoring outage cannot be retroactively treated as a decision.

**Excludes:** New scoring formula, production breakout authority, real orders.

## 6. ARGUS-DATA-002 - Time-Normalized Intraday Relative Volume

**Objective:** Replace the non-authoritative partial-session/full-day ratio with
a prospective, time-aligned participation contract.

**Depends on:** R032 canonical intraday volume semantics and R031B volume
adjudication. It no longer precedes the candle evidence gate.

**Acceptance:** Same-time-of-day or explicitly approved expected-volume baseline;
session and extended-hours separation; source/version clocks; insufficient-data
state; no historical report rewrite; prospective score/readiness authority only
under a new configuration fingerprint.

**Excludes:** Provider guessing, account sizing, broker behavior.

## 7. ARGUS-REGIME-001 - Rolling Market And Sector Regime

**Objective:** Produce versioned market/sector context from canonical evidence.

**Depends on:** R032 bars; DATA-002 if participation is included.

**Acceptance:** Allowed regime labels; benchmark/sector inputs; sufficiency and
stale state; transition reason; replay determinism; bounded fan-out to watched
candidates; no silent score contribution.

**Excludes:** Trade recommendation and broad-universe breadth without data proof.

## 8. ARGUS-EVENT-001 - Macro Event Calendar And Risk Context

**Objective:** Maintain scheduled event context and auditable event-risk windows.

**Depends on:** Approved authoritative calendar source and policy decisions.

**Acceptance:** Source and revision identity; market-time semantics; normal,
caution, block-new-entry, and stale states; holiday/early-close support; no event
initiates a trade; unavailable data is explicit.

**Excludes:** News sentiment scoring and automatic broker action.

## 9. ARGUS-CATALYST-002 - Intraday Catalyst Refresh

**Objective:** Continuously add/revise catalysts while preserving DATA-001/001B
provenance and authority.

**Depends on:** MONITOR-001 events; accepted catalyst source contract.

**Acceptance:** Deduplication, revisions, attribution classes, provider/receipt
clocks, material-delta trigger, unresolved research-only state, outage/stale
handling, and no inherited freshness.

**Excludes:** Unsupported relationship inference and real-time LLM authority.

## 10. ARGUS-BREAKOUT-001 - Sequential Breakout Research Capture

**Objective:** Persist research-only sequences for impulse, breakout, miss,
failure, pullback, reclaim, and exhaustion.

**Depends on:** R032 candles and MONITOR-001 setup identity.

**Acceptance:** Prior-window/no-lookahead triggers; distinct setup IDs; exact
event clocks; unavailable data; failed-breakout preservation; no score,
readiness, selector, plan, or order authority.

## 11. ARGUS-BREAKOUT-002 - Prospective Sequential Event Study

**Objective:** Measure whether the sequential setup states add independent
evidence after latency, spread, regime, volume, and false-positive controls.

**Depends on:** Sufficient BREAKOUT-001 prospective events.

**Acceptance:** Frozen cohort and denominators; continuation/failure outcomes;
MFE/MAE; time-to-trigger; missed-opportunity accounting; redundancy analysis;
no edge claim below sample gate.

## 12. ARGUS-PLAN-002 - Immutable Intraday Plan Versions

**Objective:** Bind each actionable setup revision to an immutable plan and
fresh Risk Governor result.

**Depends on:** MONITOR-001; DATA-002; REGIME-001; EVENT-001; CATALYST-002;
accepted setup semantics from BREAKOUT research or separately frozen families.

**Acceptance:** Opportunity/setup/plan/decision IDs; explicit horizon; evidence
fingerprint; supersession reason; breakout/pullback/reclaim separation; missed
entry cannot silently become reclaim; manual override creates new version and
risk recheck; all historical versions remain queryable.

**Excludes:** Real broker allocation and transmission.

## 13. ARGUS-SHADOW-025 - Continuous Intraday Prospective Sample

**Objective:** Start a new, immutable FakeBroker-only sample using the frozen
continuous-intraday constitution.

**Depends on:** Every preceding authority-bearing task, visual acceptance of
required WPF states, complete proof bundle, and separately reviewed sample
constitution.

**Acceptance:** New sample/fill/config/evidence identities; v1/v2/v3 unchanged;
expected discovery/monitor cycles accounted for; duplicates/cooldowns and
availability denominators preserved; market/sector/event concentration shown;
FakeBroker only; no real-order capability.

## Parallel ARGUS-UI-STREAMLINE-001

**Objective:** Present continuous states with a quiet, integrated workstation
hierarchy.

**May start when:** It consumes synthetic or existing canonical view models and
does not block the critical path.

**Acceptance:** Compact pane controls, understandable state labels, global mode
treatment rather than repetitive warning badges, pane recovery logic, and
Steven visual acceptance. It may not invent provider freshness, account state,
plan eligibility, or execution authority.

## Integration Policy

The architecture package may merge as docs-only governance after proof. Runtime
tasks merge one at a time after Hard Chew and, when applicable, Steven visual
acceptance. Any canonical runtime merge while scheduled opening jobs remain
pinned requires deliberate service-manifest repin and fresh installed-state
proof; feature-branch work does not alter those jobs.
