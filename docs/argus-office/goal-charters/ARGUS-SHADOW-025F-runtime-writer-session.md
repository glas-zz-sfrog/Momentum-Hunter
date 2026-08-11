# ARGUS-SHADOW-025F Goal Charter

## Goal

Compose the dormant runtime topology claim and source-admission store into one
single-use Engine Host writer session that owns the writer lease for its process
lifetime, without activating an installed runtime path.

## Operator Value

Momentum Hunter must not authorize a writer at startup and then append after a
replacement host has taken ownership. The exact current process must retain
sole authority while it writes, and persisted evidence must remain bound to the
correct evidence program and configuration.

## Scope

- Bind one validated Python Engine Host claim to one process-lifetime OS lease.
- Revalidate host, PID, build, configuration, topology, operation, and target
  path on each source-admission append.
- Make a session single-use and reject same-process or replacement-process
  concurrent ownership.
- Bind source admissions to configuration identity.
- Bind ledger program/configuration headers and ordered contents under one
  tamper-evident fingerprint.
- Prove release after normal close and process exit, finite replacement timeout,
  exact replay, cross-namespace rejection, and concurrent activation safety.

## Non-Goals

- No installed root, ACL/reparse work, Engine Host importer, startup loop,
  service/scheduler/WPF change, provider/account call, broker/order capability,
  Paper/Shadow activation, production evidence write, merge, or installation.

## Acceptance Evidence

- Compileall passes.
- Focused source-admission and writer-session tests pass.
- Candidate, plan, topology, Engine Host, client, and service-supervisor
  regressions pass.
- Full Python discovery passes within a bounded timeout.
- Diff, protected-path, credential, static capability, generated-artifact, and
  canonical nonmutation reviews pass.

## Classification

`IMPLEMENTED_PENDING_MERGE`
