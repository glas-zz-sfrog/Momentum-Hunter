# ARGUS-EVENT-001 Goal Charter - Versioned Macro-Event Context

## Goal

Create a deterministic offline calendar and context engine that preserves known
market-moving event evidence and applies an explicit caller-owned policy without
fetching data, scoring candidates, or initiating trades.

## Operator Outcome

Momentum Hunter can later explain whether a decision occurred in normal,
cautionary, blocked-new-entry, or stale event conditions, exactly which event
and revision applied, and whether that event was market-wide, sector-specific,
or symbol-specific.

## Scope

- Model every architecture-approved event category and four context states.
- Preserve stable source/event/revision identity and provider/receipt clocks.
- Validate scheduled, risk, and observation windows plus affected scope.
- Persist complete caller-supplied consequence policy and fingerprints.
- Preserve append-only, deterministic, tamper-evident calendar snapshots.
- Expose score-neutral context to a bounded watched-candidate set.
- Remain dormant until a later integration task wires an approved source.

## Non-Goals

- Do not select a calendar provider or choose production event windows.
- Do not invent production consequences, score candidates, recommend a trade,
  build a TradePlan, run Risk Governor, select, size, or create an order.
- Do not contact Schwab, Alpaca, another provider, Engine Host, the service,
  scheduler, Shadow state, WPF, production data, or credentials.
- Do not merge while the A003-dependent integration lane is frozen.

## Acceptance Criteria

- [x] All approved categories and `NORMAL`, `CAUTION`, `BLOCK_NEW_ENTRY`, and
  `DATA_STALE` are modeled.
- [x] Source/revision identity, dual clocks, all windows, importance, scope,
  evidence state, and fingerprints are immutable.
- [x] Unknown/stale active evidence and missing rules fail closed.
- [x] Symbol/sector events do not leak to unrelated candidates.
- [x] Lookahead, invalid chronology/windows/scope, revision reuse, chain skips,
  tampering, and atomic replace failure are rejected safely.
- [x] Exact replay is deterministic and duplicate append is byte-identical.
- [x] Candidate fan-out is bounded, ordered, score-neutral, and nontrading.
- [x] No existing runtime imports or activates the engine.
- [x] Focused, adjacent, and full Python verification pass.

## Evidence Depth

- Python compileall: pass.
- Focused event-context tests: 30/30 pass.
- Bounded regime, lifecycle, intraday-plan, and Shadow-selector suite: 167/167
  pass.
- Full Python discovery: 1,411/1,411 pass in 234.246 seconds.
- `git diff --check`, protected-path review, secret scan, and network/order/
  scoring capability scan: pass.
- No UI changed; no Steven visual check is required.

## Status

`IMPLEMENTED_PENDING_INTEGRATION` at `ea30d71` on
`codex/ARGUS-EVENT-001-versioned-macro-event-context`, stacked on REGIME-001
closeout `f4deb18`. Project development remains active; A003 direct Paper
acceptance remains separately blocked by market hours.
