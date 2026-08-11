# ARGUS-SHADOW-025E Goal Charter

## Goal

Persist each validated runtime-source admission in one deterministic,
append-only ledger without selecting an installed root or activating runtime
orchestration.

## Operator Value

Momentum Hunter must preserve why each new continuous plan was allowed to
trigger a decision cycle. Exact replay must remain idempotent, conflicting
source reuse must fail closed, and simultaneous or interrupted writers must not
lose or corrupt the proof that connects candidate/plan evidence to a cycle.

## Scope

- Extract SHADOW-025B's proven finite cross-process path lease into a reusable
  dormant utility without changing event-cycle behavior.
- Add an explicit-path-only runtime-source-admission ledger and store.
- Validate the complete ordered plan lineage before every atomic append.
- Make exact duplicate appends byte-stable and reject identity, source, plan,
  predecessor, chronology, schema, or fingerprint conflicts.
- Prove Windows concurrent-writer preservation, finite timeout, ordinary
  recovery, process-exit recovery, atomic replacement, and tamper rejection.

## Non-Goals

- No installed root selection, ACL/reparse-point work, Engine Host import,
  startup claim composition, orchestration loop, service/scheduler/WPF change,
  provider/account call, broker/order capability, Paper/Shadow activation,
  production evidence write, merge, or installation.

## Acceptance Evidence

- Compileall passes.
- Focused source-admission and event-cycle tests pass.
- Candidate, plan, topology, Engine Host, and service-supervisor regressions
  pass.
- Full Python discovery passes within a bounded timeout.
- Diff, protected-path, credential, network/broker, generated-artifact, and
  canonical nonmutation reviews pass.

## Classification

`IMPLEMENTED_PENDING_MERGE`
