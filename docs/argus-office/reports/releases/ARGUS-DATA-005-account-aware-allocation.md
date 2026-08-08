# ARGUS-DATA-005 Account-Aware Allocation

Status: `IMPLEMENTED_PENDING_MERGE`

## Result

Momentum Hunter now has a versioned `account-aware-fixed-unit-risk-v1`
allocation contract. Simulation and Shadow cannot use the TradePlan report's
`$500` reference quantity; they require a separately verified allocation
decision or stop before FakeBroker order creation.

## Contract

- Explicit policy fields cover fixed unit risk, per-position notional cap,
  minimum cash reserve, total open-risk cap, daily-loss limit, maximum open
  positions, and account-evidence freshness.
- No numeric field has a production default. An incomplete policy is blocked.
- Context requires exactly one ending `2573` `INDIVIDUAL_CASH` account, a valid
  binding fingerprint, fresh balance/receipt/portfolio clocks, nonnegative cash,
  buying power and commitments, and order transmission `UNAVAILABLE`.
- Quantity is the floor of the minimum risk, cash/buying-power, and notional
  budgets. Fractional shares and zero-share results are unsupported.

## Evidence Chain

- Risk Governor must pass before allocation.
- Allocation decision, policy, account context, and quantity are fingerprinted.
- Authorized allocation precedes FakeBroker preview and submission.
- Shadow freezes the complete canonical allocation JSON plus all fingerprints.
- Audits fail missing, duplicated, reordered, malformed, tampered, or
  quantity-inconsistent evidence.

## Safety Boundaries

- The Schwab bridge consumes already validated read models and performs no I/O.
- It rejects changed account identity and any unexpected brokerage position.
- No account, position, order, provider, service, scheduler, or production-data
  call occurred during implementation or verification.
- No real broker adapter or transmitting method was added.
- Official Shadow remains unarmed and `0 / 30`.

## Verification

- Python compileall: pass.
- Focused allocation, workstation simulation, simulation audit, automatic
  selector, Shadow lifecycle, live marking, sample readiness, and terminal
  packet tests: pass.
- Full Python discovery: 1,296/1,296 passed in 1,253.631 seconds.
- Full .NET solution: 251/251 passed.
- `git diff --check`: pass.
- Secret/capability and protected-path reviews: pass.

## Unresolved Activation Gates

- Steven has not selected the numeric risk policy.
- Production does not yet provide the allocator a fresh captured account and
  portfolio snapshot.
- The WPF simulation action can still be clicked before Python returns the
  truthful allocation-required block, and the legacy Qt ladder still has an old
  `$500` sizing label. Those are separate visual follow-ups.
- The current zero-broker-position invariant must later evolve into an exact
  canary-position state before any live canary work.

## Protected Review

Scoring, rank, alerts, RVOL, setup family, same-session TradePlan timing,
missed-entry/reclaim identity, provider transport, capture/service/scheduler,
database/schema, packages, credentials, raw captures, generated reports, and
historical evidence are unchanged. `$500` remains reference-only.
