# ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001A Closeout

Date: 2026-08-26

## Identity

- Branch: `codex/ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001A`
- Base: `2a53881fdfc103db10c06216fee84d2de6ea5003`
- Qualified implementation: `74da179e76ab714bc3a650a0162e523d461ccef5`
- Forensic standard SHA-256:
  `8B3A7F161BA393DACCED20C92B6B544C3893D201A97F76B370980DA884940303`
- Authority: `RESEARCH_ONLY`
- Execution authority: `NONE`
- Order capability: `UNAVAILABLE`
- Status at branch closeout: `IMPLEMENTED_PENDING_MERGE`

## Result

The existing `run_runtime()` path now shares a natural setup coordinator
between composition and material-event polling. Recurring Finviz discovery and
hot-universe admission remain owned by their existing components. A newly
tracked symbol enters bounded Schwab history/readiness handling, receives an
immutable candidate lifecycle, and is evaluated from canonical completed bars
without any caller injecting lifecycle, successor, predecessor, or decision
objects.

The coordinator reuses the existing candidate-lifecycle and sequential-
breakout contracts. Completed canonical bars with preserved price-history
receipt identity emit exact `CANONICAL_BAR_COMPLETED` material events. Those
events drive bounded composition steps that preserve pending, breakout,
missed-entry, failed-breakout, exhaustion, pullback, reclaim, continuation,
predecessor, and successor chronology. A missed setup remains immutable; a
later valid setup receives a distinct identity and a new DATA-004 TradePlan.

Runtime reconstruction reloads the persisted same-session hot universe,
canonical discovery snapshot, lifecycle ledger, sequential-event ledger,
producer records, processed material fingerprints, existing plan identities,
and predecessor linkage. Late process starts use a prospective evidence floor
and cannot replay earlier intraday bars as newly observed decisions.

## Exact Natural Path

`run_runtime()`
-> `LiveDiscoverySource`
-> `LiveMarketDataSource`
-> `LiveMaterialEvents`
-> `ContinuousNaturalSetupCoordinator.completed_bar_events()`
-> `LiveCompositionSource.compose()`
-> `ContinuousNaturalSetupCoordinator.next_step()`
-> `ContinuousTradePlanProducer.evaluate()`
-> `ContinuousNaturalSetupCoordinator.commit()`
-> existing Continuous writer envelope.

The five-second runtime tick is scheduling only. Material identity comes from
the completed canonical bar, its canonical fingerprint, the persisted Schwab
history receipt, and the resulting sequential/lifecycle evidence.

## Historical Context

`HISTORICAL_CONTEXT_DECISION_USE = PARTIAL`

- History identity, depth, chronological admission, and prior-session
  time-normalized RVOL remain decision inputs.
- Same-session completed canonical bars now derive sequential breakout and
  successor trigger evidence.
- The prior completed-bar range supplies the explicitly labeled stop/target
  distance for the natural research successor.
- Daily and older minute history still do not derive broader support/resistance,
  ATR, trend, technical pattern, or multi-resolution context.

Adequate historical context plus one current completed canonical bar remains
sufficient. No five-new-bar admission ceremony was introduced.

## Instrument Boundary

Unknown or unavailable instrument classification now preserves a research
TradePlan while adding `INSTRUMENT_CLASSIFICATION_UNAVAILABLE` and forcing
top-level `execution_eligible = false`. No common-stock status is inferred.
Authoritatively identified leveraged ETP, inverse ETP, ETN, and other blocked
classes still suppress the plan and remain ineligible.

## Evidenceability

Each natural composition chain preserves the request, every natural event,
source/material fingerprints, full producer record, producer record identity,
cycle identity, known-at cutoff, and explicit safety fields. The producer and
lifecycle stores reject malformed, oversized, tampered, contradictory, or
future-known evidence and make exact duplicates idempotent.

The external forensic standard remains the binding contract for the separately
authorized real provider-backed canary. This task made no provider call and did
not manufacture a market setup.

## Verification

- Focused natural/composition/producer/deployment tests: 57 passed.
- Architecture adjacency suites: all passed after one narrow expected importer
  allowlist update; one non-elevated Windows link case remains an expected skip.
- Continuous runtime/canary/soak suites: 33 passed in 136.868 seconds.
- Full Python discovery: 2,763 tests in 2,250.266 seconds,
  `OK (skipped=1)`.
- Compileall: passed.
- PowerShell installer parse: passed.
- `git diff --check`: passed.
- Secret scan: passed.
- Forbidden account/broker/order capability scan: passed.
- Opening boundary: 96 reachable package modules, 115 excluded modules, 99
  closure files, zero outside-root imports, and zero dynamic-load sites. All
  five changed Continuous modules are opening-excluded. No opening promotion is
  required.
- The initial aggregate nonmutation helper produced incomparable before/after
  aggregate values because it did not preserve its per-file hash domain. The
  authoritative capture-manifest check independently verifies all 12 Aug. 24/25
  raw capture files byte-for-byte, and all six protected opening reports retain
  their original Aug. 24/25 write times. Automation manifest SHA-256 remains
  `afc55ec289e46e02df96c2fc0b4dd501deec763fc94b82dbb2065b25f942700b`.
- `MomentumHunterAutomation`, `MomentumHunterContinuousRuntime`, and
  `MomentumHunterContinuousWriter` remain Running/Automatic with unchanged
  service definitions. The Continuous services remain installed at
  `e69426b3b7bd179cd62eba2e28a5d0553da47154`.

No .NET source changed, so .NET testing was not required.

## Classification

`NATURAL_RUNTIME_TRADEPLAN_PATH_IMPLEMENTED = YES`

`PRODUCTION_LIFECYCLE_SOURCE_IMPLEMENTED = YES`

`COMPLETED_BAR_EVENT_DISPATCH_IMPLEMENTED = YES`

`MATERIAL_REEVALUATION_NATURAL_PATH_PROVEN = YES`

`NATURAL_SUCCESSOR_SETUP_PRODUCTION_PROVEN = YES`

`NATURAL_SUCCESSOR_TRADEPLAN_PROVEN = YES`

`END_TO_END_RESTART_RECONSTRUCTION_PROVEN = YES`

`NEW_SYMBOL_BACKFILL_NATURAL_PATH_READY = YES`

`ARBITRARY_FIVE_BAR_GATE_ABSENT = YES`

`HISTORICAL_CONTEXT_DECISION_USE = PARTIAL`

`UNKNOWN_INSTRUMENT_RESEARCH_VISIBILITY = YES`

`UNKNOWN_INSTRUMENT_EXECUTION_ELIGIBILITY = BLOCKED`

`CONTINUOUS_PAPER_ACTIVATION_READY = NO`

`EXECUTION_AUTHORITY_ADDED = NO`

`FORENSIC_EVIDENCEABILITY_IMPLEMENTED = YES`

`READY_FOR_PROVIDER_BACKED_FORENSIC_CANARY = YES`

## Next

Cleanly fast-forward the qualified branch into canonical after branch closeout,
then run the separately authorized real provider-backed research-only forensic
canary. Do not activate STAT-DATA-002, implement instrument classification, or
reconcile/arm Continuous Paper in this task.
