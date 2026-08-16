# Goal Charter: CONTINUOUS-WINDOWS-ISOLATION-001 Physical Proof

## Goal

Physically determine what Windows permits across the proposed Continuous
Runtime and dedicated evidence-writer boundary, using only disposable local
roots and temporary test identities.

## Operator Value

Prevent a logical two-process design from being mistaken for real isolation.
Expose same-SID, process-handle, ACL, duplicate-writer, crash, and reparse
failure modes before any continuous runtime is installed or activated.

## Scope

- Inventory the current user, installed service, limited-current-user,
  high-integrity-current-user, and LocalService test identities.
- Exercise direct file operations, handle inheritance and duplication,
  authenticated IPC, capability regeneration, duplicate physical writers,
  crash/restart, and reparse/temp-file attacks.
- Use only `C:\MomentumHunterIsolationProof*`, system temporary directories,
  and write-once sanitized review reports.
- Verify cleanup and production Git/service/manifest nonmutation.

## Non-Goals

- No provider, broker, account, credential, order, Paper, Shadow, or external
  system access.
- No production evidence, service, scheduler, manifest, WPF, Engine Host, or
  canonical Git mutation.
- No continuous strategy activation, installation, or architecture weakening.
- No resistance claim against local Administrator, SYSTEM, or kernel control.

## Acceptance Evidence

- Physical same-SID and distinct-principal operation matrices.
- Handle inheritance/duplication and IPC attack results.
- Duplicate-writer, writer/runtime crash, and reparse/temp interference proof.
- Cleanup to zero temporary tasks, roots, and actor processes.
- Python compileall, focused proof tests, adjacent writer/runtime/security
  regressions, full discovery, secret scan, and protected-path review.
- Canonical `master`, manifest hash, service PID/account/state remain unchanged.

## Status

`IMPLEMENTED_PENDING_CORRECTED_DISTINCT_PRINCIPAL_RERUN`.

The same-SID and process/filesystem defects are physically proven. The
completed LocalService run created new files and denied the limited nonwriter,
but its preexisting seed files inherited ACLs before the writer ACL was
installed. The fixture order is corrected and regression-pinned; the final
elevated rerun remains required before accepting the dedicated-principal
operation matrix.

## Goal Steward Review

- [x] Goal and operator outcome are concrete.
- [x] Scope, non-goals, and protected boundaries are explicit.
- [x] Failing isolation results are accepted as evidence.
- [x] Evidence depth covers physical Windows behavior and broad regressions.
- [x] Remaining elevation gate is explicit and cannot be inferred away.
