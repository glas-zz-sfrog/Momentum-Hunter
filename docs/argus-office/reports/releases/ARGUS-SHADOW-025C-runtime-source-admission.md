# ARGUS-SHADOW-025C Runtime Source Admission

## Branch

`codex/ARGUS-SHADOW-025C-runtime-source-admission`, stacked on verified
ARGUS-SHADOW-025B head `6ba54bd`.

## Scope

The dormant continuous decision path now has an explicit source-admission
contract. A setup-bound candidate lifecycle event may source one new plan only
when the exact event and plan are present in their validated canonical ledgers.
Regime, catalyst, RVOL, clock, setup, and other context changes cannot fire
parallel cycles; they must first become one immutable successor plan, and that
exact plan becomes the source.

## Files Changed

- `momentum_hunter/event_source_admission.py`
- `momentum_hunter/event_driven_decision_cycle.py`
- `tests/test_event_source_admission.py`
- `tests/test_event_driven_decision_cycle.py`
- Branch-local Argus governance and this release report.

## Evidence

- Compileall: pass.
- Focused source-admission plus event-cycle tests: 59 pass.
- Direct plan/outcome/source/event contracts: 115 pass.
- Combined continuous evidence contracts: 285 pass.
- Allocation/Paper/Shadow/candle boundaries: 130 pass.
- Full Python discovery: 1,734 pass in 229.8 seconds.
- `git diff --check`: pass.
- Static network/broker/runtime capability scan: pass.
- Credential-shaped value scan: no credential found.

## Failure Modes Proved

- Setup-free discovery or WATCHING state cannot source a decision cycle.
- Candidate events and plans absent from their canonical ledgers fail closed.
- Changed candidate evidence cannot reuse an old candidate-event identity.
- A successor must extend the exact predecessor and advance chronology.
- A successor without a material authority or timing change is rejected.
- An evidence refresh collapses into one successor-plan source.
- A plan fingerprint is accepted only with the exact plan source identity and ID.
- Admission output is deterministic and tamper-evident.

## Protected Areas

No production execution, provider, account, allocation, scoring, readiness,
selector, Paper, Shadow, service, scheduler, Engine Host, UI, or storage path
changed. The new module has no network, broker, persistence, or runtime
capability and remains imported only by tests.

## Risks

This freezes admission semantics but does not choose the installed source
ledger paths, owning process, orchestration loop, or operational recovery
policy. Those remain prospective runtime work after serialized integration.

## Manual QA

None. This is nonvisual synthetic contract infrastructure.

## Recommendation

Preserve Tuesday's terminal opening and Paper evidence. Then reconcile this
latest successor against canonical master and integrate the continuous stack in
dependency order before any runtime orchestration or installed path wiring.

## Classification

`IMPLEMENTED_PENDING_MERGE`
