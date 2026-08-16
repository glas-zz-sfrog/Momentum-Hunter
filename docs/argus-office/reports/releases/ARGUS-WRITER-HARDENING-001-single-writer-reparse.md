# WRITER-HARDENING-001 Physical Integrity Closeout

## Identity

- Canonical protected baseline: `ea056155182351be70bb03d23841aca55c6118ae`.
- Runtime ancestor: `fd044526d81b1c7c9ecb9ba4261a1e8e0793993c`.
- Writer topology ancestor: `39bd45b913c01dde4d9462de9405f11ef73913d6`.
- Windows physical-proof ancestor:
  `b3846806589cc0c905e4b953232b998a1a03d1de`.
- Feature branch:
  `codex/ARGUS-WRITER-HARDENING-001-single-writer-reparse`.
- Implementation commit: `df31bc0`.
- Feature branch backup: pushed by ordinary non-force push.
- Merge/install/activation: none.
- Classification:
  `WRITER_PHYSICAL_INTEGRITY_HARDENED_PENDING_AUGUST_17_RECONCILIATION`.

## Implementation

`windows_writer_storage.py` isolates the Windows mechanics from strategy and
domain code. It holds an exclusive no-sharing handle to the root-derived
`.writer-owner.lock` for the writer process lifetime. A second process targeting
the same physical root fails immediately with `WRITER_OWNER_CONFLICT`; another
root remains independent. Windows releases the handle on normal close or process
death, so a stale diagnostic file does not become permanent authority.

Owner evidence contains the writer instance, PID, acquisition time, topology
version/fingerprint, and deterministic root/lease identities. Root identity is
derived from the normalized path plus the opened directory's volume/file ID and
the topology fingerprint. PID is diagnostic only.

The backend rejects unexpected reparse points and final-path mismatches while
holding the root and writer-owned directory handles without delete sharing.
Path components reject traversal, absolute/UNC/drive changes, separators,
alternate data streams, reserved devices, trailing dot/space, non-ASCII, and
Unicode normalization tricks. Temporary files are writer-derived under the
validated `.partial` directory, created exclusively, flushed, and committed by
hard link only after identity and byte validation. Canonical and lease files
must have the expected link count, preventing an external hard-link alias from
turning a writer operation into an outside-root mutation.

The lower-level Windows calls are `CreateFileW`,
`GetFileInformationByHandle`, `GetFinalPathNameByHandleW`, `WriteFile`,
`FlushFileBuffers`, and `CreateHardLinkW`. They are required because repeated
string-prefix/path checks cannot close the demonstrated directory-substitution
race.

## Physical Proof

Preserved report:

`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\WRITER-HARDENING-001\WRITER-HARDENING-001-20260816T173600Z-5207f911ae104acf.json`

Report SHA-256:

`F8D6D4B4F84BD2A82700D9E8305B1345BA264358DF40878875F374708941E9AB`

Report fingerprint:

`9cc9945f17c483db3615131fc2c65907d950b54fef8d8a0c66c2a20857a7990e`

Results:

- Duplicate writers: one `ACCEPTED`, one `WRITER_OWNER_CONFLICT`, one record.
- Crash combination: A owned, B was denied, A was killed, C acquired; zero
  overlapping replacement owners and one record.
- Root, child, shard, partial, startup-partial, and inward hard-link attacks:
  rejected or physically blocked; outside-root mutation count `0`.
- Directory symlink creation was unavailable under the local Windows policy;
  junction/reparse variants physically exercised the equivalent boundary.
- LocalService writer completed create, temp write, atomic commit, immutable
  append, rename/delete, and cleanup operations.
- Steven, WPF-equivalent, and Engine Host-equivalent medium processes could
  read but could not perform any tested mutation or duplicate the LocalService
  handle.
- High-integrity Administrator regained access and duplicated the handle.
  `LOCAL_ADMINISTRATOR_RESISTANCE_NOT_CLAIMED` remains explicit.
- Same-SID attack evidence remains red and authoritative:
  `SAME_SID_FILESYSTEM_ISOLATION_INSUFFICIENT`.
- IPC authentication, wrong/stale capability, replay, conflicting sequence,
  forged identity, malformed/oversized message, handle inheritance/allowlist,
  writer crash/restart, and runtime restart/replay behavior passed.

Final physical classifications:

- `SINGLE_WRITER_EXCLUSION_PROVEN`
- `REPARSE_RESISTANT_WRITES_PROVEN`
- `WINDOWS_ISOLATION_PROVEN_WITH_DEDICATED_PRINCIPAL`
- `SAME_SID_FILESYSTEM_ISOLATION_INSUFFICIENT`
- `LOCAL_ADMINISTRATOR_RESISTANCE_NOT_CLAIMED`

## Scale And Verification

The complete physical soak wrote 2,000 immutable records with 10 exact
duplicate replays and one restart. Mean write latency was `39.059 ms`, p95 was
`42.265 ms`, restart recovery was `7003.56 ms`, storage was `7,281,006` bytes
across `4,011` files, and split-brain count was `0`. No whole-ledger rewrite
occurred.

- Compileall: pass.
- Focused and adjacent writer/runtime/security regression: 216/216 pass,
  including the 4,300-record ledger test.
- Full Python discovery: initial run had two worktree-environment failures
  because `.venv` was absent; both passed after a temporary junction supplied
  the expected isolated dependency path. Corrected full run: 2,301/2,301 pass
  in 533.788 seconds. The temporary junction was removed.
- PowerShell parse: pass for all three physical harness scripts.
- `git diff --check`: pass.
- Secret-shape scan: pass.
- Network/provider/account/broker/order capability scan: pass; none added.
- Protected-path review: only the writer/storage boundary, proof harness,
  tests, and this task's governance records changed.

## Cleanup And Nonmutation

After the physical campaign there were zero proof tasks, roots, or actor
processes. Canonical `master` and `origin/master` remained clean and equal at
`ea056155`. The installed Automation Service remained Running/Automatic as
`.\steve`, PID `10232`. The production manifest SHA-256 remained
`8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`.
All four August 17 jobs remained enabled, dependency-correct, and pinned to
`ea056155`. No continuous runtime/writer was installed, and no production,
Paper, Shadow, provider, broker, account, order, service, manifest, scheduler,
or UI state changed.

## Remaining Gate

Preserve this branch unmerged through the August 17 evidence window. Then
reconcile `df31bc0` onto the one authoritative runtime/writer lineage and plan
the still-separate research-only deployment/activation gate. Dedicated
principal installation behavior is not activated by this task.
