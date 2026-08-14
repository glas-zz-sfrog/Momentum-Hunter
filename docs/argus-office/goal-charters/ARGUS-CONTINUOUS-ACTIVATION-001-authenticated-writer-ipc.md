# ARGUS-CONTINUOUS-ACTIVATION-001 Goal Charter

## Goal

Prove a dormant, offline child-process writer protocol that accepts only
authenticated, ordered, configuration-bound continuous-runtime records while
keeping installed activation explicitly blocked.

## Operator Value

Momentum Hunter needs one serialized evidence writer before continuous
intraday collection can be activated. This slice proves the message protocol
and failure behavior without pretending that a same-user Windows process is
already isolated from WPF or another process running under Steven's SID.

## Scope

- Use an ephemeral 256-bit capability delivered only through a child process's
  inherited standard-input handle.
- Keep capability material out of command arguments, environment variables,
  persisted records, receipts, and diagnostics.
- Authenticate canonical envelopes with HMAC-SHA256.
- Bind every envelope to session, sequence, predecessor, configuration, source,
  artifact allowlist, payload hash, and envelope fingerprint.
- Persist only write-once synthetic records beneath the system temporary root.
- Independently validate every child record, receipt, hash, chain, and output
  filename in the parent.
- Fail closed on tampering, forgery, replay, reordering, identity mismatch,
  malformed frames, unexpected artifacts, sensitive payloads, and conflicts.
- Report `PROTOCOL_PROVEN_ACTIVATION_BLOCKED` with every unresolved physical
  Windows proof.

## Non-Goals

- No installed service, scheduler, Engine Host, WPF, provider, account,
  credential store, broker, order, Paper, Shadow, SETUP-002, or production-data
  integration.
- No named-pipe authority based only on a shared Windows SID.
- No process, principal, ACL, credential, or production-root change.
- No activation command and no claim that same-user process-handle isolation is
  proven.
- No merge into canonical `master` while the August 17 SETUP-002 experiment is
  awaiting its first prospective evidence.

## Acceptance Evidence

- Compileall passes.
- Focused IPC tests cover real child-process transport, authentication,
  ordering, chaining, parent identity, capability lifecycle, tampering,
  replay, conflicting output, sensitive payload rejection, and source
  nonmutation.
- Adjacent writer/session/evidence/recovery/root/topology/source/plan suites
  pass.
- Full Python discovery passes after final self-review.
- Static scans prove no existing runtime import and no provider, account,
  broker, order, network, service, scheduler, Engine Host, WPF, or production
  capability.
- Canonical checkout, installed manifest, scheduled jobs, Paper/Shadow state,
  and SETUP-002 activation remain unchanged.

## Classification

`IMPLEMENTED_PENDING_WINDOWS_ISOLATION_PROOF`
