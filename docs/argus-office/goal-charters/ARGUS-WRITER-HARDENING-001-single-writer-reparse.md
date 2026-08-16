# Goal Charter: WRITER-HARDENING-001 Physical Integrity

## Goal

Close the two physical integrity defects found by
CONTINUOUS-WINDOWS-ISOLATION-001: concurrent writer ownership of one evidence
root and filesystem redirection outside that root.

## Scope

- Add a root-scoped, process-lifetime Windows ownership primitive.
- Fail a duplicate writer immediately without a canonical mutation.
- Make ownership reclaimable after process death without deleting evidence.
- Pin and validate the physical root, writer-owned directories, temporary
  files, and canonical targets with Windows handles.
- Reject reparse points, path tricks, hard-link aliases, and directory swaps.
- Preserve write-once, idempotency, sequence, authentication, and restart
  semantics.
- Rerun the complete disposable Windows isolation campaign.

## Non-Goals

- No production writer or continuous runtime installation or activation.
- No service identity, scheduler, manifest, August 17 job, Paper, Shadow,
  provider, account, broker, order, scoring, TradePlan, risk, or UI change.
- No same-SID isolation claim.
- No resistance claim against local Administrator, SYSTEM, or kernel control.

## Acceptance Evidence

- Exactly one independent writer can own one root; unrelated roots remain
  independent.
- A denied writer performs zero canonical writes, and a replacement can acquire
  ownership after the prior owner crashes.
- The reparse/junction/swap/hard-link matrix produces zero outside-root writes.
- LocalService can perform the writer lifecycle while medium nonwriters can
  read but cannot mutate or duplicate the writer handle.
- IPC, crash/restart, write-once, tamper, and 4,300-record regressions pass.
- The 2,000-record physical soak has zero split-brain events.
- Full Python discovery, PowerShell parsing, secret/capability scans, protected
  path review, cleanup, and production nonmutation pass.

## Result

Implementation commit `df31bc0` and the complete physical report satisfy the
mandatory properties. Classification:

`WRITER_PHYSICAL_INTEGRITY_HARDENED_PENDING_AUGUST_17_RECONCILIATION`.

The branch remains unmerged and uninstalled. Activation remains prohibited.

## Goal Steward Review

- [x] Physical security properties are behavioral and measurable.
- [x] Protected production and August 17 boundaries are explicit.
- [x] Historical same-SID failure and administrator limitation are retained.
- [x] Complete physical and logical regression evidence is required.
