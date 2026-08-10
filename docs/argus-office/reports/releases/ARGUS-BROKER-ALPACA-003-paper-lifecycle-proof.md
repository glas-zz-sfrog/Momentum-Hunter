# ARGUS-BROKER-ALPACA-003 Paper Lifecycle Proof

## Classification

`COMPLETE`

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
- automatic CLI emission of the adjudicated registry after success without
  mutating the persisted source report;
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
- Lifecycle tests: `21 / 21` pass.
- Focused onboarding/adapter/lifecycle stack: `77 / 77` pass.
- Adjacent Paper/onboarding/allocation/TradePlan/simulation tests:
  `151 / 151` pass.
- Full Python discovery: `1,391 / 1,391` pass.
- `git diff --check`: pass.
- Protected-path scan: no Engine Host, scheduler, service, Shadow, scoring,
  readiness, schema, package, WPF, or production configuration files changed.
- Secret scan: zero Paper-key, AWS-key, OpenAI-key, or live-host URL hits.
- Runtime import scan: no existing runtime imports the lifecycle harness or
  Alpaca Paper adapter.

## Direct Provider Evidence

On 2026-08-10 at 12:32 Central, the exact Paper-only harness ran proof
`alpaca-paper-lifecycle-78aaade645ee4fd697a338d3` against SPY:

- `$1.00` market entry filled `0.00128035` share at `$773.226`.
- A fractional stop and stop-limit were accepted and canceled.
- A fractional limit target was accepted, replaced by price, and canceled.
- Exact liquidation sold `0.00128035` share at `$773.206`.
- Persisted final state and a separate post-run read both found zero positions
  and zero open orders.
- Final report classification: `ALPACA_PAPER_LIFECYCLE_PROVEN`.
- Plan SHA-256:
  `405FC8E32E2EBE2704DE326745C2E791B4EB7538ED249AC23613748B8F75EB4C`.
- Final SHA-256:
  `A1A4CDDFC60BF03DDC7D23B0F9AF548F64B107DF34E88287477E548B75A54414`.
- Exact stored credential values were compared locally against the evidence;
  neither credential nor account identity was present.

## Operational State

Canonical `master` and `origin/master` contain the directly proven A001-A003
stack. The installed automation service remains Running/Automatic. The
successful August 10 opening receipt is preserved, and 24 future opening jobs
from August 11 through September 14 are pinned to the final synchronized
closeout head. Tuesday is `PENDING`, zero Shadow jobs are enabled, and order
transmission remains `UNAVAILABLE`. No service restart, Engine Host command,
Shadow action, production-data mutation, or live brokerage action occurred.

## Capability Truth

Direct evidence promotes Paper environment, fractional quantity, market,
limit, stop, stop-limit, price replacement, cancellation, client-order
identity, and exact fractional liquidation. Partial-fill and provider restart
recovery remain synthetic-only because neither condition occurred in the direct
run. Bracket/OCO/OTO, streaming, extended-hours execution, and broker-resident
linked protection remain outside this slice and fail closed.

The offline adjudicator will promote only Paper environment, fractional
quantity/market/limit/stop/stop-limit, price replacement, cancellation, and
client-order identity when the final report contains the exact successful
provider receipt and lifecycle chain. It does not treat a classification label
alone as proof and does not infer native take-profit, bracket, OCO, OTO,
streaming, overnight, or linked-protection support.

## Next Action

The verified A001-A003 stack is integrated on canonical `master`, backed up,
and operationally repinned. Resume provider-neutral DATA-005B allocation work.
Do not wire a Paper strategy sample until the allocation, Risk Governor,
ledger, and policy gates are explicitly versioned and tested.
