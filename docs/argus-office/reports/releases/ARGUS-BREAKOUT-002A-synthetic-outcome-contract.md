# ARGUS-BREAKOUT-002A Synthetic Outcome Contract

## Classification

`IMPLEMENTED_PENDING_MERGE`

## Git Identity

- Canonical frozen baseline: `78db1bfddc91917b98a818f584576943e5624263`.
- Stacked prerequisite: ARGUS-CONTINUOUS-001 `f6b776eb876c75805e8b144a12e8ccd96fd226ab`.
- Feature branch: `codex/ARGUS-BREAKOUT-002A-synthetic-outcome-contract`.
- Sibling PLAN-002A `7be49fd` is not contained in this branch.

## Implemented Contract

- Exact event-chain-prefix binding for BREAKOUT_CONFIRMED and
  RECLAIM_CONFIRMED anchors.
- Versioned 5/15/30/60-minute same-session horizons.
- Forward return, MFE, MAE, trigger hold/failure, and first-failure evidence only
  when the exact completed window exists.
- Explicit pending, gap, missing, corrected, and session-unavailable evidence.
- Append-only revisions with stale-branch rejection and atomic explicit-path
  persistence.
- Prospective and historical cohort separation, visible denominators, and
  descriptive summaries.
- Default `COHORT_THRESHOLD_UNSET`; even a configured sufficient cohort can
  become only `READY_FOR_LATER_ADJUDICATION`, never an edge conclusion.

## Hard-Chew Repairs

1. The initial horizon loop reused its first horizon; each frozen horizon now
   produces its own identity and assessment.
2. Whole-ledger outcome binding would have revised old evidence when unrelated
   events arrived; records now bind immutable event-chain prefixes while the
   cohort snapshot binds the full source ledger.
3. Hash-only bar evidence could hide timestamp duplication; records now preserve
   and validate every exact forward-bar timestamp.
4. Missing outcomes were not initially explicit in summary arithmetic; every
   summary now balances complete, pending, gap, session-unavailable, and missing
   rows against its eligible denominator.
5. A numeric event threshold alone could appear ready with unfinished horizons;
   every required prospective horizon must also be terminal before later
   adjudication readiness is reported.

## Verification

- Python compileall: PASS.
- Focused outcome suite: 29 / 29 PASS.
- Adjacent BREAKOUT-001, technical breakout, candidate lifecycle, DATA-004,
  regime, RVOL, and candle-cutover suite: 136 / 136 PASS.
- Full Python discovery: 1,648 / 1,648 PASS in 224.759 seconds.
- Source nonmutation, future-bar noninterference, tamper, revision lineage,
  idempotency, denominator, and authority-negative tests: PASS.
- Protected-path, static capability, secret-shaped value, and whitespace scans:
  PASS.

## Protected Boundaries

No existing runtime imports this module. No provider/account call, production
store, score, readiness, alert, TradePlan, Risk Governor, allocation, selector,
broker/order path, service, scheduler, Engine Host, UI, Shadow state, database,
package, credential, source capture, production candle, or generated report was
changed. Canonical `master` and Tuesday's installed opening/Paper runtime remain
unchanged.

## Remaining Work

- Preserve Tuesday's terminal opening and Paper engineering evidence.
- Integrate the common continuous branch first, then reconcile/reverify sibling
  PLAN-002A and BREAKOUT-002A on the current base.
- Freeze a real prospective cohort denominator before BREAKOUT-002 calibration.
- Do not connect outcome summaries to PLAN-002, SHADOW-025, Paper, or live
  authority without a separate prospective task and proof.
