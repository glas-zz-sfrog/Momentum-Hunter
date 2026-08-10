# ARGUS-OVERNIGHT-001 Goal Charter

Status: PROVEN_WITH_LIMITATIONS

## Goal

Determine whether Alpaca supplies useful Sunday-night SPY, QQQ, and NVDA market context through read-only market-data endpoints.

## Boundaries

- Alpaca evidence is `CONTEXT / RESEARCH` only.
- Schwab remains canonical strategy market-data authority.
- Use only exact-host `GET` requests to `data.alpaca.markets`.
- Do not request an account, position, order, preview, cancel, replace, or liquidation.
- Do not modify production stores, runtime, service, scheduler, Shadow, scoring, readiness, TradePlan, Risk Governor, FakeBroker, or WPF.
- Do not expose credentials or account identity.

## Acceptance

- Probe `SPY`, `QQQ`, and `NVDA` during the active Sunday overnight session.
- Record latest bar, quote, trade, snapshot, and delayed BOATS historical one-minute evidence where entitled.
- Preserve timing, OHLCV, gap, duplicate, and feed-identity evidence in sanitized write-once JSON and Markdown.
- Add focused parser, session, sanitation, authority, and no-order-capability tests.
- Prove canonical Git, Monday capture, service manifest, Shadow, and order-transmission state remain unchanged.

## Result

- Final classification: `OVERNIGHT_CONTEXT_PROVEN_WITH_LIMITATIONS`.
- Alpaca's derived `overnight` feed returned fresh indicative quotes and delayed latest bars/trades for SPY, QQQ, and NVDA.
- Bounded `boats` historical one-minute bars returned usable OHLCV context; direct latest BOATS calls were not entitled.
- Execution authority remains `UNVERIFIED`; canonical strategy authority remains `NOT_GRANTED`.
