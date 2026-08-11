# Goal Charter: ARGUS-CONTINUOUS-003 Current-Head Integration

## Goal

Reconcile the proven dormant continuous-intraday contract stack onto canonical
head `e98b5cc1bab336c19305d1ca48b19b0aec45c9c6` after the first prospective
Paper decision and scheduler-repin repair were preserved.

## Operator Value

Move Momentum Hunter toward later-session candidate discovery without changing
the installed opening/Paper runtime or pretending that the dormant contracts
already monitor or trade the market.

## Scope

- Preserve the exact provider-neutral candidate-lifecycle, regime, macro-event,
  catalyst, plan-version, breakout-research/outcome, and event-cycle contracts
  from `codex/ARGUS-CONTINUOUS-002-offline-contract-reconciliation`.
- Re-run their focused, adjacent, and full regression proof against the current
  canonical source tree.
- Reconcile governance from current Git and operational evidence.
- Integrate and back up only after every proof gate passes.

## Non-Goals

- No runtime import, source loop, provider call, account query, credential read,
  order method, service or scheduler command, Engine Host command, WPF change,
  production-store writer, scoring/readiness change, or Shadow/Paper activation.
- No production claim that continuous intraday discovery is active.
- No cohort activation or strategy conclusion.

## Acceptance Evidence

- Restored source and tests match the proven source branch exactly.
- Compileall, focused, adjacent, and full Python discovery pass.
- Existing production modules contain no import of the dormant stack.
- Capability, credential, protected-path, and whitespace scans pass.
- The feature branch is pushed normally, then fast-forward integrated.
- Canonical and `origin/master` synchronize cleanly after integration.
- Opening and dependent Paper jobs are repinned to the final exact head without
  changing their pending state or touching brokerage state.

## Status

`IMPLEMENTED_PENDING_MERGE` until current-head verification and clean
fast-forward integration are complete.
