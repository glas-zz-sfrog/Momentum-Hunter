# ARGUS-STAT-DATA-001 Goal Charter

## Goal Statement

Build a deterministic, provider-neutral, prospective research ledger that
freezes each complete opportunity-discovery cycle and every represented
opportunity before later specialist, market-path, broker-execution, or
data-quality evidence is attached separately.

## Operator Outcome

Momentum Hunter can later answer which opportunities genuinely existed, which
rows were rejected, blocked, provider-bounded, selected, or left alone, what
was known at the decision cutoff, and what later happened without preserving
only interesting winners or rewriting history.

## In Scope

- Immutable cycle and opportunity contracts with independent fingerprints.
- Complete-denominator validation and explicit incomplete/system-failure
  cycles.
- General origin/disposition/counterfactual/security-identity semantics.
- Immutable Specialist Contract attachment records with strict target and
  chronology validation.
- Separate market-path, broker-execution, and data-quality outcome contracts.
- Write-once atomic persistence, restart/idempotency/tamper behavior, and pure
  read-only summaries.
- One bounded adapter for caller-supplied canonical opening/TradePlan evidence.
- Synthetic/temporary-directory tests and branch-local governance.

## Out Of Scope

- Provider calls, historical backfill, prospective activation, runtime
  consumers, service or scheduler wiring, Windows installation, UI, continuous
  collection, candidate admission, scanning, scoring, ranking, TradePlan or
  Risk Governor changes, allocation, Paper or Shadow changes, broker/order
  actions, specialist voting, arbiter logic, strategy conclusions, or
  profitability statistics.

## Protected Areas

Canonical `master`, the installed automation manifest and service, Aug. 17
opening/Paper/SETUP-002 jobs, current production evidence, SETUP-002 sample,
Paper and Shadow state, providers, accounts, broker adapters, and UI remain
untouched. The new module must be unconsumed and incapable of network, provider,
account, broker, order, service, scheduler, Engine Host, persistence outside an
explicit caller-selected root, or execution authority.

## Acceptance Criteria

- [x] The branch stacks directly on Specialist Contract `e65cb70` and imports
  neither REGIME-002 nor EXEC-QUALITY-001.
- [x] Cycle and opportunity are distinct immutable records with versioned
  sample/policy/source/session identity.
- [x] A claimed complete cycle accounts for every parsed row; missing or
  provider-bound rows cannot disappear.
- [x] Same-symbol same-session opportunities remain distinct when origin,
  setup, cutoff, or evidence identity differs.
- [x] Security identity remains explicitly resolved or unresolved; ticker is
  never silently promoted to durable issuer identity.
- [x] Base opportunities remain immutable while specialist opinions and later
  outcomes attach through separate write-once records.
- [x] Specialist attachments validate opportunity, candidate, setup,
  TradePlan, symbol, evidence, and chronology identity.
- [x] Market path, broker execution, and data quality remain separate domains;
  counterfactual observations cannot become actual decisions or fills.
- [x] Market-path metrics stop at terminal evidence and fail closed on missing
  or unsafe horizons.
- [x] Broker outcomes require actual submission/provider evidence and actual
  filled quantity; authorization quantity is never treated as fill quantity.
- [x] Persistence is atomic, tamper-evident, idempotent for exact duplicates,
  and rejecting for conflicts or partial files.
- [x] The opening adapter preserves every represented source row and never
  calls a provider or makes a strategy decision.
- [x] The prospective sample remains inactive at zero sessions and zero
  opportunities, with historical fixtures explicitly retrospective.
- [x] Focused, adjacent, full-suite, static, secret, capability, protected-path,
  canonical-lane, and Aug. 17 pin checks pass.
- [ ] One feature-branch commit is pushed; nothing is merged, installed,
  activated, scheduled, or repinned.

## Evidence Required

Python compileall; focused STAT-DATA negative matrix; Specialist Contract,
SETUP-002, opening/TradePlan identity, and Paper outcome regressions; full
Python discovery; staged diff/secret/capability/protected-path scans; direct
parent and sibling-independence proof; canonical checkout, automation manifest,
and Aug. 17 pin nonmutation proof.

## Smallest Safe Implementation Slice

One pure Python denominator module, one focused synthetic test module, and
branch-local architecture/release/governance records. Tests write only beneath
temporary directories. No production consumer or collector is added.

## Open CEO Decisions

None for the contract slice. Prospective activation, continuous producers,
specialist nomination authority, policy veto authority, historical fill-model
research, statistical conclusions, and every production influence remain
separately gated.
