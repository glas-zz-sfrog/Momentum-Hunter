# ARGUS-SCHWAB-OVERNIGHT-API-PROBE-001

## Goal

Run the smallest fingerprinted, read-only Schwab probe needed to determine
whether the Individual Trader API supplies current true-overnight market data
between 20:00 and 04:00 Eastern.

## Scope

- Observe fixed symbols `SPY`, `QQQ`, `NVDA`, `AAPL`, and `MU`.
- Poll quote snapshots for approximately 15 minutes.
- Query one-minute price history for the overnight window.
- Observe bounded `LEVELONE_EQUITIES` and `CHART_EQUITY` Streamer traffic.
- Persist incremental, sanitized, fingerprinted evidence.
- Make no account, position, order, Alpaca, Paper, or live-execution call.
- Change no provider role, runtime, service, scheduler, manifest, credential, or
  production evidence.

## Acceptance

1. Bind the probe to exact Git source, installed-product identity, service
   state, and manifest hashes.
2. Preserve provider timestamps separately from local receipt and Streamer
   envelope timestamps.
3. Classify quote, bid/ask, mark, trade, price-history, streaming-quote, and
   streaming-candle capability independently.
4. Verify the exact HTTP route inventory and zero account/position/order calls.
5. Scan evidence against credential-shaped patterns and known live local secret
   values without disclosing those values.
6. Preserve failed harness attempts as failures of the harness, not provider
   conclusions.
7. Produce an immutable capability matrix and plain-language final report.

## Final Classification

`SCHWAB_TRUE_OVERNIGHT_API_NOT_AVAILABLE` only when successful, independently
verified evidence shows no current quote, trade, or candle source after the
ordinary 20:00 Eastern extended-hours boundary.
