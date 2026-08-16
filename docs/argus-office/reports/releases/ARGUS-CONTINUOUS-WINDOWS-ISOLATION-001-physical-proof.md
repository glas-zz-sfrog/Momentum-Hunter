# CONTINUOUS-WINDOWS-ISOLATION-001 Physical Windows Proof

## Branch And Identities

- Canonical Git: `ea056155182351be70bb03d23841aca55c6118ae`.
- Runtime branch/head: `codex/ARGUS-CONT-RUNTIME-001-independent-runtime` at
  `fd044526d81b1c7c9ecb9ba4261a1e8e0793993c`.
- Writer topology branch/head:
  `codex/ARGUS-WRITER-TOPOLOGY-002-dedicated-evidence-writer` at
  `39bd45b913c01dde4d9462de9405f11ef73913d6`.
- Proof branch:
  `codex/ARGUS-CONTINUOUS-WINDOWS-ISOLATION-001-physical-proof`, based exactly
  on writer topology head `39bd45b`.
- Current/WPF/Engine-Host-equivalent SID:
  `S-1-5-21-4040432023-2123217278-1285564647-1001`; physical test token was
  medium integrity in session 1.
- Installed Automation Service: `BEASTCOMPUTER\steve` equivalent (`.\steve`),
  session 0, PID `10232`, Running/Automatic throughout the completed run.
- Dedicated writer test identity: `NT AUTHORITY\LOCAL SERVICE`, SID
  `S-1-5-19`, non-administrator service token in session 0.
- High-integrity ceiling test: the current user SID with a high-integrity local
  administrator token. No resistance to this token is claimed.

## Evidence Root And ACL Matrix

Completed run ID `97dd66cce8ef4a65` used only:

- `C:\MomentumHunterIsolationProof\97dd66cce8ef4a65`
- `C:\MomentumHunterIsolationProofTools\97dd66cce8ef4a65`
- `C:\MomentumHunterIsolationProofControl\97dd66cce8ef4a65`

All were removed after the run. The test ACL gave SYSTEM full control,
LocalService modify on evidence/control and read/execute on tools, and ordinary
Users read/execute or control-only access as required. Physical results, rather
than displayed ACL text, determine the findings:

- Same-SID medium process: create, overwrite, append, rename, delete, directory
  create, committed overwrite/delete, and partial rename all succeeded.
- Limited current-user process against the distinct lane: every mutation,
  ACL/ownership attempt, junction creation, and read attempt was denied.
- LocalService writer: new file and directory creation succeeded. Existing
  seed mutations were denied because the fixture created them before applying
  the writer ACL; this matrix is not accepted as the final writer result.
- High-integrity current-user process: initial data mutations were denied, but
  ACL modification and junction creation succeeded, followed by a successful
  grant and write. This is the documented administrator ceiling.

The harness now applies the ACL before creating seed files. A focused test
pins that order, but the corrected elevated matrix did not run because its UAC
launch was not approved.

## Physical Results

### Same-SID And Handles

- Same-SID filesystem isolation: `INSUFFICIENT`.
- Same-SID process open: succeeded against the proof-owned child only.
- Same-SID handle duplication/read/hash: succeeded.
- Inheritance disabled: capability read denied with Windows error 6.
- Inheritance enabled: capability read and hash match succeeded.
- Explicit allowed handle list: capability read and hash match succeeded.
- Explicit unrelated handle list: capability read denied with error 6.
- Limited current-user process could not open the LocalService target process
  for handle duplication; Windows error 5.
- High-integrity current-user process opened LocalService, duplicated the
  handle, read it, and matched its SHA-256.

Only proof-owned child/test processes were targeted. No unrelated process was
opened, duplicated, stopped, or modified.

### Capability And IPC

- Capability A became stale after restart; exact replay used regenerated
  session authority and produced one canonical record with `DUPLICATE` rather
  than a second write.
- Valid authenticated envelope accepted.
- Wrong capability, stale capability, replay, forged runtime identity,
  oversized message, malformed message, and sequence conflict rejected.

### Duplicate Writer And Recovery

- Two physical writer processes both accepted sequence 1 and produced two
  records. Restart validation detected the split brain.
- Duplicate-writer exclusion: `INSUFFICIENT`.
- Writer crash before commit, after temp write, after atomic commit before ACK,
  and after ACK commit before return all exited with injected code 86.
- Restart produced exactly one committed record in every case, no surviving
  partial file, one quarantine only for the after-temp case, and either
  `ACCEPTED` or `DUPLICATE` as appropriate.
- Runtime crash/restart replay produced one record and `DUPLICATE` on replay.

### WPF And Engine Host Equivalents

- The medium-integrity current-user equivalent could not mutate or read the
  distinct-principal lane and could not open the LocalService handle target.
- The high-integrity current-user equivalent changed ACLs, created a junction,
  regained write access, and duplicated the LocalService capability handle.
- Actual WPF and Engine Host processes were not touched. The proof establishes
  token-equivalent behavior, not binary-specific application behavior.

### Reparse, Temp, And Committed Evidence

- Whole-root substitution and final record-shard redirection were rejected;
  neither produced an escaped canonical record.
- Redirecting the same-SID `.partial` path created one escaped temporary file
  before the writer returned `UNAVAILABLE`.
- Same-SID committed evidence overwrite and delete both succeeded.
- Same-SID temp rename succeeded.
- Reparse/temp boundary: `INSUFFICIENT`.

### Service And Start Order

- Temporary writer-first, nonwriter-first, and handle-target launch/termination
  paths completed. Runtime backpressure for a delayed writer remains a logical
  contract proof; no installed runtime process was started.
- No reboot, installed-service restart, scheduler repin, or production process
  termination occurred.

## Claims And Limitations

Physically proven:

- Different executable names do not create isolation.
- The current shared SID cannot enforce writer-only filesystem mutation.
- Explicit handle inheritance/allowlisting works as tested.
- A medium current-user token cannot open the tested LocalService process for
  handle duplication; a high administrator token can.
- IPC authentication, restart capability invalidation, replay rejection, and
  writer/runtime crash idempotency work in the test architecture.
- Current duplicate-writer exclusion and partial-temp reparse handling are not
  adequate.

Not proven:

- Final LocalService writer operation matrix after corrected ACL/seed order.
- Resistance to Administrator, SYSTEM, kernel control, credential theft, or
  arbitrary code execution inside the writer.
- Actual installed WPF/Engine Host binary isolation.
- Simultaneous boot ordering of an installed continuous runtime and writer.
- Any provider, account, broker, order, Paper, Shadow, or strategy behavior.

## Verification

- Compileall: pass.
- Focused Windows proof tests: 13/13 pass.
- Focused importer plus proof tests: 14/14 pass.
- Adjacent writer/runtime/IPC/root-security/proof tests: 96/96 pass.
- Full Python discovery: 2,294/2,294 pass in 599.304 seconds.
- PowerShell parse checks: pass for all three proof scripts.
- Secret-value scan: pass. Four preexisting synthetic credential-shaped values
  in `test_event_runtime_writer_ipc.py` remain test rejection fixtures and are
  not live values.
- Provider/broker/order imports or calls in the proof harness: none.
- Temporary proof tasks, roots, and actor processes after completed/failed
  attempts: zero.

## Rollback And Production Nonmutation

Before and after the completed elevated run:

- Canonical Git remained clean at
  `ea056155182351be70bb03d23841aca55c6118ae`.
- Automation Service remained Running/Automatic as `.\steve`, PID `10232`.
- Manifest SHA-256 remained
  `8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`.
- No continuous or test writer remained active.
- No production provider, broker, account, credential, order, evidence root,
  service, manifest, scheduler, WPF, or Engine Host state changed.

Canonical JSON proof:

`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\CONTINUOUS-WINDOWS-ISOLATION-001\CONTINUOUS-WINDOWS-ISOLATION-001-20260816T121230Z-97dd66cce8ef4a65.json`

SHA-256:

`E5D76D376B3377FAD7460B62FCDF21EBEE23FE2A3C60C4EB84FD0F7B1A129B0E`

## Classification And Next Gate

Completed report classifications:

- `SAME_SID_FILESYSTEM_ISOLATION_INSUFFICIENT`
- `DUPLICATE_WRITER_EXCLUSION_INSUFFICIENT`
- `REPARSE_POINT_BOUNDARY_INSUFFICIENT`
- `WINDOWS_TRUST_BOUNDARY_REQUIRES_ARCHITECTURE_CHANGE`

Branch closeout classification:

`IMPLEMENTED_PENDING_CORRECTED_DISTINCT_PRINCIPAL_RERUN`

Exact next gate: run the corrected disposable LocalService matrix under UAC,
then design and prove a dedicated non-admin writer deployment with OS-level
single-writer exclusion and reparse-resistant temp/final operations. Do not
merge, install, or activate continuous runtime behavior before those gates.
