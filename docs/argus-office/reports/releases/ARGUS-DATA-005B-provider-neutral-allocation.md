# ARGUS-DATA-005B - Provider-Neutral Allocation Preparation

## Status

- Branch: `codex/ARGUS-DATA-005B-provider-neutral-allocation`
- Base and exact A003 live-proof source: `1abb4dd`
- Classification: `IMPLEMENTED_PENDING_A003_ACCEPTANCE_AND_INTEGRATION`
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

## Verification

- Python compileall: pass.
- New focused tests: 33/33 pass.
- Existing allocator, account snapshot, Shadow selector, Alpaca adapter, and
  lifecycle regressions: 199/199 pass.
- Full Python discovery: 1,424/1,424 pass in 269.059 seconds from the exact
  revised worktree state. The ignored worktree-local `.venv` junction points to
  the canonical dependency environment and creates no tracked file.
- Generic import scan: new modules are referenced only by each other and tests.
- Network/order/runtime scan: no callable provider, broker, service, scheduler,
  Engine Host, Shadow, or WPF integration.
- Canonical `master` stayed clean and synchronized at `1d0ca95`.

## A003 Identity Reconciliation

`7ccbad5` created the harness, `94c7c77` added strict capability adjudication,
and `1abb4dd` added automatic adjudicated-registry output. Git ancestry proves
both earlier commits are included in `1abb4dd`; Monday must test `1abb4dd`.

## Remaining Gates

- Run one bounded direct A003 lifecycle during regular market hours.
- Require zero residual positions/orders, sanitation, exact Paper-host identity,
  and terminal adjudication before integration.
- Freeze provider-specific semantics and separate numeric Canary/research
  policies only from observed capabilities.
- Do not activate Shadow or begin a Paper sample as part of this branch.
