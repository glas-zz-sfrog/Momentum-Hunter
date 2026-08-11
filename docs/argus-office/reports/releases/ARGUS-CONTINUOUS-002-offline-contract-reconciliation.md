# ARGUS-CONTINUOUS-002 Offline Contract Reconciliation

## Classification

`IMPLEMENTED_PENDING_MERGE`

## Lineage

- Canonical frozen baseline: `78db1bfddc91917b98a818f584576943e5624263`.
- Common continuous prerequisite: `f6b776eb876c75805e8b144a12e8ccd96fd226ab`.
- Feature branch: `codex/ARGUS-CONTINUOUS-002-offline-contract-reconciliation`.
- Reconciled source changes: PLAN-002A `7be49fd` + `8aca0fd`, BREAKOUT-002A
  `e6cafe8` + `d0e8e45`, and SHADOW-025A `c48db6a` + `23af778`.

The shared governance conflicts were reconciled additively. Neither sibling
branch was rewritten, rebased, or merged into canonical `master`.

## Integrated Contracts

- Continuous candidate, regime, macro-event, catalyst, and sequential-breakout
  evidence from ARGUS-CONTINUOUS-001.
- Immutable prospective-only PLAN-002A plan versions and decision authority.
- Research-only BREAKOUT-002A 5/15/30/60-minute outcomes and cohorts.
- Material-trigger SHADOW-025A non-live decision cycles and suppression receipts.

All modules remain dormant. No existing production runtime imports the new
PLAN, outcome, or event-cycle contracts.

## Integration Defects Closed

1. SHADOW-025A's synthetic plan and decision factory still used the pre-hardening
   PLAN-002A schema. The fixture now supplies the prospective authority profile
   plus exact plan, risk, allocation, and blocker facts.
2. A rehashed continuous decision could name the correct plan fingerprint while
   copying different plan status/blockers into an event cycle. The event-cycle
   binding now compares those authority facts directly to the supplied plan and
   rejects the cycle before persistence.

Focused regressions prove historical plans cannot enter event cycles and blocked
plans cannot be relabeled as authorized decisions.

## Verification

- Python compileall: PASS.
- PLAN-002A + BREAKOUT-002A + SHADOW-025A: 94 / 94 PASS.
- Combined continuous contract stack: 264 / 264 PASS.
- DATA-004, RVOL, allocation, Paper research/engineering, Shadow, and candle
  cutover adjacency: 130 / 130 PASS.
- Full Python discovery: 1,713 / 1,713 PASS in 226.866 seconds.
- Two first-run infrastructure failures were caused only by the new worktree
  lacking its expected `.venv` path. Both exact tests passed after an ignored
  local junction was added, followed by the clean full pass above.

## Protected Boundary

No provider/network call, account query, credential access, broker/order method,
production-store path, service, scheduler, Engine Host, WPF, score, readiness,
selector, TradePlan semantics, Risk Governor, allocation policy, Shadow state,
Paper state, database/schema, package, raw capture, or generated report changed.

Canonical `master`, the installed service, Tuesday's opening/Paper jobs, and
external state remain untouched.

## Remaining Work

Preserve Tuesday's terminal opening and first prospective Paper engineering
evidence. After that gate, Git Steward may reconcile this rehearsal against the
then-current canonical base and serialize integration. Runtime event-source,
cross-process persistence ownership, production plan generation, prospective
cohort activation, and final continuous-intraday sample identity remain separate
tasks.
