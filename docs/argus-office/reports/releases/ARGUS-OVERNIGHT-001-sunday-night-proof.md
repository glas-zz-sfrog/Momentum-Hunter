# ARGUS-OVERNIGHT-001 Sunday-Night Capability Proof

> Read-only context research. No account, position, order, Shadow, strategy, or production-store action occurred.

- Observation: `2026-08-10T03:31:42.232622+00:00` to `2026-08-10T03:31:47.693483+00:00`
- Symbols: `SPY, QQQ, NVDA`
- Feed identity: `DERIVED_OVERNIGHT`
- Context usefulness: `USEFUL_WITH_LIMITATIONS`
- Execution authority: `UNVERIFIED`
- Canonical strategy authority: `NOT_GRANTED`

## Capability Adjudication

- `OVERNIGHT_DATA_AVAILABLE`: `PASS`
- `OVERNIGHT_1M_CANDLES`: `PASS`
- `OVERNIGHT_VOLUME`: `PASS`
- `OVERNIGHT_QUOTES`: `PASS`
- `OVERNIGHT_TRADES`: `PASS`
- `FEED_IDENTITY`: `DERIVED_OVERNIGHT`
- `BOATS_EVIDENCE_AVAILABLE`: `True`
- `CONTEXT_USEFULNESS`: `USEFUL_WITH_LIMITATIONS`
- `EXECUTION_AUTHORITY`: `UNVERIFIED`
- `CANONICAL_STRATEGY_AUTHORITY`: `NOT_GRANTED`

## Historical Overnight Bars

| Symbol | Bars | First | Latest | Age (s) | High | Low | Volume | Missing | Duplicates |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SPY | 111 | 2026-08-10T00:00:00+00:00 | 2026-08-10T03:10:00+00:00 | 1307.613361 | 773.6 | 771.82 | 55263 | 80 | 0 |
| QQQ | 157 | 2026-08-10T00:00:00+00:00 | 2026-08-10T03:15:00+00:00 | 1007.657988 | 724.77 | 721.42 | 121486 | 39 | 0 |
| NVDA | 123 | 2026-08-10T00:00:00+00:00 | 2026-08-10T03:14:00+00:00 | 1067.692482 | 225.13 | 223.9 | 219226 | 72 | 0 |

## Limitations

- Latest context uses Alpaca's derived overnight feed.
- Historical BOATS evidence is delayed by provider plan semantics.
- Sparse overnight sequences contain minutes without returned bars.

Evidence fingerprint: `7c661835c81b4441473511c055efb4a46495e47cb92c04dce8f8e096c8dd4dac`
