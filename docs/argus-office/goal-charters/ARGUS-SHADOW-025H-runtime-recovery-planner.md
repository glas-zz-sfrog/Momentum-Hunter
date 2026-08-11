# ARGUS-SHADOW-025H Goal Charter

## Goal

Add a dormant, read-only recovery planner that validates the complete 025G
evidence-chain prefix and identifies the next safe orchestration stage after a
process interruption without repairing or advancing evidence.

## Operator Value

Momentum Hunter must distinguish a valid interrupted prefix from a complete
decision and from contradictory evidence. A restart should know whether it is
waiting for a plan, source admission, or decision-cycle receipt without
inventing a trade, repeating a completed stage, or hiding tampering.

## Scope

- Independently validate topology and all four supplied ledger schemas and
  fingerprints.
- Prove exact candidate -> plan -> admission -> receipt/cycle identity.
- Classify empty, waiting, single-stage recovery, multi-stage recovery, and
  complete valid prefixes.
- Preserve exact pending and completed identities in a fingerprinted snapshot.
- Bind artifact hashes to the inspected state and reject concurrent changes
  detected during inspection.
- Permit only topology-authorized read roles and redact invalid-ledger errors.
- Prove deterministic output and complete source nonmutation.

## Non-Goals

- No repair, write, candidate selection, plan creation, cycle processing,
  Engine Host invocation, installed root, ACL/reparse work, service/scheduler/
  WPF change, provider/account call, broker/order capability, Paper/Shadow
  activation, production evidence access, merge, or installation.

## Acceptance Evidence

- Compileall passes.
- Focused recovery, evidence-chain, and writer-session tests pass.
- Candidate, plan, admission, cycle, topology, Engine Host, client, and
  automation-supervisor regressions pass.
- Full Python discovery passes within a bounded timeout.
- Diff, protected-path, credential, capability, generated-artifact, and
  canonical nonmutation reviews pass.

## Classification

`IMPLEMENTED_PENDING_MERGE`
