# ARGUS-BROKER-ALPACA-003 Paper Lifecycle Proof

## Classification

`IMPLEMENTED_PENDING_MARKET_HOURS_PROOF`

## Implementation

This stacked feature branch adds a standalone Paper-only lifecycle harness and
hardens the isolated Alpaca adapter with:

- sanitized allowlisted provider receipts;
- exact-position reads;
- quantity-bounded position-reducing orders;
- idempotent submit and replacement recovery by frozen client-order ID;
- contradiction detection for recovered commands;
- market-hours gating and a 30-minute closing buffer;
- a write-once plan created before provider mutation;
- bounded polling, partial-fill recognition, and three finite flatten IDs;
- distant stop, stop-limit, target, replacement, and cancel checks;
- a pure offline capability adjudicator that requires the exact fingerprinted
  identity, event, receipt, and final-flat chain before promotion;
- write-once final/failure evidence outside Git.

The planned direct proof is one `$1.00` notional SPY market entry in the
`CANARY_REALISTIC` Paper lane. It may never contact the live host and is not
wired into any Momentum Hunter trading decision or runtime process.

## Synthetic Evidence

Synthetic tests prove:

1. Closed sessions stop before provider access and before a plan is written.
2. An untouched plan survives reload byte-for-byte; altered scope or hash
   fails closed.
3. A complete fractional entry, stop, stop-limit, target replacement, and
   exact market exit finishes with zero positions and zero open orders.
4. A restart with an existing owned entry and position does not submit another
   entry.
5. Ambiguous submit/replace responses perform one lookup and never blind retry.
6. Partial entry and exit fills are recorded; the latter uses the next frozen
   exit ID and reaches flat.
7. Foreign positions/orders and orphan protective orders block without
   mutation.
8. A provider interruption preserves failure evidence and performs bounded
   cleanup.
9. Final evidence contains no account identity or credential-shaped values.
10. Tampered, dirty, receipt-free, and incomplete lifecycle reports cannot
    promote capabilities; unexercised bracket/OCO/OTO, streaming, and linked
    protection remain unproven.

## Verification

- Compileall: pass.
- Adapter tests: `32 / 32` pass.
- Lifecycle tests: `20 / 20` pass.
- Focused onboarding/adapter/lifecycle stack: `76 / 76` pass.
- Adjacent Paper/onboarding/allocation/TradePlan/simulation tests:
  `151 / 151` pass.
- Full Python discovery: `1,390 / 1,390` pass in 255.889 seconds.
- `git diff --check`: pass.
- Protected-path scan: no Engine Host, scheduler, service, Shadow, scoring,
  readiness, schema, package, WPF, or production configuration files changed.
- Secret scan: zero Paper-key, AWS-key, OpenAI-key, or live-host URL hits.
- Runtime import scan: no existing runtime imports the lifecycle harness or
  Alpaca Paper adapter.

## Operational Nonmutation

Canonical `master` and `origin/master` remain synchronized at `1d0ca95`. The
installed automation service remains Running/Automatic. Its manifest remains
SHA-256 `E99E65A302B97A5D866071C3C1B37C8519972F8D55966EAC08772A1F6F093B47`
with 25 enabled opening jobs and zero enabled Shadow jobs. No service restart,
manifest edit, scheduled-job edit, Engine Host call, production-data access, or
brokerage read/write occurred during synthetic implementation.

## Capability Truth

No remaining provider capability is promoted by this branch yet. Market
entry/fill, stop and stop-limit acceptance, price replacement, partial-fill
behavior, restart reconciliation, and exact liquidation remain
`DOCUMENTED_UNPROVEN` or `UNKNOWN` until one direct regular-market proof passes.
Bracket/OCO/OTO, streaming, extended hours, and broker-resident linked
protection remain outside this slice.

The offline adjudicator will promote only Paper environment, fractional
quantity/market/limit/stop/stop-limit, price replacement, cancellation, and
client-order identity when the final report contains the exact successful
provider receipt and lifecycle chain. It does not treat a classification label
alone as proof and does not infer native take-profit, bracket, OCO, OTO,
streaming, overnight, or linked-protection support.

## Next Action

Commit and back up this feature branch without merging or installing it. In
the next safe regular-market window, run exactly one bounded Canary Paper
lifecycle, inspect the final account for zero positions and zero open orders,
scan the evidence, and adjudicate only the capabilities the provider actually
demonstrates.
