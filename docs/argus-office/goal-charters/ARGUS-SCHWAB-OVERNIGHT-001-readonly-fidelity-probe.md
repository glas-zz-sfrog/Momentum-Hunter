# ARGUS-SCHWAB-OVERNIGHT-001 Goal Charter

Status: IMPLEMENTED_PENDING_MERGE

## Goal

Measure whether the existing read-only Schwab stack provides useful Sunday-night quotes and minute OHLCV for SPY, QQQ, and NVDA before granting Alpaca any permanent overnight role.

## Boundaries

- Reuse the existing sole-account guard, exact Schwab GET endpoints, and CHART_EQUITY WebSocket contract.
- Read only quotes, Streamer bootstrap/candles, and explicit-window price history.
- Do not request positions, orders, previews, permissions, or mutations.
- Do not write production candles or alter the service, scheduler, Shadow, scoring, readiness, TradePlan, Risk Governor, broker adapters, or WPF.
- Keep Schwab overnight authority unverified until the evidence is adjudicated.

## Acceptance

- Observe exactly SPY, QQQ, and NVDA for five to ten minutes during the active overnight session.
- Preserve quote clocks, every CHART_EQUITY version, explicit price-history bars, gaps, revisions, OHLCV, and source agreement.
- Compare the result with Alpaca OVERNIGHT-001 without blending providers.
- Preserve sanitized write-once proof and verify zero trading/runtime capability.

## Result

The bounded live observation completed on 2026-08-09 from 23:09:32 to
23:14:35 Central. Schwab authentication, the quote GET, Streamer connection,
and `CHART_EQUITY` subscription all succeeded, but the returned quote and
initial chart records were Friday-close evidence approximately 52 hours old.
No current Sunday-night candle update arrived, and explicit-window extended-
hours `/pricehistory` returned zero bars for all three symbols.

Final classification: `SCHWAB_OVERNIGHT_DATA_INSUFFICIENT`.

Role adjudication: `ALPACA_DERIVED_FILLS_REAL_SCHWAB_GAP`. Alpaca retains only
the narrow `CONTEXT / RESEARCH` role proven by OVERNIGHT-001; execution,
ranking, breakout-trigger, and TradePlan authority remain ungranted.
