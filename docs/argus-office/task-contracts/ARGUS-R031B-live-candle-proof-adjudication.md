# ARGUS-R031B - Live Candle Proof And Adjudication

## Historical Status

`COMPLETE / ACCEPTED_WITH_LIMITATIONS`

This is the current-master preservation of the task contract originally stored
on source branch `bae053b`. Source SHA-256:
`3B36A7CDEF94A2D98A105BB3001A8FF8F9B80517683C5DE321CABA48AB47ABD9`.

The task executed during market hours and was integrated through `404c589`; the
current-master closeout is `06b3fa7`. This contract is historical evidence, not
a Ready task and not permission to open another Schwab session.

## Original Objective

Execute the nonpersisting Schwab candle observer and adjudicate which Streamer
and price-history behaviors were actually proven for the sole approved account.
The proof was required to observe SPY, IWM, and one deterministic Hunter
candidate; preserve provider and receipt chronology; compare OHLCV with later
`/pricehistory`; and leave every unobserved behavior explicitly unverified.

## Safety Boundary

- Read-only market data only.
- No position, preview, order, or transaction request.
- No production candle persistence during the proof.
- No service, scheduler, Engine Host, WPF, Shadow, selector, Risk Governor,
  TradePlan, FakeBroker, or broker-order mutation.
- No token, credential, full account number, or full account hash in evidence.
- No provider guarantee inferred from SDK/community behavior.

## Observation Contract

The proof recorded:

- connection/authentication/subscription chronology;
- redacted account-invariant result;
- acknowledgements, entitlement, and subscription identity;
- every Streamer candle update with source, symbol, provider timestamp, local
  receipt timestamp, receipt sequence, OHLCV presence, repeated-minute identity,
  changed fields, and arrival order;
- later price-history request/response clocks and matching minute identity; and
- exact OHLCV differences, missing/duplicate/corrected minutes, and latency to
  comparable history evidence.

Each question had to be classified `VERIFIED`, `DISPROVEN`,
`PARTIALLY_VERIFIED`, or `UNVERIFIED`; one clean minute could not prove finality,
correction behavior, capacity, or reconnect guarantees.

## Observed Result

- Symbols: SPY, IWM, and deterministic rank-one Hunter candidate NVDA.
- Duration: bounded 15-minute market-hours observation.
- Comparable rows: 48 complete one-minute OHLCV rows.
- OHLC: all comparable values matched `/pricehistory`.
- Volume: five NVDA stream values contained fractional tails relative to
  history, so stream volume was not accepted as completed canonical authority.
- Result: `ACCEPTED_WITH_LIMITATIONS`.
- Canonical consequence: price history reconciles completed bars; Streamer
  versions remain preserved but stream-only canonicality is false.

The implementation also repaired observed acknowledgement, keyed-symbol,
field-map, and zero-sequence response shapes before current-master integration.

## Behaviors Not Generalized By The Proof

The proof did not convert a bounded successful session into broad guarantees
for finality markers, all correction timing, practical subscription scale,
halts, all extended-hours behavior, or every disconnect/reconnect condition.
Those remain explicit provider/runtime limitations and must fail visibly where
unobserved.

## Canonical Follow-On

R032 implemented bounded source-specific persistence and price-history
reconciliation. R032B/R032C added historical depth and automatic cache-first
loading. R033 added provider-free Engine Host/WPF consumption. Their current
status is maintained in
[CONTINUOUS_INTRADAY_IMPLEMENTATION_SEQUENCE.md](CONTINUOUS_INTRADAY_IMPLEMENTATION_SEQUENCE.md).

Detailed release evidence remains in
[ARGUS-R031B-schwab-candle-market-hours-proof.md](../reports/releases/ARGUS-R031B-schwab-candle-market-hours-proof.md).
