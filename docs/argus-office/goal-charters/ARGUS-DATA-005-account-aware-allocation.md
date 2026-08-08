# ARGUS-DATA-005 Goal Charter - Account-Aware Allocation

## Goal

Replace every executable use of the report's `$500` reference quantity with a
versioned, deterministic, account-aware allocation decision that fails closed
unless an explicit risk policy and fresh, correctly bound account evidence are
both present.

## Operator Outcome

Momentum Hunter can explain exactly why a simulated quantity was authorized or
blocked. Steven can distinguish reference sizing from executable sizing, and a
missing, stale, malformed, mismatched, or over-limit account state cannot create
a FakeBroker order.

## Scope

- Size whole shares from the minimum of fixed/remaining risk, available cash or
  buying power after reserve and commitments, and per-position notional limit.
- Require one ending `2573` `INDIVIDUAL_CASH` account, a redacted binding
  fingerprint, fresh balance and portfolio clocks, and transmission
  `UNAVAILABLE`.
- Freeze policy, account-context, allocation, and quantity fingerprints into
  simulation and Shadow evidence.
- Require Risk Governor evidence before allocation and allocation evidence
  before FakeBroker preview/submission.
- Preserve the report's `$500` result as a visible reference only.
- Provide a pure bridge from already validated Schwab read models; do not fetch
  account data in the allocator.

## Non-Goals

- Do not choose Steven's dollar-risk or account-budget policy.
- Do not install a production account/balance collector in this task.
- Do not change scores, rank, alerts, RVOL, setup identity, TradePlan horizon,
  provider transport, capture scheduling, database/schema, packages, UI, or
  historical evidence.
- Do not create paper/live broker capability, transmit an order, arm Shadow, or
  activate unattended execution.

## Acceptance Criteria

- [x] Missing numeric policy values block rather than use hidden defaults.
- [x] Missing, stale, future, malformed, or mismatched account evidence blocks.
- [x] Account count, ending, type, binding, position, daily-loss, cash, risk,
  and transmission constraints fail closed.
- [x] Executable simulation and Shadow paths never read the `$500` reference
  quantity.
- [x] Authorized quantity is a positive whole-share count and is frozen into
  the ledger and Shadow record.
- [x] Tampered, duplicated, reordered, malformed, or missing allocation
  evidence fails audit.
- [x] Source reports and TradePlans remain immutable.
- [x] DATA-004 same-session setup-aware timing and immutable missed-entry/
  successor-reclaim semantics remain unchanged.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused allocation/simulation/Shadow suites: pass, including 187 combined
  lifecycle tests, 14 live-marking tests, and 117 post-review boundary tests.
- Full Python discovery after all repairs: 1,296/1,296 pass in 1,253.631 seconds.
- Full .NET solution: 251/251 pass.
- `git diff --check`: pass.
- Secret/capability scan: no credential value, provider client, account fetch,
  paper/live adapter, or transmitting method added.
- Protected-path review: only the authorized account-allocation and frozen
  FakeBroker/Shadow evidence boundary changed.

## Status

`COMPLETE` after verified clean fast-forward integration at implementation
commit `a2e5020`. Activation remains blocked on a separately chosen numeric
policy and a fresh read-only account/portfolio snapshot source.

## Goal Steward Review

- [x] The allocator does not invent risk appetite.
- [x] Reference sizing cannot silently become executable sizing.
- [x] Account evidence is redacted, time-bound, and exact-account-bound.
- [x] Tests prove behavior and negative paths rather than label presence.
- [x] No visual acceptance item is required because no UI file changed.
