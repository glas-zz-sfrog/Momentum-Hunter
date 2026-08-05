# ARGUS-R031B Schwab Candle Market-Hours Proof

Status: `ACCEPTED_WITH_LIMITATIONS`

## Scope

R031B executed the already-built read-only, nonpersisting Schwab candle observer
for SPY, IWM, and the canonical rank-one 2026-08-05 opening candidate NVDA.
It queried Streamer user preferences, `CHART_EQUITY`, and bounded
`/marketdata/v1/pricehistory` evidence only. It did not request positions or
orders and did not invoke the automation service, Engine Host, WPF, production
candle storage, Shadow selection, FakeBroker, or broker transmission.

## Preserved Proof

- Base path: `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\schwab-candle-market-hours-proof-20260805T165825091Z-NVDA`
- Proof fingerprint: `3BC38136C6388A505F653CC52813CC17FF6A5C786F472E715ACC6FDD4375F14E`
- Proof JSON SHA-256: `A073393BDF24FF2654E59447EE1D7D2B287C415B0E6C66CB077C48318C530A39`
- Adjudication JSON SHA-256: `97424166458C45E8B89F3F5DD355D51DB683CCCC022E6DEA04E6CA415614EDD3`
- Adjudication Markdown SHA-256: `8E21BC1525BD134C0C046C5B8ABD82F1DD31A71EC0A2CF4E84A0881481843B41`
- Manifest SHA-256: `6C332F30C6C99AF6A220996C008A2EC4B125D63BF6547AD0F81B5EAB683B0810`

The proof bundle is outside the repository and is not tracked by Git. Its scan
found no bearer token, access token, refresh token, or client-secret value.
Only the allowed redacted account ending is present.

## Observed Behavior

- Schwab accepted the `CHART_EQUITY` subscription for all three symbols.
- Sixteen one-minute rows arrived per symbol, 48 total.
- Every row contained complete OHLCV values.
- Each symbol-minute appeared once; no replay, revision, out-of-order update,
  or missing streamed symbol was observed.
- First arrival occurred 62.147 to 87.645 seconds after the candle's bar-start
  timestamp. This is approximately two to 28 seconds after minute close for the
  observed sample, not a current forming-minute feed.
- All 48 comparable open, high, low, and close values matched price history.
- Five NVDA stream volume values contained fractional tails; price history
  returned the same whole-number volume values. Both versions are preserved.
- Schwab supplied no explicit candle-finality marker in the observed frames.

## Live-Shape Repair

The live run proved that acknowledgement content may be an object, symbol
identity arrives in `key`, sequence may be zero, and fields 1 through 8 map to
sequence, open, high, low, close, volume, chart time, and chart day. The parser
now accepts that observed shape, rejects conflicting symbol identities and
negative sequences, and validates each live data frame before history work.

## Verification

- Python compileall: pass.
- Focused contract/observer/adjudication suite: 59/59 pass after repair.
- Current-master candle suite: 77/77 pass.
- Affected Schwab/candle/account boundary suite: 223/223 pass.
- Full Python discovery on the proof branch: 1,094/1,094 pass.
- `git diff --check`: pass.
- Protected-path review: no scoring, readiness, alert, TradePlan, broker/order,
  service, Engine Host, WPF, schema, or production-data behavior changed.

## Decision

R031B is accepted for bounded R032 implementation with these mandatory limits:

- Stream bars remain noncanonical until reconciled against price history.
- R032 must preserve stream and history versions rather than overwrite either.
- Current-minute finality, late corrections, reconnect behavior, halt behavior,
  and subscription scaling remain unproven and must fail visibly.
- R032 may not activate WPF candles or remove legacy CRWV evidence; those remain
  R033 and separately approved R034 work.
