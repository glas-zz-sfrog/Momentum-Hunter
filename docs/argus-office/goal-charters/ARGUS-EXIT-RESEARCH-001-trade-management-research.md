# ARGUS-EXIT-RESEARCH-001 Goal Charter

## Goal Statement

Create a deterministic, research-only Exit Intelligence specialist that compares
frozen alternative management paths against the exact trade Momentum Hunter
actually entered without changing actual trade history or runtime behavior.

## User Pain / Operator Outcome

Momentum Hunter must eventually answer whether structural, trailing, time,
break-even, partial, momentum-failure, or regime-deterioration management would
have behaved differently from the actual control. Those comparisons must start
from broker-confirmed fill truth and must not manufacture fills, rewrite trades,
or leak future information into an earlier exit.

## In Scope

- One pure Python exit-research policy and evaluator.
- Immutable actual-control, counterfactual-path, decision-event, exit-leg, and
  post-exit-observation records.
- Exact use of the common Specialist Opinion contract.
- Completed-bar chronology, same-bar ambiguity, gap, quantity, MFE/MAE, stable
  1R, forced-flat, and deterministic identity rules.
- Synthetic reference fixtures, adversarial tests, architecture documentation,
  governance reconciliation, one commit, and a feature-branch backup push.

## Out Of Scope

- Entry research, parameter optimization, provider calls, accounts, brokers,
  orders, files or database persistence, runtime wiring, scheduling, service,
  Engine Host, WPF, activation, Paper/Shadow changes, and actual exit authority.

## Protected Areas

No scoring, ranking, TradePlan, Risk Governor, allocation, Paper lifecycle,
Shadow lifecycle, FakeBroker, broker adapter, order, service, scheduler, UI,
database, credential, production-data, or installed-runtime path may change.
Canonical `master`, the installed automation manifest, and all August 17 jobs
and pins must remain unchanged.

## Acceptance Criteria

- [x] Every counterfactual begins from the exact confirmed actual average fill,
  actual filled quantity, fill time, and original protective-stop risk basis.
- [x] Actual control and all counterfactual result domains remain distinct.
- [x] Eight method identities are represented without a combined optimized exit.
- [x] Completed evidence, next-bar trailing effectiveness, same-bar ambiguity,
  opinion chronology, gap uncertainty, and forced-flat rules fail closed.
- [x] Partial quantities never exceed actual confirmed quantity.
- [x] MFE/MAE terminate at the counterfactual exit and later movement is separate.
- [x] Common Specialist Opinions remain `RESEARCH_ONLY` with no execution authority.
- [x] Equivalent inputs serialize byte-identically and tampering is rejected.
- [x] The future sample remains inactive with zero trades.
- [x] Focused, adjacent, full-suite, static, and protected-lane proof passes.

## Evidence Required

- Python compileall and focused EXIT-RESEARCH tests.
- DATA-004, lifecycle/FakeBroker, PAPER-005, Specialist Contract, quantity/fill,
  SETUP-002, and sibling compatibility regressions.
- Full Python discovery, diff check, protected-path review, secret/capability and
  runtime-import scans.
- Canonical Git, installed manifest, and August 17 job/pin nonmutation proof.

## Evidence Depth / Hard Chew Requirements

- Exercise all 22 reference fixtures and the directive's negative matrix.
- Prove future/forming evidence, stale/mismatched opinions, quantity inflation,
  same-bar favorable ordering, post-exit leakage, fake execution, tampering, and
  capability acquisition are rejected.
- Self-review changed paths, fix narrowly, then rerun focused and full proof.

## Smallest Safe Implementation Slice

One isolated module, one focused test module, one architecture inventory, and
branch-local governance records. No consumer and no persistence path are added.

## Open CEO Decisions

- None. V1 parameters are frozen software-validation heuristics. Any future
  optimization, activation, authority, runtime wiring, or UI is separately gated.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove chronology, identity, and authority boundaries.
- [x] Evidence required is strong enough to verify the requested outcome.
