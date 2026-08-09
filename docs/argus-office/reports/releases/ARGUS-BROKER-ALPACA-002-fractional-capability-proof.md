# ARGUS-BROKER-ALPACA-002 Fractional Capability Proof

## Classification

`IMPLEMENTED_PENDING_INTEGRATION_AND_MARKET_HOURS_LIFECYCLE_PROOF`

## Scope

This slice adds a provider-neutral capability registry, an isolated exact-host
Alpaca Paper adapter, and a bounded direct proof for fractional limit creation,
client-order recovery, and cancellation. It is stacked on secure onboarding
commit `39576d9` and is not installed or connected to Momentum Hunter runtime.

## Direct Paper Evidence

The final preflight observed the Canary lane as active and usable with `$100`
cash, `$100` buying power, fractionable/tradable SPY, zero positions, and zero
open orders. The bounded proof then:

1. Submitted `0.5` SPY shares at a deliberately nonmarketable `$2.00` limit.
2. Recovered the same provider order through the exact client-order ID.
3. Canceled the order.
4. Confirmed zero final positions and zero final open orders.

The secret-free write-once local evidence is:

- Proof ID: `alpaca-frac-limit-cancel-7c9f61504ae047a89e4cd3c6520e50cd`
- Classification: `FRACTIONAL_LIMIT_CANCEL_PROVEN`
- Provider evidence SHA-256: `BCCE4479632CC45A6CCAB1DA71E4689C1E6C327CBD1BF13D1F9E45855AAD0BCD`
- Implementation SHA-256: `7C1DA818FE702AD537995D56F46F692EBB15CA1A8C9C0DD5C869F88A088B0D16`
- File SHA-256: `9FBB5E5570E228C4E2D8F28C951289AF4666580493B0EFDF50647651EA1DB9D1`
- Local path: `C:\Users\steve\AppData\Local\MomentumHunter\Alpaca\proofs\alpaca-frac-limit-cancel-7c9f61504ae047a89e4cd3c6520e50cd.json`

The proof contains no credential, API header, account number, account hash, or
account identity. It is not tracked by Git.

## Capability Adjudication

Proven by this slice:

- Exact Alpaca Paper environment and host boundary.
- Fractional quantity at `0.5` shares.
- Fractional limit order acceptance.
- Exact client-order ID lookup.
- Cancellation of the accepted fractional limit order.

Still unproven or unknown:

- Nine-decimal precision depth and provider minimums.
- Fractional market and filled-limit behavior.
- Stop, stop-limit, profit-taking, bracket, OCO, and OTO behavior.
- Replace semantics beyond synthetic contract tests.
- Partial fills, status streaming, and interruption recovery against Alpaca.
- Fractional position recovery, exact liquidation, and forced flat.
- Broker-resident protective-order safety.

## Safety Boundary

- The adapter accepts only `https://paper-api.alpaca.markets`.
- The Alpaca live host is structurally rejected.
- Only the `CANARY_REALISTIC` credential lane is accepted.
- The `STRATEGY_RESEARCH` lane remains disabled and has no credential.
- Mutation requires an exact internal confirmation, an owned client-ID prefix,
  an allowlisted side, and a proven maximum notional.
- Ambiguous submission failure is not automatically retried.
- Terminal cancellation is idempotent.
- Provider client-ID contradictions fail closed.
- No Alpaca file is imported or called by Engine Host, Shadow, service,
  scheduler, WPF, FakeBroker, or production execution paths.

## Verification

- Python compileall: pass.
- Focused Alpaca capability tests: `21 / 21` pass.
- Onboarding/allocation/autonomy/Shadow bounded regressions: `151 / 151` pass.
- Full Python discovery: `1,359 / 1,359` pass in 204.082 seconds.
- `git diff --check`: pass.
- Direct secret-pattern scan of the proof: zero hits for API headers, account
  identity fields, key/secret labels, and credential-shaped Paper keys.

## Protected Areas

No scoring, readiness, RVOL, TradePlan, account policy, Shadow sample, capture,
Schwab market data, scheduler, service, Engine Host, WPF, database/schema,
package, production configuration, raw evidence, or generated production report
behavior changed. No live order was authorized or transmitted.

## Next Slice

Create a separate market-hours Alpaca Paper lifecycle task for fills,
protective orders, replace/cancel-resubmit, partial fills, exact liquidation,
restart/reconciliation, and network interruption. Do not integrate this adapter
into allocator, Shadow, service, or a Paper strategy sample until those
capabilities are independently adjudicated.
