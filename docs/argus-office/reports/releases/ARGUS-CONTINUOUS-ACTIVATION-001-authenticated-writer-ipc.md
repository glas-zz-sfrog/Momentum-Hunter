# ARGUS-CONTINUOUS-ACTIVATION-001 Authenticated Writer IPC

## Branch

`codex/ARGUS-CONTINUOUS-ACTIVATION-001-authenticated-writer-ipc`, created from
synchronized canonical base `ea056155182351be70bb03d23841aca55c6118ae` in a
separate AppData worktree.

## Scope

This release adds one dormant offline prototype for the dedicated-writer shape
already admitted by SHADOW-025K. A parent creates a one-session 256-bit
capability, sends it to a direct child only through inherited standard input,
and then sends canonical HMAC-authenticated envelopes. The child admits only
four existing continuous-runtime ledger types and writes one immutable frame
per accepted record plus a chained terminal receipt beneath a caller-supplied
system-temporary directory.

The parent does not trust the child's success text. It independently verifies
the terminal status, exact record count, canonical bytes, envelope identity,
record hashes, receipt predecessor chain, terminal fingerprint, activation
blockers, and the complete output filename set. Any mismatch fails closed.

## Security Boundary

- Capability material is absent from arguments, environment, files, receipts,
  result objects, repr output, and diagnostics.
- Credential-shaped payload keys and values are rejected before signing.
- The direct child is bound to the expected parent PID; the base Python
  executable is required so a virtual-environment launcher cannot obscure that
  relationship.
- Configuration, source, session, artifact, payload, sequence, and predecessor
  identities are authenticated and fingerprinted.
- Duplicate, reordered, forged, cross-session, cross-configuration,
  cross-source, malformed, oversized, or conflicting evidence is rejected.
- No existing runtime imports the module, and there is no activation command.

This proves a protocol, not installed isolation. A same-SID process may still
be able to obtain process handles or inspect memory unless Windows process
isolation and installed ACL behavior are physically proven. WPF handle
inheritance and restart/crash recovery also remain unproven. Every result is
therefore `PROTOCOL_PROVEN_ACTIVATION_BLOCKED` with
`activation_authorized=false`.

## Files Changed

- `momentum_hunter/event_runtime_writer_ipc.py`
- `tests/test_event_runtime_writer_ipc.py`
- Branch-local Goal Charter, Roadmap, Branch Ledger, Task Log, Changelog, Risk
  Register, and this release report.

## Evidence

- Compileall: pass.
- Focused IPC suite: 15 pass.
- Adjacent writer/session/evidence/recovery/root/topology/source/plan suites:
  231 pass.
- Full Python discovery: 2,028 pass in 270.536 seconds after final self-review.
- Static import/capability scan: no existing runtime importer and no provider,
  account, broker, order, network, service, scheduler, Engine Host, WPF, or
  production path.
- No generated proof artifact is tracked; subprocess artifacts exist only in
  automatically removed temporary directories.

## Protected Areas

No scoring, readiness, TradePlan, Risk Governor, allocation, provider,
credential, account, broker/order, Paper, Shadow, SETUP-002, service,
scheduler, Engine Host, WPF, database, schema, production store, or installed
runtime behavior changed.

## Risks

The protocol does not solve same-SID process-handle access, installed-root ACL
proof, WPF handle isolation, or restart/crash recovery. Integration and
activation remain separate consequential gates. The prototype uses Python
process memory for the ephemeral capability; physical handle isolation must be
proven before that memory can be treated as inaccessible to another same-user
process.

## Manual QA

None. This is nonvisual dormant infrastructure.

## Recommendation

Preserve the branch as the protocol candidate. After August 17 evidence is
terminal, reconcile it onto current master only if still needed, then perform a
separate elevated Windows isolation proof before any installed runtime import,
production-root write, or activation decision.

## Classification

`IMPLEMENTED_PENDING_WINDOWS_ISOLATION_PROOF`
