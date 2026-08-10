# ARGUS-DATA-005B - Provider-Neutral Allocation Preparation

## Status

- Branch: `codex/ARGUS-DATA-005B-current-master-integration`
- Base: synchronized A003 operational closeout `e0f6e33`
- Reconciled source: `codex/ARGUS-DATA-005B-provider-neutral-allocation` at `046b127`
- Classification: `IMPLEMENTED_PENDING_MERGE`
- Project development: `PROJECT_DEVELOPMENT_ACTIVE`
- Runtime integration: none

## Implementation

- `provider_neutral_allocation.py` defines immutable account, policy, request,
  and decision evidence with exact Decimal arithmetic and SHA-256 fingerprints.
- Allocation preserves ideal risk size, capability-quantized provider size, and
  final account-authorized size as separate values.
- Proven generic order, quantity, fractional precision, and order-specific
  fractional capabilities determine whether quantity is fractional, whole, or
  unavailable.
- `paper_research_evidence.py` preserves canonical rank, independent eligibility,
  lineage, allocation blockers, and configurable portfolio admission without
  activation or order creation. Every candidate must share one allocation
  policy, account snapshot, and capability registry. Rank-ordered admissions
  consume cumulative notional and open-risk budgets; a budget-withheld candidate
  does not consume a concurrency slot or erase its independent eligibility.
- Alpaca Paper execution and MH conservative executable results remain separate
  evidence domains and explicitly prohibit combined statistics.
- Hard Chew self-review found that the original dormant decision carried only
  opaque lineage fingerprints. The narrow fix now preserves explicit cycle,
  candidate, rank, symbol, TradePlan, Risk decision, account lane, provider,
  and environment identity; candidate/allocation and canary/research-lane
  mismatches fail closed before admission or result pairing.

## Verification

- Python compileall: pass.
- New focused tests: 36/36 pass.
- Existing allocator, account snapshot, Shadow selector, Alpaca adapter, and
  lifecycle regressions: 202/202 pass.
- Full Python discovery: 1,427/1,427 pass in 232.579 seconds from the exact
  revised current-base worktree state. The ignored worktree-local `.venv`
  junction points to the canonical dependency environment and creates no
  tracked file.
- Generic import scan: new modules are referenced only by each other and tests.
- Network/order/runtime scan: no callable provider, broker, service, scheduler,
  Engine Host, Shadow, or WPF integration.
- Canonical `master` stayed clean and synchronized at `1d0ca95`.

## A003 Identity Reconciliation

`7ccbad5` created the harness, `94c7c77` added strict capability adjudication,
and `1abb4dd` added automatic adjudicated-registry output. Git ancestry proves
both earlier commits are included in `1abb4dd`; Monday must test `1abb4dd`.

## Remaining Gates

- Fast-forward this verified dormant infrastructure into canonical `master`.
- Freeze separate numeric Canary/research policies from observed capabilities.
- Add an audited Risk Governor/allocation/Alpaca Paper/ledger wiring slice before
  any prospective Paper engineering sample.
- Do not activate Shadow or begin a Paper sample as part of this branch.
