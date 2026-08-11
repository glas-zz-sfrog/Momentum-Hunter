# ARGUS-SHADOW-025A Goal Charter - Synthetic Event-Driven Decision Cycles

## Goal

Build a deterministic, dormant contract that records when material continuous-intraday
evidence would cause Momentum Hunter to reevaluate one opportunity, while preventing
ordinary quote churn, cooldown, or replay from fabricating decisions.

## Operator Outcome

Steven can later inspect exactly why an opportunity was reevaluated, suppressed, selected
for downstream non-live execution, or left as no-selection. Every result retains the
trigger, PLAN-002A plan, risk, allocation, account, capability, policy, and predecessor
identity that produced it.

## Scope

- Define material trigger evidence for candidate, setup, volume, catalyst, regime,
  event-window, spread, plan revision, invalidation, and stale-data changes.
- Record quote-only, insignificant-delta, and cooldown suppression receipts.
- Allow safety/invalidation reevaluation to bypass entry cooldown.
- Consume an already completed PLAN-002A decision without rebuilding plan, risk, or
  allocation evidence.
- Persist immutable receipts and cycles to one caller-supplied explicit path.
- Reject tampering, conflicting replay, contradictory lineage, chronology regression,
  orphan cycles, partial writes, and in-process concurrent lost updates.

## Non-Goals

- Do not discover candidates, contact a provider/account, run risk or allocation, choose
  a broker, submit/replace/cancel an order, mark a position, or advance a lifecycle.
- Do not arm Shadow or connect this module to service, scheduler, Engine Host, WPF,
  scoring, readiness, production storage, or Tuesday's pinned jobs.
- Do not define cross-process writer locking or production event-source semantics.

## Acceptance Criteria

- [x] Enabled material evidence creates one immutable non-live cycle.
- [x] Authorized and blocked PLAN-002A decisions become selection or no-selection truth.
- [x] Quote-only, insignificant, and cooldown events never create a cycle.
- [x] Regime and candidate-safety changes bypass entry cooldown.
- [x] Exact duplicate replay is idempotent; conflicting replay fails closed.
- [x] Trigger, plan, decision, policy, source, chronology, and predecessor identities bind.
- [x] Tampered/orphaned evidence and conflicting outputs fail before state replacement.
- [x] Two coordinators sharing a path cannot lose an in-process append.
- [x] Inputs remain unchanged and deterministic inputs produce byte-identical ledgers.
- [x] No network, broker/order, account, runtime, or production-path capability exists.
- [x] Focused, adjacent, compile, full-discovery, diff, capability, and secret proof pass.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused SHADOW-025A tests: 35/35 pass.
- Adjacent lifecycle/plan/Shadow/context tests: 268/268 pass.
- Adjacent Paper/allocation tests: 46/46 pass.
- Legacy storage/story collision rerun: 15/15 pass.
- Full Python discovery: 1,673/1,673 pass in 225.362 seconds after final self-review.
- Static runtime-import, network/broker-method, secret, protected-path, and whitespace
  scans: required before commit.
- Canonical checkout: clean and synchronized at `78db1bf`; no installed state changed.

## Status

`IMPLEMENTED_PENDING_MERGE` on a feature branch stacked on PLAN-002A `7be49fd`.
Merge/install waits for Tuesday terminal opening/Paper evidence and serialized prerequisite
integration.

## Goal Steward Review

- [x] The goal is an executable precursor, not a roadmap-only result.
- [x] Suppressed work is explicit evidence rather than an absent or fabricated cycle.
- [x] Safety reevaluation cannot be hidden behind an entry cooldown.
- [x] Acceptance proves identity, negative paths, persistence, and non-capability.
