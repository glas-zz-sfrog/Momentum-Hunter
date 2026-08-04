# ARGUS-R031B - Live Candle Proof And Adjudication

## Status

`NEXT`; market-hours, read-only, nonpersisting evidence task. It is not the
production collector.

## Objective

Execute the existing R031 nonpersisting Schwab candle observer during a suitable
market window and adjudicate which Streamer and price-history behaviors are
actually proven for the sole approved account.

## Preconditions

- Canonical Git is clean and synchronized.
- The existing R031 branch chain is reconciled by identity:
  `a39086c` is the initial contract, `b96f745` includes/hardens it, and
  `3272476` plus `d6d7217` contain the nonpersisting observer and launch
  hardening on top of provisional R032A `35c59ee`.
- R031A is reused rather than rebuilt: bounded 3-15 minute observation, dry-run
  default, explicit live switch, SPY/IWM/Hunter symbols, account-invariant
  check, login/subscription, every candle version, chronology, anomaly evidence,
  price-history comparison, sanitized no-overwrite output, and pinned
  `websocket-client==1.9.0` dependency.
- No candle branch is treated as canonical runtime merely because it is pushed.
- Exactly one approved account remains bound: ending `2573`, type
  `INDIVIDUAL_CASH`, immutable hash unchanged.
- Any account count, ending, type, hash, permission, position, or authorization
  anomaly stops the task and interrupts Steven before observation continues.
- The proof output directory is temporary or review-only and is not an active
  chart, service, or production candle store.

## Observation Set

- `SPY`
- `IWM`
- One current Hunter candidate selected deterministically from the latest valid
  report and recorded before connection

Do not substitute a remembered or manually attractive candidate after seeing
the feed.

## Required Evidence

For connection and subscription:

- request start and connection time;
- authentication/bootstrap outcome;
- redacted account-invariant result;
- subscription request identity;
- acknowledgement or rejection details;
- entitlement status;
- disconnect, reconnect, and resubscription events; and
- observed symbol or subscription-limit response, if the provider actually
  supplies one.

For every Streamer candle update:

- raw-message SHA-256 or deterministic redacted fingerprint;
- service/source name;
- symbol;
- provider candle timestamp;
- local receipt timestamp;
- receipt sequence;
- OHLCV fields and field presence;
- session/extended-hours indicator if supplied;
- whether the same symbol/minute was seen before;
- changed fields versus the previous update; and
- observed arrival order versus candle order.

For later `/pricehistory` comparison:

- request and response clocks;
- matching symbol/minute identity;
- OHLCV comparison;
- missing, duplicate, shifted, or corrected minute;
- exact difference fields; and
- age from Streamer minute rollover to first matching history evidence.

## Adjudication Values

Every question receives exactly one status:

- `VERIFIED`: direct, repeated evidence supports the bounded claim.
- `DISPROVEN`: observed behavior contradicts the claim.
- `PARTIALLY_VERIFIED`: some symbols/minutes support it, but the contract is not
  general enough to freeze.
- `UNVERIFIED`: the observation did not exercise or resolve the behavior.

Required questions:

1. Is `CHART_EQUITY` entitled for this account?
2. Is one-minute OHLCV delivered for all three symbols?
3. Is the current minute repeated provisionally, or emitted once?
4. What event marks minute rollover, if any?
5. What are observed first-arrival and settled-value latencies?
6. Does volume appear incremental, cumulative, final, or unresolved?
7. Do Streamer OHLCV and `/pricehistory` agree after reconciliation?
8. Are older minutes corrected after apparent completion?
9. What happens on a controlled client-side disconnect/reconnect, if that step
   is separately safe and included in the observer contract?
10. Are extended-hours/session semantics explicit?
11. Are subscription acknowledgements and rejections deterministic?
12. Is a practical subscription limit proven by official response evidence?

One clean minute is insufficient to claim finality, correction behavior,
capacity, or reconnect guarantees.

## Safety And Nonmutation

- Read-only market data only.
- No account, position, preview, order, or transaction request.
- No production candle persistence.
- No service, scheduler, Engine Host, WPF, provider configuration, or official
  Shadow mutation.
- No selector, Risk Governor, FakeBroker command, or TradePlan generation.
- No secret, token, full account number, or full account hash in proof outputs.
- No inferred provider guarantee from SDK source or community documentation.

## Stop Conditions

Stop and report if:

- account invariant differs from the accepted sole-account state;
- the observer would need production writes or another Streamer owner;
- official authentication scope is broader than expected;
- any request path exposes order or transaction capability;
- the existing observer cannot preserve raw arrival order and timestamps;
- market conditions cannot produce a meaningful observation; or
- Git/runtime isolation is not clean.

## Acceptance Criteria

- All three symbols have an explicit observation result.
- Every required adjudication question has one allowed status plus evidence.
- Streamer arrivals and price-history comparison preserve exact clocks and
  source identity.
- Unknown behavior remains `UNVERIFIED`.
- Account and credential evidence is sanitized.
- No runtime or production data path changes.
- The resulting contract is precise enough for R031C to accept, revise, or
  reject each R031/R032A assumption.

## Required Outputs

- Sanitized JSON observation record.
- Human-readable Markdown adjudication.
- Hash manifest for proof inputs and outputs.
- Explicit list of disproven and unresolved assumptions.
- Recommendation: exactly one of `ACCEPTED_FOR_R032_DESIGN`,
  `ACCEPTED_WITH_LIMITATIONS`, `REQUIRES_ADDITIONAL_OBSERVATION`, or
  `REJECTED_BY_PROVIDER_BEHAVIOR`.

## Follow-On Gate

R031B does not merge the old candle branch and does not start production
persistence. `ARGUS-R031C` reconciles accepted R031, R031A observer, and R032A
synthetic contracts onto the current canonical baseline. Only then may R032
implement the central Streamer manager and collector.
