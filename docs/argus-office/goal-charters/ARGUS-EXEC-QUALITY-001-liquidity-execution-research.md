# ARGUS-EXEC-QUALITY-001 Goal Charter

## Goal Statement

Build one deterministic, provider-neutral Execution Quality specialist that
describes the mechanical quality of an otherwise valid opportunity from
caller-supplied canonical evidence, without gaining execution or strategy
authority.

## User Pain / Operator Outcome

Momentum Hunter can preserve whether spreads, quote behavior, liquidity,
price impact, and fill conditions looked mechanically clean or ugly at the
decision time, then compare that frozen opinion with later Paper execution
without rewriting the original observation.

## In Scope

- Immutable provider-neutral quote, minute-bar, policy, assessment, and
  observed-execution research models.
- Separate liquidity, spread, quote-stability, price-impact-risk, fill-risk,
  and data-quality states plus raw measurements.
- Regular-session v1 classification, explicit extended-hours abstention,
  TradePlan slippage sensitivity, and optional capability evidence.
- A later execution attachment with explicit full/partial/no-fill semantics
  that preserves the original opinion identity.
- Common Specialist Opinion Contract mapping, deterministic JSON and
  fingerprints, adversarial tests, and branch-local governance.

## Out Of Scope

- Provider calls, persistence, accounts, order preview/submission/replacement/
  cancellation, fill simulation, candidate admission, scoring, ranking,
  TradePlan mutation, Risk Governor, allocation mutation, Paper or Shadow
  behavior, SETUP-002, REGIME-002, UI, service, scheduler, installation,
  activation, or production integration.

## Protected Areas

No production strategy or runtime path may change. The canonical checkout,
installed service/manifest, August 17 jobs, current Paper sample, Shadow
state, provider implementations, broker adapters, and order state remain
untouched. A separate task is required before any opinion may influence a
decision or before prospective collection is activated.

## Acceptance Criteria

- [x] The specialist stacks directly on SPECIALIST-CONTRACT-001 and remains a
  sibling of REGIME-002.
- [x] All six required dimensions and their exact v1 vocabularies are
  preserved separately; no universal execution score exists.
- [x] Quote/candle chronology, identity, freshness, source, session, and
  tamper checks fail closed or abstain explicitly.
- [x] Missing quote sequence, size, volume, or unsupported-session evidence
  remains unknown rather than being inferred.
- [x] TradePlan sensitivity is mathematical counterfactual only and neither
  mutates the plan nor changes quantity.
- [x] Full, partial, cancelled-remainder, and no-fill outcomes use actual
  provider quantities and cannot leak into the predecision opinion.
- [x] Common opinions remain `RESEARCH_ONLY` with
  `EXECUTION_AUTHORITY_NONE`, non-directional semantics, and heuristic or
  unavailable confidence only.
- [x] Focused, bounded regression, full discovery, static scans, and
  protected-lane checks pass.
- [x] One feature-branch commit is pushed; nothing is merged, installed,
  activated, scheduled, or repinned.

## Evidence Required

- Python compileall; focused EXEC-QUALITY fixtures and negative matrix;
  Specialist Contract, DATA-004, DATA-005B, Paper lifecycle, quote chronology,
  and SETUP-002 regressions; full Python discovery; diff, secret, import/
  capability, and protected-path scans; canonical checkout, manifest, and
  August 17 job nonmutation proof.

## Smallest Safe Implementation Slice

One pure Python specialist module, one focused synthetic test module, and
branch-local documentation/governance. No consumer, writer, provider, broker,
runtime, or UI path is added.

## Open CEO Decisions

- None. Thresholds are frozen only as explicit v1 research heuristics. Any
  decision authority, provider expansion, Level 2 procurement, short/borrow
  logic, or prospective activation requires a later directive.

## Goal Steward Review

- Goal, operator outcome, scope, non-goals, protected areas, acceptance
  criteria, and required evidence are explicit.
- The charter does not claim strategy validity, fill probability, execution
  authority, integration, or activation.
