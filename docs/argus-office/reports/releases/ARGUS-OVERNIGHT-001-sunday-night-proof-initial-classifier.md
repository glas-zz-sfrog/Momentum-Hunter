# ARGUS-OVERNIGHT-001 Sunday-Night Capability Proof

> Read-only context research. No account, position, order, Shadow, strategy, or production-store action occurred.

- Observation: `2026-08-10T03:29:37.999325+00:00` to `2026-08-10T03:29:43.525991+00:00`
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
| SPY | 111 | 2026-08-10T00:00:00+00:00 | 2026-08-10T03:10:00+00:00 | 1183.447215 | 773.6 | 771.82 | 55263 | 80 | 0 |
| QQQ | 156 | 2026-08-10T00:00:00+00:00 | 2026-08-10T03:13:00+00:00 | 1003.482505 | 724.77 | 721.42 | 121384 | 38 | 0 |
| NVDA | 122 | 2026-08-10T00:00:00+00:00 | 2026-08-10T03:07:00+00:00 | 1363.523991 | 225.13 | 223.9 | 218752 | 66 | 0 |

## Limitations

- Latest context uses Alpaca's derived overnight feed.
- Historical BOATS evidence is delayed by provider plan semantics.
- Sparse overnight sequences contain minutes without returned bars.

Evidence fingerprint: `f24be6d6138ed9f4f9e3db7ddaf1b92480f8c224c13841c593f3adf011ca9533`
