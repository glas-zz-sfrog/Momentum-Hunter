# ARGUS-EVENT-SHOCK-001 Goal Charter

## Goal Statement

Build one deterministic, provider-neutral Event Shock research specialist that
extends the existing CONTINUOUS-003 catalyst and macro-event evidence contracts
and keeps event relevance, expected market reaction, and actual market reaction
as three separate facts.

## Operator Outcome

Momentum Hunter can later test whether credible unscheduled events produce the
expected symbol, sector, commodity, or market response without allowing a
headline, sentiment label, or specialist opinion to create or alter a trade.

## In Scope

- A pure Python evaluator for caller-supplied catalyst snapshots, optional
  macro-event context, and canonical minute bars.
- Explicit, versioned event categories for supply disruption, industrial
  incident, geopolitical escalation, cyber incident, unexpected regulation,
  material corporate event, and other credible breaking shocks.
- Explicit relationship semantics for direct issuer, competitor/peer, proven
  supplier/customer, sector, commodity, macro, and unresolved relationships.
- Separate immutable records for event relevance, prospective expected
  reaction, and later observed reaction.
- Research states for confirmation, disagreement, volume without progress,
  relative lag, and immediate breakout failure.
- Versioned policy, deterministic identities, common Specialist Opinion
  mapping, abstention/failure semantics, and synthetic proof fixtures.
- Branch-local governance, Hard Chew verification, one feature-branch commit,
  and ordinary non-force feature-branch backup.

## Out Of Scope

- Provider/network access, production persistence, service/scheduler/Engine
  Host/WPF integration, activation, or prospective sample creation.
- Candidate admission, scoring, ranking, TradePlan, Risk Governor, allocation,
  Paper, Shadow, broker/order, stop, target, exit, or portfolio behavior.
- Headline sentiment as trade authority, inferred company relationships, event
  prediction, outcome backfill, or threshold optimization.
- STAT-DATA-002 producer wiring and any change to the August 17 jobs.

## Frozen Policy Decisions

- Specialist identity is `EVENT_SHOCK`; specialist version is
  `event-shock-reaction-research-v1`.
- Authority is exactly `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`.
- The common Specialist Opinion Contract is reused without modification.
- CONTINUOUS-003 catalyst/macro evidence is referenced, never duplicated or
  repaired in place.
- `UNRESOLVED` relationships abstain and cannot be inferred by this specialist.
- Event relevance never proves direction. Expected reaction is a prospective,
  versioned hypothesis. Actual reaction is a later attachment that cannot
  rewrite the hypothesis.
- An evaluated directional opinion requires canonical market confirmation;
  headline text or sentiment alone is insufficient.
- Numeric confidence is `HEURISTIC / UNCALIBRATED`, never a probability.
- Initial thresholds are explicit `RESEARCH_HEURISTIC` values and cannot be
  optimized in this task.
- New packet identities and heuristic thresholds are module-local research
  contracts; they cannot replace or modify any existing replay, capture,
  alert, score, readiness, or runtime identity or threshold.
- No sample is activated and no historical observation is manufactured.

## Protected Areas

Canonical master, installed runtime, providers, credentials, production
evidence, scoring, readiness, candidate selection, TradePlans, Risk Governor,
allocation, Paper, Shadow, broker/orders, service, scheduler, UI, database,
and all four August 17 jobs are protected and unchanged. Existing replay
identity rules, historical capture selection, alert-threshold semantics,
secrets/API keys/environment configuration, production configuration, and
runtime behavior are explicitly protected.

## Acceptance Criteria

- [ ] Event relevance, expected reaction, and actual reaction have separate
  immutable identities and timestamps.
- [ ] Direct issuer, peer/competitor, supplier/customer, sector, commodity,
  macro, and unresolved relationships are preserved explicitly.
- [ ] Supply disruption, industrial incident, geopolitical escalation, cyber
  incident, unexpected regulation, material corporate event, and approved
  other credible shock categories are deterministic in-domain fixtures.
- [ ] Missing attribution, stale evidence, insufficient baseline, and missing
  confirmation abstain or fail closed instead of appearing neutral.
- [ ] News/price agreement, news/price disagreement, volume without progress,
  relative lag, and immediate breakout failure are deterministic outcomes.
- [ ] Later outcomes cannot change the original opinion or hypothesis bytes.
- [ ] Common Specialist Opinion evidence-family disclosure and abstention rules
  are honored.
- [ ] Inputs are not mutated; outputs are deterministic and tamper-evident.
- [ ] No provider, runtime, persistence, or execution capability is added.
- [ ] Hard Chew and canonical-lane nonmutation proof pass.

## Evidence Required

Compileall; focused EVENT-SHOCK tests; Specialist Contract, catalyst evidence,
macro-event, CONTINUOUS-003, and adjacent specialist regressions; full Python
discovery; diff, secret, capability, protected-path, and import scans; final
canonical Git, installed-manifest, and August 17 job-pin nonmutation checks.

## Expected Classification

`IMPLEMENTED_PENDING_MERGE`
