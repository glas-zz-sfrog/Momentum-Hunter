# ARGUS-REGIME-002 Goal Charter

## Goal Statement

Build one deterministic, offline Market Regime / Exhaustion / Stress research
specialist that extends the existing CONTINUOUS-003 rolling-regime evidence and
emits the common Specialist Opinion Contract without gaining production
authority.

## Operator Outcome

Momentum Hunter can preserve a truthful, multidimensional research opinion
about market direction, extension, stress, session, and data quality so later
prospective analysis can test whether that context improves the existing
Momentum baseline.

## In Scope

- A pure Python, caller-supplied canonical-candle evaluator for SPY, QQQ, and
  IWM.
- Reuse of CONTINUOUS-003 rolling-regime derivation and optional macro-event
  context.
- Immutable raw benchmark features and separate direction, extension, stress,
  session, and data-quality states.
- A versioned research policy, deterministic packet identity, common
  Specialist Opinion mapping, abstention/failure semantics, and synthetic
  proof fixtures.
- A dormant prospective sampling recommendation, documentation, tests,
  feature-branch commit, and ordinary non-force feature-branch backup.

## Out Of Scope

- Provider/network access, production persistence, service/scheduler/Engine
  Host/WPF integration, activation, and prospective sample creation.
- Candidate admission, score/rank, TradePlan, Risk Governor, allocation,
  Paper, Shadow, broker/order, stop, liquidation, or portfolio behavior.
- A crash predictor, universal specialist score, calibrated probability,
  strategy veto, or risk multiplier.
- Threshold optimization against historical outcomes.

## Frozen Policy Decisions

- Specialist identity is `REGIME`; specialist version is
  `regime-exhaustion-research-v1`.
- Authority is exactly `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`.
- SPY, QQQ, and IWM are all required for an evaluated opinion.
- Missing or incomplete evidence abstains as `INSUFFICIENT_EVIDENCE`; stale
  evidence abstains as `STALE_EVIDENCE`; unsupported after-hours evaluation
  abstains as `UNSUPPORTED_SESSION`.
- Contradictory, future-dated, duplicate, cross-session, wrong-symbol, or
  fingerprint-mismatched evidence fails and cannot be presented as neutral.
- Premarket evidence preserves `TRUE_04_TO_07_PATH_UNOBSERVED`.
- Candidate/sector participation, when supplied, is explicitly a
  `BOUNDED_CANDIDATE_UNIVERSE_PROXY`, never full-market breadth.
- Numeric confidence is `HEURISTIC / UNCALIBRATED`, never a probability.
- Initial thresholds are minimal `RESEARCH_HEURISTIC` constants and may not be
  optimized in this task.
- Future cadence recommendation is every five minutes during the regular
  session; no schedule is created here.

## Protected Areas

Existing runtime imports, scoring, readiness, candidate selection, TradePlan,
Risk Governor, allocation, Paper, Shadow, account/broker/order paths,
providers, service, scheduler, UI, database/schema, credentials, production
evidence, and the August 17 jobs are protected and unchanged.

## Acceptance Criteria

- [ ] Common Specialist Opinion Contract is reused without modification.
- [ ] CONTINUOUS-003 rolling-regime logic is reused rather than duplicated.
- [ ] Raw returns, structure, bar-derived VWAP, volatility, range, speed, and
  cross-index participation features are preserved deterministically.
- [ ] Direction, extension, stress, session, and data-quality states remain
  separate.
- [ ] Trend-up, trend-down, rotation, chop, late-trend, volatility-shock, and
  data-unsafe fixtures pass.
- [ ] The complete negative matrix fails closed or abstains according to the
  frozen policy.
- [ ] Output is immutable, deterministic, identity-bound, tamper-evident, and
  input-nonmutating.
- [ ] No runtime or execution capability is added.
- [ ] Hard Chew and canonical-lane nonmutation proof pass.

## Evidence Required

Compileall; focused REGIME-002 tests; Specialist Contract, CONTINUOUS-003,
macro-event, candle/evidence, and SETUP-002 regressions; full Python discovery;
diff, secret, capability, and protected-path scans; plus final canonical Git,
installed-manifest, and August 17 job-pin nonmutation checks.

## Goal Steward Review

`READY_FOR_BUILDER` on stacked branch
`codex/ARGUS-REGIME-002-exhaustion-market-stress` at parent `e65cb70`.
Expected closeout classification:
`IMPLEMENTED_PENDING_PARENT_INTEGRATION`.
