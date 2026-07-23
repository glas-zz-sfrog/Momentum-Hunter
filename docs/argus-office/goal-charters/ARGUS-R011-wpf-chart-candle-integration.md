# ARGUS-R011 - WPF Chart Candle Integration

## Goal Statement

Render deterministic OHLC candle bodies, wicks, and volume in the WPF workstation from existing local Python evidence through a versioned, read-only chart contract, without provider fetches, synthetic fallback, or changes to scoring, readiness, replay, planning, risk, simulation, or broker behavior.

## User Pain / Operator Outcome

The accepted workstation currently shows an empty Chart pane because the real Python workspace path deliberately clears mock candles. Steven must be able to inspect the stored chart structure that actually exists, know its symbol and timeframe, and see whether that evidence is current, stale, insufficient, or unavailable.

## In Scope

- Add a loopback-only Python Engine Host command for one symbol and one supported interval: `1m`, `5m`, `15m`, or `Daily`.
- Read existing `opportunity-minute-bars.json` and `daily-ohlc-bars.json` files without modifying them.
- Aggregate stored one-minute bars deterministically for `5m` and `15m`; do not interpolate or invent bars.
- Return versioned candle data, state, source lineage, latest source timestamp, and an operator-facing summary.
- Map the chart snapshot into WPF and refresh the primary and linked chart panes when symbol or interval changes.
- Render stale stored candles with an explicit stale label; render missing or malformed data as unavailable without mock fallback.
- Add focused Python service/host tests and .NET mapper/presentation tests.

## Out Of Scope

- Provider or broker network calls, credentials, API keys, order routing, Paper, or Live behavior.
- Scoring, readiness, alert thresholds, replay identity, TradePlan, Risk Governor, Execution Ledger, Execution Auditor, or FakeBroker changes.
- New market-data storage, mutation of raw captures, mutation of stored bars, database/schema changes, or background fetching.
- Indicators, drawings, zoom/pan, streaming ticks, Level II, or production-grade charting-library replacement.
- Treating stale evidence as current or substituting daily candles for an unavailable intraday interval.

## Protected Areas

Core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, and source market-data artifacts remain protected.

## Acceptance Criteria

- The host advertises and serves a versioned read-only chart snapshot command with validated symbol and interval arguments.
- Daily candles come only from valid stored daily OHLC records; intraday candles come only from stored minute bars.
- `5m` and `15m` aggregation preserves first open, maximum high, minimum low, last close, summed volume, day boundaries, and chronological order.
- Available stored candles render in the WPF Chart pane with bodies, wicks, and volume.
- Stale candles remain visible but are labeled `STALE` with source and as-of evidence.
- Missing, malformed, unsupported, or insufficient data produces an explicit non-available state and never calls the mock candle client.
- Candidate selection, interval changes, linked charts, and pinned chart context request the correct symbol/timeframe.
- No score, readiness, replay, planning, risk, simulation, broker, Paper, or Live behavior changes.

## Evidence Required

- Python tests cover daily mapping, one-minute mapping, 5/15-minute aggregation, stale state, missing symbol/source, malformed source, input validation, and source-file non-mutation.
- Host tests prove chart payload delivery, argument validation, idempotent request identity, no collection cycle, and no execution capability.
- .NET tests cover JSON mapping, stale/unavailable labels, selection and interval refresh, linked/pinned chart context, and no mock-engine fallback.
- Python compileall, Release .NET build, focused tests, bounded broader tests, protected-path review, and second-pass diff review pass.
- A physical WPF screenshot proves a nonblank chart with visible candle bodies/wicks, source label, selected symbol, interval, and simulation-only/live-locked language.

## Evidence Depth / Hard Chew Requirements

- Build the full contract path before judging labels alone.
- Run focused failure-path tests before broader bounded discovery.
- Verify local source files are byte-identical before and after chart reads.
- Inspect the final WPF output at desktop resolution and confirm candle pixels are not blank or clipped.
- Review the final diff for provider calls, generated data, secret handling, broker/execution terms, and protected paths.
- Perform a narrow fix pass for any defect found during self-review, then rerun the affected proof.
- Commit implementation, tests, Goal Charter, and final roadmap evidence together only after all acceptance criteria pass.

## Smallest Safe Implementation Slice

One validated chart snapshot command backed by existing local daily/minute JSON evidence, one WPF mapper/client, and primary/linked pane refresh using the existing candle renderer.

## Open CEO Decisions

- None for this read-only slice. A later task may decide whether to add live market-data streaming or a richer chart library.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove real chart behavior rather than labels.
- [x] Evidence depth includes runtime, failure, and visual proof.
