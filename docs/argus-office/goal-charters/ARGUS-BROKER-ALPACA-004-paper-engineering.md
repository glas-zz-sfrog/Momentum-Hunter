# ARGUS-BROKER-ALPACA-004 Goal Charter

## Goal

Produce the first prospective Momentum Hunter-generated Canary Alpaca Paper
decision through trusted evidence, DATA-004 planning, Paper Risk, DATA-005B
allocation, real Paper order/fill/protection truth, and immutable terminal
evidence.

## Operator Value

Momentum Hunter can now truthfully record either `PAPER_TRADE_CREATED` or
`NO_TRADE` from the current prospective opening candidate supply. The lane
proves engineering behavior; it is not the final continuous-intraday strategy
sample and is not evidence of profitability.

## Boundaries

- Alpaca Paper Canary lane only; exact Paper host only.
- Schwab remains authoritative for strategy market evidence.
- No Alpaca live, Schwab order, Shadow, UI, score, alert, schema, or money move.
- No retrospective decisions or backfill.
- No order without trusted report/quote/plan/risk/allocation evidence.
- No activation until integration, service refresh, sample freeze, and exact-head
  job installation pass.

## Acceptance Evidence

- Full compile passes.
- Focused entry, stop, exit, recovery, idempotency, mutex, timing, manifest, and
  negative-path tests pass.
- Complete Python discovery passes.
- Diff, protected-path, endpoint, and secret scans pass.
- First provider result is preserved prospectively as trade or no-trade.

Status: `IMPLEMENTED_PENDING_INTEGRATION_AND_PROSPECTIVE_ACTIVATION`.
