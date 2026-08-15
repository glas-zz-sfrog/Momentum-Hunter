# ARGUS-EXIT-RESEARCH-001 - Trade-Management And Exit Intelligence

## Status

- Branch: `codex/ARGUS-EXIT-RESEARCH-001-trade-management-research`
- Parent: Specialist Contract commit `e65cb70`
- Canonical merge base: `ea05615`
- Classification: `IMPLEMENTED_PENDING_PARENT_INTEGRATION`
- Runtime/install/activation: none

## Implementation

- Added pure caller-supplied models and evaluation for one immutable actual
  trade control plus separately identified counterfactual management paths.
- Actual evidence requires broker-confirmed average fill, filled quantity, fill
  time, fill ID, original protective stop, TradePlan, opportunity/setup,
  policy, and evidence identities. Hypothetical entry evidence is rejected.
- Frozen `exit-management-research-v1` policy fingerprint:
  `7dca6d7547cef6aed38e661bb89868a5f6ebe7f9058c1c45958555726e1e778a`.
- Implemented actual control, structural stop, two-ATR next-bar trailing stop,
  60-minute time stop, +1R break-even, 50% Target-1 partial exit with an
  original-stop/Target-2 runner, momentum failure, and regime deterioration.
- Preserved same-bar ordering as ambiguous, gap execution as unknown,
  completed-bar chronology, stable original 1R, quantity conservation,
  counterfactual MFE/MAE through exit only, and separate post-exit opportunity.
- Emitted only common Specialist Contract opinions with
  `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`; stale or mismatched sibling
  opinions abstain. No optimized combination or parameter search exists.
- Defined an inactive prospective sample at zero trades. No persistence,
  producer, runtime consumer, provider, account, broker, order, service,
  scheduler, Engine Host, WPF, Paper, or Shadow path was added.

## Records And Identity

- `ActualTradeEvidence` binds trade/opportunity/candidate/setup/TradePlan,
  sample/policy, provider environment, exact entry order/fill, broker-confirmed
  average fill/quantity/time, original stop/targets, forced-flat boundary,
  terminal state, actual exit fills, evidence references, and fingerprint.
- `ExitResearchControl` preserves the actual trade fingerprint and all material
  source identities. It reports actual provider/ledger results only in
  `ACTUAL_EXECUTABLE_RESULT`; candles never reconstruct actual fills.
- `ExitCounterfactualPath` binds the control fingerprint, method/version,
  policy, evidence cutoff, actual entry basis, starting quantity, levels,
  events, legs, execution-evidence state, normalized metrics, and fingerprint.
- Counterfactual IDs change with control, method, policy, evidence cutoff,
  starting quantity, or actual entry basis. The control fingerprint changes
  with actual trade, sample/policy, provider, order, fill, plan, or evidence.
- Decision events are `CREATED`, `ACTIVE`, `STOP_UPDATED`, `PARTIAL_SIGNAL`,
  `EXIT_SIGNAL`, `TERMINAL`, `ABSTAINED`, or `DATA_FAILURE`. Conflicting event
  or bar identity fails closed; equivalent inputs serialize identically.

## Evaluation Semantics

- Structural levels are immutable caller inputs and cannot act before known.
  Trailing levels use completed-bar high minus two ATR and become effective on
  the next bar. Break-even activates after +1R and cannot trigger favorably in
  its activation bar. Time exit is 60 minutes. Partial management exits 50% at
  frozen Target 1 and conserves the exact actual filled quantity.
- Momentum and regime methods consume matching, unexpired common Specialist
  Opinions only. Their implementations are not imported. Missing, stale,
  target-mismatched, unsupported-side, or unsupported-session evidence
  abstains rather than becoming a hold or exit.
- A normal level crossing is `MARKET_PATH_ONLY`; a gap is
  `EXECUTION_UNKNOWN`. V1 supports the vocabulary for quote/model evidence but
  does not fabricate either. Only the actual control may claim
  `ACTUAL_BROKER_EXECUTION`.
- The original broker-confirmed fill minus frozen valid stop remains 1R.
  MFE/MAE end at each counterfactual exit. Later movement is a separate
  `PostExitOpportunityObservation`. Counterfactuals cannot outlive the frozen
  DATA-004 session boundary or admit cross-session/short semantics in v1.

## Sibling And Sample Boundary

- RESEARCH-GOV can preregister the static question and eight fixed comparison
  arms. STAT-DATA can attach result fingerprints to the same opportunity.
- TECH may supply immutable structure/momentum evidence and REGIME may supply
  deterioration opinions. EXEC remains mechanically independent and EVENT is
  not consumed in v1. No sibling implementation import exists.
- Sample `exit-management-research-v1` is inactive with zero trades, no
  historical backfill, and no parameter optimization. No retrospective market
  or Paper trade was evaluated; all fixtures are synthetic software proof.
  Static sample fingerprint:
  `79592f644fb04b2c3853d9277554dd0a8e0e40c12eeb38d6e6bf2fe298d74a9f`.
- This task proves deterministic shape, chronology, identity, quantity,
  look-ahead, domain separation, and reproducibility. It does not prove that
  any exit method improves expectancy, has predictive value, or should affect
  a real or Paper trade.

## Verification

- Focused Exit Intelligence tests: 52/52 pass across all 22 reference fixture
  categories and the directive's adversarial matrix.
- DATA-004, Specialist Contract, Alpaca Paper lifecycle/engineering,
  SETUP-002, simulation, and exit combined regressions: 241/241 pass.
- Exact sibling branch suites for RESEARCH-GOV, STAT-DATA, REGIME, TECH,
  EXEC-QUALITY, and EVENT-SHOCK: 228/228 pass.
- Python compileall and direct py_compile: pass.
- Full Python discovery: 2,115/2,115 pass in 287.700 seconds.
- Diff check, protected-path review, secret/value scan, capability/import scan,
  deterministic/tamper proof, and canonical operational nonmutation: pass.

## Promotion Boundary

Integrate the Specialist Contract parent first. Later integration of this
branch does not activate it. Producer wiring, write-once persistence,
prospective sample activation, policy/parameter research, specialist
combination, Paper influence, and any exit or order authority each require a
separately authorized prospective gate and fresh Hard Chew proof.
