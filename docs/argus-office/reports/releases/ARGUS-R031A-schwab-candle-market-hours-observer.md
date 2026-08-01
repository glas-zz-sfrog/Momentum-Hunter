# ARGUS-R031A Schwab Candle Market-Hours Observer

Status: `IMPLEMENTED_PENDING_LIVE_MARKET_HOURS_RUN`

## Scope

ARGUS-R031A adds the one-shot, nonpersisting observer required to close R031's
remaining live behavior questions. It does not collect production candles,
populate charts, alter Monday automation, or authorize R032 persistence.

## Runtime Boundary

- The CLI is a deterministic zero-network plan unless `--execute` is supplied.
- The PowerShell runner is likewise plan-first, pins module imports to this
  isolated worktree from any current directory, and requires `-Execute` for
  live use.
- Live use requires an explicit `.json` output outside the repository and
  refuses overwrite.
- Observation is bounded to ten symbols and three through fifteen minutes on
  an open NYSE session; regular hours are the default.
- Account revalidation requires one authorized account, ending `2573`, the
  unchanged encrypted identity, and internal type `INDIVIDUAL_CASH`.
- Account details can return balance fields, but values are suppressed. No
  positions or orders are requested and order transmission is unavailable.
- Exact external surfaces are `GET /trader/v1/accounts/accountNumbers`, one
  account-details GET without positions, `GET /trader/v1/userPreference`,
  `wss://streamer-api.schwab.com/ws`, and bounded explicit-window
  `GET /marketdata/v1/pricehistory` calls.
- There is no service, scheduler, Engine Host, WPF, production-data,
  FakeBroker, real-broker, position, order, or transmission integration.

## Evidence Behavior

The observer records connection and subscription chronology, every accepted
`CHART_EQUITY` candle version, provider time, local receipt time, first-candle
latency, revisions, replays, out-of-order arrivals, observed gaps, and bounded
price-history reconciliation. Heartbeats are tolerated. Candle data arriving
with or immediately before the subscription acknowledgement is preserved.
Per-symbol history failure is explicit and does not discard the primary
Streamer proof. A socket failure after candle receipt preserves those candles
and adds an explicit disconnect finding. Output excludes tokens, credentials, full account identity,
account hash, balance values, and raw Streamer bootstrap identifiers.
Every proof records the SHA-256 identity of the observer and candle-contract
modules, the expected WebSocket dependency version, and the version actually
imported. Source identity is checked before and after the observation, and any
change fails without producing ambiguous proof. Any version other than
`websocket-client==1.9.0` fails before the socket is opened.

## Verification

- Python compileall: PASS.
- Focused observer tests: 23 PASS.
- Schwab/candle boundary regression: 210 PASS.
- Full Python discovery: 1,081 PASS.
- `websocket-client==1.9.0`: imported successfully from an isolated external
  target; canonical `.venv` unchanged.
- Default CLI plan: PASS, with network, persistence, service, Engine Host, WPF,
  positions, orders, and transmission all disabled or unavailable.
- PowerShell runner parse and unrelated-directory plan: PASS. The runner
  supplied exactly `SPY`, `IWM`, and `CRWV`, called no network, wrote no
  production data, and left transmission unavailable.
- Protected-path and secret/capability scans: PASS before commit.
- Canonical Monday checkout/runtime nonmutation: PASS. Canonical Git remains
  clean and synchronized at `c546242`; the service is Running/Automatic with a
  fresh heartbeat, Healthy Engine Host, 30 pending opening jobs, zero failed
  opening jobs, zero Shadow jobs, transmission `UNAVAILABLE`, and unchanged
  manifest SHA-256
  `636274F988D89BD19AF7BB84201D64DBC175E647AF670041CFD8A2B81D388638`.

## Remaining Proof

Run the observer during market hours for SPY, IWM, and one current Hunter
candidate after Monday's opening evidence is preserved. Review entitlement,
arrival delay, repeated current-minute updates, apparent minute completion,
late corrections, volume behavior, gaps, and Streamer-versus-history results.
Until then, R031 remains pending, R032 production collection stays not started,
and R033 chart integration stays blocked.
