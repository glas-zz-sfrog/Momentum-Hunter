# Goal Charter: CONTINUOUS-CANARY-HARDENING-001

## Goal Statement

Repair the two system-contract defects exposed by the August 19 installed
research-only continuous canary, then prove that phase deferral or one
deterministically invalid evidence record cannot silently freeze the rest of a
trading session.

## User Pain / Operator Outcome

Momentum Hunter must keep building premarket awareness, defer evaluation until
that evaluation is legal, and resume later prospective work after a bounded
record-level failure. Windows service state must not be mistaken for pipeline
progress.

## In Scope

- Preserve and hash the failed canary as `SYSTEM_CONTRACT_FAILURE /
  DECISION_NOT_REACHED`.
- Add an explicit, checkpointed premarket readiness deferral and prospective
  regular-session rollover.
- Replace cumulative discovery evidence with a bounded current-cycle schema,
  transition delta, and predecessor/state references.
- Remove duplicate logical payload serialization from production writer
  envelopes and records.
- Preflight production envelope size before evidence queue admission.
- Separate transient writer failures from permanent record failures.
- Terminally classify deterministic poison records, preserve a compact failure
  record, and advance later eligible work.
- Keep process heartbeat and pipeline forward-progress health separate, with a
  cadence-derived stall watchdog and blocker diagnostics.
- Prove recovery from the preserved historical checkpoint in the installed
  research-only topology.
- Canonicalize and deploy only after every offline Hard Chew gate passes.

## Out Of Scope

- No strategy threshold, scoring, ranking, TradePlan, Risk Governor, allocation,
  execution, Paper, Shadow, account, position, or broker-order change.
- No retrospective trade or decision creation.
- No deletion or rewriting of the failed canary.
- No protocol-ceiling increase used to hide record growth.
- No UI work.
- No Continuous Paper activation.

## Protected Areas

- Continuous runtime scheduling, readiness, persistence, checkpoint recovery,
  dedicated-writer IPC, and installed runtime behavior are explicitly
  authorized only for the bounded repair above.
- The runtime must remain `RESEARCH_ONLY` with account reads, position reads,
  Paper, Shadow, and all order capability `UNAVAILABLE`.
- Interrupt Steven for any unexpected account/broker capability, secret
  exposure, unrelated service/job mutation, unsafe Git operation, destructive
  evidence action, or repair requiring strategy-semantic changes.

## Acceptance Criteria

- Premarket discovery produces deferred readiness, zero false readiness
  failures, retained-candidate rollover, and no premarket TradePlan.
- One hundred production-shaped discovery cycles remain bounded with meaningful
  headroom under 524,288 bytes and reconstructable lineage.
- The writer stores one canonical logical payload representation.
- Payload-too-large is distinct from writer-unavailable and is classified once.
- Valid A, oversized B, valid C, heartbeat, discovery, and readiness all proceed
  without B becoming an infinite queue head.
- Restart does not resurrect a terminal poison record; transient outage recovery
  remains bounded and idempotent.
- Health exposes process liveness, pipeline progress, queue-head diagnostics,
  and a cadence-derived stalled state separately.
- Installed-topology recovery proves the preserved August 19 checkpoint can be
  adjudicated without deleting or rewriting historical evidence.
- Full Python discovery passes in one run, along with compile, diff, secret,
  credential, capability, and protected-path checks.
- Exact canonical deployment preserves zero financial authority.

## Evidence Required

- Hash-addressed failed-canary preservation bundle and incident summary.
- Deterministic premarket-to-open, poison-head, poison-restart, transient-outage,
  long-soak, envelope-size, reconstruction, and installed-topology results.
- Envelope measurements for cycles 1, 5, 10, 20, 50, and 100, plus maximum,
  median, p95, ceiling, and minimum headroom.
- Feature/canonical/deployed SHAs, service identities/states, runtime and writer
  hashes, checkpoint migration evidence, rollback evidence, and safety counters.
- Live read-only canary evidence when a sufficient market window remains.

## Evidence Depth / Hard Chew Requirements

- Compile all Python modules.
- Run focused contract tests, adjacent continuous/runtime/writer/provider tests,
  and the full Python suite in one invocation.
- Exercise production-shaped data rather than tiny payload substitutes.
- Review the complete protected-path diff and perform a second-pass code/test
  self-review followed by narrow repairs and final reruns.
- Run `git diff --check`, secret/credential scans, and static account/order
  capability scans before commit and again before canonical merge.
- Update the authoritative Roadmap only from observed branch, test, merge,
  deployment, and canary facts.

## Smallest Safe Implementation Slice

One feature branch from `e2dd140`: first preserve evidence, then implement the
phase contract, bounded evidence contract, writer failure contract, and health
contract together because the installed incident crosses all four boundaries.
No deployment occurs until the complete offline composition passes.

## Open CEO Decisions

- None. The supplied directive resolves the nonvisual implementation,
  canonicalization, deployment, and read-only canary scope.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove the requested outcome.
- [x] Evidence required is strong enough to verify completion.
