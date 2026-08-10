# ARGUS-SCHWAB-AFTER-HOURS-001 Goal Charter

Status: `SCHEDULED_EXTERNAL_TIME`

## Goal

Prove during Tuesday's actual 4:00-8:00 PM Eastern session whether Schwab
delivers fresh, complete one-minute `CHART_EQUITY` OHLCV and compatible
`/pricehistory` evidence for SPY, QQQ, and NVDA.

## Operator Value

Momentum Hunter needs observed after-hours behavior before treating Schwab's
documented extended-hours capability as usable market structure. The proof
must distinguish successful transport from fresh, reconcilable candle data.

## Boundaries

- Read only the pinned Schwab account ending `2573` and market-data endpoints.
- Request no positions, orders, previews, or order capability.
- Write proof only outside the repository and production data stores.
- Do not invoke or change the service, Engine Host, WPF, Shadow, scoring,
  readiness, TradePlan, Risk Governor, candle stores, or scheduled opening jobs.
- Do not grant candle canonicality or production persistence authority.

## Acceptance

- Run independent early and late after-hours observations on 2026-08-11.
- Observe exactly SPY, QQQ, and NVDA for 15 minutes per run.
- Preserve quote provider/receipt clocks, all Streamer updates, complete OHLCV,
  price-history requests, and stream/history reconciliation.
- Fail visibly on stale/missing symbols, non-extended bars, OHLC differences,
  account mismatch, wrong date/window, dirty/wrong Git, or source-hash drift.
- Preserve each valid proof write-once and redact secrets/account identity.

## Scheduled Proof

- Early: 2026-08-11 15:05 Central / 16:05 Eastern.
- Late: 2026-08-11 18:35 Central / 19:35 Eastern.
- Each task is one-time, wake-enabled, limited interactive, bounded to 25
  minutes, and configured for two transport-level retries at two-minute
  intervals.
- Codex is not required. The machine may be locked, but Steven's Windows
  session must remain logged in so current-user DPAPI credentials are usable.
