# ARGUS-SHADOW-025I Goal Charter

## Goal

Add a dormant orchestration transaction that accepts one already-built
candidate, plan, source-admission, policy, and decision bundle and completes
its valid evidence-chain prefix idempotently under the current topology-bound
sole-writer authority.

## Operator Value

A process interruption between evidence stages must not lose a valid market
decision, duplicate it, or let a malformed restart request create a misleading
partial chain. Momentum Hunter needs one deterministic operation that can
preview and resume the exact requested evidence without inventing any input.

## Scope

- Validate every supplied record and its runtime configuration.
- Acquire the existing process-lifetime writer lease before inspecting state.
- Preview the complete proposed chain in memory before the first evidence
  append.
- Replay candidate, plan, admission, and decision stages in fixed order.
- Treat exact existing evidence as an idempotent duplicate.
- Return a fingerprinted result with before/after recovery snapshots and exact
  target identities.
- Prove target completion without claiming unrelated pending work is complete.

## Non-Goals

- No candidate, plan, admission, policy, risk, allocation, or decision
  generation.
- No installed importer, Engine Host startup, root selection, ACL/reparse work,
  provider/account call, broker/order capability, Paper/Shadow activation,
  service/scheduler/WPF change, production evidence access, merge, or install.

## Acceptance Evidence

- Compileall passes.
- Focused crash-prefix, replay, conflict, chronology, authority, fingerprint,
  and non-capability tests pass.
- Adjacent and broader continuous-runtime regressions pass.
- Full Python discovery passes within a bounded timeout.
- Diff, protected-path, credential, capability, generated-artifact, and
  canonical nonmutation reviews pass.

## Classification

`IMPLEMENTED_PENDING_MERGE`
