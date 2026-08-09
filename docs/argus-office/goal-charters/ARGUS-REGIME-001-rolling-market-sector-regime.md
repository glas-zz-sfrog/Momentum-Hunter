# ARGUS-REGIME-001 Goal Charter - Rolling Market And Sector Regime

## Goal

Create a deterministic offline context engine that derives versioned market and
sector regime evidence from already-canonical completed bars without scoring,
recommending, selecting, or trading.

## Operator Outcome

Momentum Hunter can later explain whether the broad market and available sector
evidence were aligned, mixed, rotating, volatile, event-constrained, or unsafe
to use, while preserving exactly which bars, clocks, sources, and policy created
that conclusion.

## Scope

- Implement all seven architecture-approved regime labels.
- Require a caller-supplied, fully persisted and fingerprinted formula policy.
- Bind benchmark, sector, source, bar, event-risk, sufficiency, confidence, and
  transition evidence to each immutable snapshot.
- Preserve append-only atomic snapshots with deterministic replay and tamper
  detection.
- Expose score-neutral context to a bounded watched-candidate set.
- Remain dormant until a later integration task explicitly wires canonical
  candle and lifecycle producers.

## Non-Goals

- Do not choose production thresholds or silently add candidate score points.
- Do not recommend a trade, build a TradePlan, run Risk Governor, select a
  candidate, size a position, or create an order.
- Do not contact Schwab, Alpaca, another provider, Engine Host, the installed
  service, scheduler, Shadow state, WPF, production data, or credentials.
- Do not merge while the A003-dependent integration lane is frozen.

## Acceptance Criteria

- [x] Every approved regime label has deterministic synthetic proof.
- [x] Terminal canonical state, depth, staleness, gaps, skew, source identity,
  and future-bar validation fail closed.
- [x] Full policy definition, derivation identity, source bars, and transitions
  are persisted and fingerprinted.
- [x] Exact replay is deterministic and duplicate append is byte-identical.
- [x] Tampering, chain breaks, backward chronology, and atomic replace failure
  preserve or reject evidence safely.
- [x] Sector data can be partial without being fabricated.
- [x] Candidate fan-out is bounded, order-preserving, and score-neutral.
- [x] No existing runtime imports or activates the engine.
- [x] Focused, adjacent, and full Python verification pass.

## Evidence Depth

- Python compileall: pass.
- Focused regime tests: 29/29 pass.
- Bounded candle, lifecycle, persistence, and breakout suite: 145/145 pass.
- Final full Python discovery: 1,381/1,381 pass in 266.269 seconds.
- `git diff --check`, protected-path review, secret scan, and network/order/
  scoring capability scan: pass.
- No UI changed; no Steven visual check is required.

## Status

`IMPLEMENTED_PENDING_INTEGRATION` at `a4b3de0` on
`codex/ARGUS-REGIME-001-rolling-market-sector-regime`, stacked on MONITOR-001
closeout `d2b77c2`. Project development remains active; A003 direct Paper
acceptance remains separately blocked by market hours.
