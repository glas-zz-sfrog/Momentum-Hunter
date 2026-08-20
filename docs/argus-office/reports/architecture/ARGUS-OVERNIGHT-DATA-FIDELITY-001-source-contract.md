# OVERNIGHT-DATA-FIDELITY-001 Official Source Contract

Retrieved: `2026-08-20`

This snapshot separates documented provider capability from the live sidecar
observations. It grants no provider, strategy, or execution authority.

## Alpaca Market Data

Official sources:

- <https://docs.alpaca.markets/us/docs/about-market-data-api>
- <https://docs.alpaca.markets/us/docs/245-trading-for-trading-api>
- <https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data>
- <https://docs.alpaca.markets/us/reference/stocklatestbarsingle-1>
- <https://docs.alpaca.markets/us/v1.4.2/reference/stockbarsingle-1>

Documented Trading API market-data tiers:

| Capability | Basic | Algo Trader Plus |
| --- | --- | --- |
| Monthly price | `$0` | `$99` |
| Regular/extended real-time equity coverage | IEX | All US exchanges |
| WebSocket ceiling | 30 symbols | Unlimited |
| Historical request limit | 200/minute | 10,000/minute |
| Historical recency restriction | Latest 15 minutes unavailable | No restriction |

Documented overnight session is `20:00-04:00 ET`. Basic uses
`feed=overnight` for latest bars, real-time indicative quotes, delayed latest
trades, and snapshots. Basic uses `feed=boats` for historical bars, quotes, and
trades after a 15-minute delay. Algo Trader Plus uses BOATS directly. Documented
market-data WebSocket endpoints are `v1beta1/overnight` and `v1beta1/boats`.

The official Assets API exposes `overnight_tradable`, but it is not on the
market-data host. This task therefore does not call it under the stricter
market-data-only safety boundary.

## Finviz

Official sources:

- <https://finviz.com/help/faq>
- <https://finviz.com/knowledge-base/learn-reference/data-sources-calculations/update-frequency>
- <https://elite.finviz.com/elite>

Elite is `$39.50/month` or `$299.50/year` and advertises real-time quotes and
extended-hours coverage from `04:00-20:00 ET`. The annual price is equivalent
to about `$24.96/month` before tax. Current official pages disagree about the
exact free-delay figure: the FAQ states one minute for stock quotes while the
update-frequency page states 15 minutes for Nasdaq and 20 minutes for
NYSE/AMEX. This task does not resolve that documentation conflict by assumption;
the live checkpoint preserves observed behavior and current unauthenticated
access separately.

## Massive Stocks

Official sources:

- <https://massive.com/pricing?product=stocks>
- <https://massive.com/docs/rest/stocks>
- <https://massive.com/docs/websocket/stocks/overview>

| Tier | Monthly price | Recency | Request/capability summary |
| --- | ---: | --- | --- |
| Basic | `$0` | End of day | 5 calls/minute, two years, reference/aggregate-oriented access |
| Starter | `$29` | 15-minute delayed | Unlimited calls, five years |
| Developer | `$79` | 15-minute delayed | Unlimited calls, ten years, broader historical trade access |
| Advanced | `$199` | Real time | Unlimited calls, 20+ years, real-time trades/quotes/WebSockets |

The official stock docs describe consolidated US coverage and a full-market
snapshot covering more than 10,000 active tickers. No Massive credential or
live request is used in this task; these tiers are benchmark-only.

## Schwab / thinkorswim

Official sources:

- <https://www.schwab.com/trading>
- <https://www.schwab.com/stocks/extended-hours-trading>
- <https://www.schwab.com/trading/thinkorswim/desktop>
- <https://developer.schwab.com/products/trader-api--individual>

Schwab advertises thinkorswim 24/5 access for 1,300+ stocks and ETFs and says
the platform suite is free with a Schwab account. The documented platform
session includes overnight trading; regular extended premarket starts at
`07:00 ET` and after-hours runs to `20:00 ET`.

Those platform claims do not prove Trader API overnight quote, history, or
Streamer behavior. Public Schwab product pages do not publish an equivalent
overnight Trader API contract. This experiment must classify the API only from
bounded physical evidence, and it must not refresh the credential shared with
production merely to obtain that evidence.

## Authority Boundary

- Official documentation is a capability claim, not a live-fidelity result.
- Live observations remain provider/feed specific.
- No source is averaged, voted, or promoted to canonical authority here.
- No paid subscription is authorized.
