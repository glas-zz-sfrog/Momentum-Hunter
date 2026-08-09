# ARGUS-MONITOR-001 Goal Charter - Candidate Lifecycle And Event Coordinator

## Goal

Create a provider-neutral, deterministic lifecycle substrate that records
already-observed candidate and setup transitions without deriving signals or
participating in trading.

## Operator Outcome

Momentum Hunter can preserve why a symbol entered the watch set, which setup it
was forming, whether that setup failed, expired, or became stale, and whether a
later pullback or reclaim is a genuinely new setup. Discovery or monitoring
outages remain visible instead of silently erasing candidates or fabricating
decisions.

## Scope

- Model every approved candidate lifecycle state and legal transition.
- Create stable opportunity and separately sequenced setup identities.
- Persist append-only, hash-addressed events with atomic replacement.
- Version cooldown, hysteresis, and minimum-delta policy on every event.
- Preserve exact replay, no-change, stale/recovery, and outage evidence.
- Reject quote-only decision-cycle creation.
- Remain dormant until a later integration task explicitly wires a producer.

## Non-Goals

- Do not discover chart patterns, score or rank candidates, build TradePlans,
  run Risk Governor, select a candidate, or create a broker order.
- Do not contact Schwab, Alpaca, another provider, Engine Host, the installed
  service, scheduler, Shadow state, production data, or credentials.
- Do not activate continuous intraday trading or change Monday's runtime.
- Do not merge while the A003-dependent integration lane is frozen.

## Acceptance Criteria

- [x] All approved lifecycle states and legal transitions are modeled.
- [x] Opportunity/setup/predecessor identities are deterministic and validated.
- [x] Exact replay is idempotent and conflicting replay fails closed.
- [x] Discovery refresh cannot demote an existing lifecycle state.
- [x] Stale/recovery and availability chronology cannot be backfilled.
- [x] Cooldown uses the policy persisted when cooldown began.
- [x] Setup-family/state mismatches and rehashed tampering fail closed.
- [x] Atomic-write failure preserves the prior ledger.
- [x] No existing runtime imports or activates the coordinator.
- [x] Focused, adjacent, and full Python verification pass.

## Evidence Depth

- Python compileall: pass.
- Focused lifecycle tests: 38/38 pass.
- Adjacent monitor, alert, target, plan, selector, and Engine Host tests:
  195/195 pass.
- Full Python discovery: 1,352/1,352 pass in 272.318 seconds.
- `git diff --check`, protected-path review, secret scan, and network/order
  capability scan: pass.
- No UI changed; no Steven visual check is required.

## Status

`IMPLEMENTED_PENDING_INTEGRATION` at `b71feb0` on
`codex/ARGUS-MONITOR-001-candidate-lifecycle`. Project development remains
active; A003 direct Paper acceptance remains separately blocked by market
hours.
