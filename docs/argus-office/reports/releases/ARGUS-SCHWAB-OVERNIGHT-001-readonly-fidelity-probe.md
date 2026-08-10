# ARGUS-SCHWAB-OVERNIGHT-001 Read-Only Fidelity Probe

## Classification

`SCHWAB_OVERNIGHT_DATA_INSUFFICIENT`

Role adjudication: `ALPACA_DERIVED_FILLS_REAL_SCHWAB_GAP`.

Schwab remains canonical for its already-proven regular-session market-data
roles. This probe grants Schwab no Sunday-night context authority and grants no
provider execution, ranking, breakout-trigger, or TradePlan authority. Alpaca
retains only its separately proven, delayed `CONTEXT / RESEARCH` role.

## Observation

- Window: 2026-08-09 23:09:32 through 23:14:35 Central (300 seconds).
- Schwab session window under test: Sunday 19:00 through Monday 03:00 Central.
- Symbols: SPY, QQQ, and NVDA only.
- Worktree: `C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-SCHWAB-OVERNIGHT-001-readonly-fidelity-probe`.
- Branch: `codex/ARGUS-SCHWAB-OVERNIGHT-001-readonly-fidelity-probe`.
- Shared canonical base: `1d0ca95a24b52d5c19e0866914e69880c07a13f5`.
- Account bootstrap invariant: exactly one authorized account, ending `2573`, type `INDIVIDUAL_CASH`, bound identity matched.

## Schwab Evidence

The exact-host `/marketdata/v1/quotes` request succeeded and the Streamer
accepted one `CHART_EQUITY` subscription. Connectivity therefore passed, but
data fidelity did not.

| Symbol | Quote age at receipt | Quote state | Stream observations | Newest stream age at stop | Explicit price-history bars |
| --- | ---: | --- | ---: | ---: | ---: |
| SPY | 187,783.193 s | Friday close / outside overnight | 1 | 188,135.606 s | 0 |
| QQQ | 187,775.717 s | Friday close / outside overnight | 1 | 188,135.606 s | 0 |
| NVDA | 187,776.205 s | Friday close / outside overnight | 1 | 188,135.606 s | 0 |

The initial Streamer payload contained one complete OHLCV row per symbol for
Friday 18:59 Central. During the following five minutes:

- no Sunday-night candle arrived;
- no current-minute revision arrived;
- no duplicate, out-of-order, reconnect, or replay event occurred;
- no current-session high, low, or useful current-session volume could be derived.

The explicit-window `/marketdata/v1/pricehistory` requests covered Sunday
19:00 Central through the end of the observation with extended hours enabled.
All three HTTP requests succeeded but returned zero bars. Consequently, there
were zero comparable Streamer/history minutes and no OHLCV agreement claim can
be made. The initial Friday records are retained as evidence of server behavior
and are not misclassified as Sunday-night data.

The quote response reported real-time entitlement flags, but provider bid/ask
clocks and security states showed old, closed-session evidence. This proves
that a successful response and a `realtime` flag are insufficient freshness
evidence by themselves.

## Fidelity Answers

1. Sunday-night Schwab quotes available: **No useful current-session quotes.** The endpoint responded with Friday-close bid/ask values.
2. Bid/ask freshness: approximately 187,776 to 187,783 seconds old at receipt.
3. Sunday-night `CHART_EQUITY` candles: **Not observed.** Only one Friday-close seed row arrived per symbol.
4. Newest candle age: approximately 188,136 seconds at observation stop.
5. Current-minute updates: **Not observed.**
6. Volume: populated only on the stale Friday seed rows; no Sunday-night volume was available.
7. Missing minutes: current-session absence is provider/entitlement behavior or an API coverage gap; sparse-market behavior cannot be distinguished because no Sunday-night row existed.
8. Sunday-night `/pricehistory`: HTTP success with zero bars for every symbol.
9. Stream/history agreement: indeterminate; zero comparable minutes.
10. Session/time-zone boundaries: request and receipt clocks were sane, HTTPS clock proof passed, and stale rows were correctly outside the overnight session.
11. Sunday-night high/low: unavailable and not useful.
12. Relative fidelity: materially less fresh and less complete than Alpaca OVERNIGHT-001 for this window.

## Alpaca Comparison

The preserved Alpaca proof was observed earlier the same Sunday night and is
not blended with Schwab evidence.

| Measure | Schwab | Alpaca derived overnight |
| --- | --- | --- |
| Fresh quote age | About 52 hours | SPY 0.288 s; QQQ 0.097 s; NVDA 3.421 s |
| Latest candle age | About 52 hours | About 16.8 to 21.8 minutes |
| Historical one-minute bars | 0 for all symbols | SPY 111; QQQ 157; NVDA 123 |
| Current-session OHLCV | Unavailable | Available with populated volume |
| Current-session high/low | Unavailable | Available for all three symbols |
| Limitations | No Sunday-night data observed | Derived feed; delayed bars; sparse missing minutes |

Alpaca's bounded historical evidence reported:

- SPY: high 773.60, low 771.82, volume 55,263, and 80 sparse minutes.
- QQQ: high 724.77, low 721.42, volume 121,486, and 39 sparse minutes.
- NVDA: high 225.13, low 223.90, volume 219,226, and 72 sparse minutes.

This comparison supports a narrow role only. Alpaca data remains context for
overnight research and must not be substituted into regular-session canonical
bars or used to authorize execution, rank candidates, trigger breakouts, or
create TradePlans without a separate task and decision.

## Evidence And Safety

- Raw proof: `ARGUS-SCHWAB-OVERNIGHT-001-proof.json`.
- Raw proof SHA-256: `D576443A67BC4092613AD072620675DA71255A8DF7133329A07AAA396F624804`.
- Raw evidence fingerprint: `73CDEFB814102BE161EEF0CD84A179C785CEA6CA7EA72AF55985A433578D406B`.
- Alpaca comparison proof SHA-256: `CA85D8351981D951ED7780949CF36E7A7DACA9377FCA6FEDB51E86A55A6B8984`.
- Symbols were fixed to SPY, QQQ, and NVDA.
- Account details were used only for the existing Streamer bootstrap guard; balances were suppressed.
- Positions, orders, previews, broker adapters, service, scheduler, Shadow, and production persistence were not invoked.
- Credential material, full account identity/hash, and tokens are absent from the proof.
- Order transmission remained `UNAVAILABLE`.

The live proof preceded a narrow post-run reporting hardening: revised versions
of the same candle minute are now retained individually but counted once in bar
and cumulative-volume summaries. This did not alter or rewrite the immutable
live evidence, which contained one observation per symbol and no revisions.

## Recommendation

Retain Alpaca's current narrow overnight `CONTEXT / RESEARCH` role and preserve
Schwab's regular-session canonical role. Do not add provider blending. Do not
grant Alpaca or Schwab overnight execution authority. This result blocks only
SCHWAB-OVERNIGHT-001 adjudication and does not block A003 Paper acceptance,
DATA-005 provider-neutral allocation, Monday capture, or other bounded work.
