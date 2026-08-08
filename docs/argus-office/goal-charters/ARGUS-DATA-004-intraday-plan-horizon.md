# ARGUS-DATA-004 Goal Charter - Intraday TradePlan Horizon

## Goal

Define one versioned, prospective `INTRADAY` TradePlan contract for same-session
setups. Opening momentum is one supported setup family, not the plan model.

## Operator Outcome

Momentum Hunter can distinguish an opening breakout, later continuation,
pullback, reclaim, or properly attributed catalyst-driven setup without
rewriting one setup into another. Steven can see whether a plan is pending,
triggered, missed, expired, or invalidated and know that its entry window,
replacement identity, stop/target rules, and forced-flat boundary were fixed
prospectively.

## Scope

- Support `OPENING_BREAKOUT`, `CONTINUATION_BREAKOUT`, `PULLBACK`, and `RECLAIM`
  under the same-session `INTRADAY` horizon.
- Support technical and authority-proven catalyst drivers.
- Bind plan identity to symbol, session, setup family, source evidence, levels,
  validity window, forced-flat time, predecessor identity, and rule profile.
- Preserve immutable missed-entry and terminal states.
- Require a new successor plan identity for setup replacement; a missed
  breakout can never be silently relabeled as a reclaim.
- Enforce plan timing through TradePlan export, Risk Governor, Active Monitor,
  workstation simulation, and independent Shadow validation.
- Use completed canonical Schwab opening bars for the first production producer.

## Non-Goals

- Do not make the model opening-only or infer later-session setup chronology
  from one opening snapshot.
- Do not implement continuous intraday setup discovery in this task.
- Do not change score weights, rank, alerts, RVOL, position sizing, account
  allocation, FakeBroker lifecycle, broker/order behavior, capture schedules,
  providers, candle stores, database/schema, packages, credentials, or UI.
- Do not arm Shadow, create a trade, or enable transmission.

## Acceptance Criteria

- [x] All four setup families share one versioned same-session contract.
- [x] Setup-aware entry validity, expiry, stop/target rules, and forced-flat
  boundaries are explicit and fingerprinted.
- [x] Opening plans use exactly the completed 09:30-09:34 ET canonical bars.
- [x] An opening level crossed before plan creation becomes immutable
  `MISSED_ENTRY`.
- [x] Reclaim requires a terminal breakout predecessor and receives a new plan
  identity plus explicit replacement reason.
- [x] Catalyst-driven setups require authoritative attribution identity.
- [x] Terminal states, plan IDs, fingerprints, source bars, and predecessor
  evidence fail closed on contradiction or tampering.
- [x] Risk Governor and Active Monitor evaluate plan authority at the actual
  decision/observation time rather than assuming an old plan is still active.
- [x] Shadow independently revalidates the complete plan contract.
- [x] Historical captures and reports remain unchanged.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused cross-module suite: 153/153 pass before final hardening.
- Full Python discovery after all fixes: 1,271/1,271 pass in 746 seconds.
- Full .NET solution: 251/251 pass.
- `git diff --check`: pass.
- Secret/capability scan: no credential value, network client, account method,
  order method, or transmission capability added.
- Protected-path review: only the authorized TradePlan/readiness/Shadow timing
  boundary changed; scoring weights, alerts, replay, capture scheduling,
  service behavior, broker/order behavior, database/schema, packages,
  credentials, UI, raw captures, and generated data did not.

## Status

`COMPLETE` after clean fast-forward integration, ordinary non-force backup,
runtime identity refresh, and repinning of the remaining opening jobs to the
final synchronized release head.

## Goal Steward Review

- [x] Same-session scope is explicit and not morning-only.
- [x] Future continuous producers can create continuation, pullback, reclaim,
  and supported catalyst plans without changing the core contract.
- [x] Missed breakout identity remains immutable.
- [x] Tests prove model, transition, export, expiry, tamper, simulation, and
  selector behavior rather than label existence.
- [x] No visual acceptance item is required because no UI changed.
