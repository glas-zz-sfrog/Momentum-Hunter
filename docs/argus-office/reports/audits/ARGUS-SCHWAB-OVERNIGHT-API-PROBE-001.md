# ARGUS-SCHWAB-OVERNIGHT-API-PROBE-001

## Classification

`SCHWAB_TRUE_OVERNIGHT_API_NOT_AVAILABLE`

The successful fingerprinted attempt ran from
`2026-08-21T02:21:37.936316-04:00` through
`2026-08-21T02:36:39.354310-04:00`. It observed no advancing Schwab quote,
trade, or candle evidence after the ordinary 20:00 Eastern extended-hours
boundary. No provider role changed.

## Source And Evidence

| Identity | Value |
| --- | --- |
| Canonical base | `701e6932645165e5e3d8a38f317dbd0e3d68258f` |
| Successful probe source | `b59cc37eb10a1478781c59ae140a73b7ee5690bd` |
| Integrated task commit | `ff74555f6bb24f6d0368d885c85800cccd91e3f8` |
| Installed product | `e69426b3b7bd179cd62eba2e28a5d0553da47154` |
| Evidence fingerprint | `0417AC70A58B26D8966A5C58F2B8E8B197161AC79FF89EAEDD74F39DB5F32EBB` |
| Capability-matrix fingerprint | `939C1FEFA21A168502803EECD49EBE692935CDD7D9284B6C8ADC78316169E974` |
| Evidence file manifest | `6ABC83D6B38C16347E633F7F8D3C644D414BB16101B0EBA2FBF6E778C1AE7750` |
| Evidence root | `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-SCHWAB-OVERNIGHT-API-PROBE-001` |

Two earlier attempts are preserved separately as probe-harness failures. The
first rejected duplicate price-history event identities before terminalizing;
the second called the wrong local Streamer summarizer signature. Both preserved
incremental evidence and zero account/position/order calls. They are not used
as provider-capability evidence.

## Direct Results

- All five symbols returned 15 HTTP-200 quote snapshots. Every provider
  timestamp and quote field remained frozen.
- SPY's newest quote was `20:00:00.071 ET`; its newest trade was
  `19:59:58.724 ET`. The 71-millisecond boundary timestamp is not treated as
  true-overnight evidence.
- QQQ, NVDA, AAPL, and MU quote/trade timestamps all stopped before 20:00 ET.
- All five price-history responses stopped at `19:59 ET`; zero one-minute bars
  existed after 20:00 ET or after midnight.
- `CHART_EQUITY` acknowledged and returned one three-symbol seed frame whose
  latest candles were `19:59 ET`; no candle advanced.
- `LEVELONE_EQUITIES` acknowledged and returned one seed frame. Momentum Hunter
  has no canonical mapping for its numeric fields, so streaming-quote
  capability remains `UNPROVEN`, not current.
- The successful attempt made 15 quote GETs, five price-history GETs, and one
  Streamer bootstrap GET. Account, position, order, Alpaca, Paper, and live
  order calls were all zero.
- No OAuth refresh was required or attempted; the encrypted auth-state
  fingerprint remained unchanged.

## Capability Matrix

| Data type | Classification |
| --- | --- |
| Quotes | `STALE_EXTENDED_HOURS_ONLY` |
| Bid/ask | `STALE_EXTENDED_HOURS_ONLY` |
| Mark | `STALE_EXTENDED_HOURS_ONLY` |
| Trades | `NOT_AVAILABLE_OVERNIGHT` |
| Price history | `STALE_EXTENDED_HOURS_ONLY` |
| Streaming quotes | `UNPROVEN` |
| Streaming candles | `STALE_EXTENDED_HOURS_ONLY` |

## Verification

- 74 focused and adjacent tests pass.
- A monolithic full-discovery run and its first 50-module bounded batch reached
  their 420-second and 300-second wrapper limits without emitting a test
  failure. They are not claimed as passes and are not needed for this isolated
  audit-tool acceptance; the long-running continuous-runtime group remains a
  residual broad-suite timing limitation.
- Exact source hashes, 15 quote records, five price-history records, baseline
  and result fingerprints, route inventory, and nonmutation invariants pass.
- Secret scan passed against credential-shaped patterns and five known live
  local values without writing those values to evidence.
- Automation, Continuous Runtime, and Continuous Writer services remained
  running; automation and continuous manifests remained unchanged.
- No provider role, product runtime, service, scheduler, manifest, credential,
  account, broker, order, Paper, Shadow, or production evidence changed.

## Decision

Schwab is not suitable as Momentum Hunter's true-overnight canonical source.
The validated Alpaca/Finviz overnight architecture remains unchanged. Schwab's
already-proven premarket, regular-session, and after-hours roles are not
reduced by this bounded result.
