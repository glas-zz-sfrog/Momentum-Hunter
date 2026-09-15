# Science raw-custody commit boundary 007

Status: implementation candidate, qualification pending. This document is not acceptance or activation authority.

Base: `4291662305a2486304fb5dd13f7fb9263218804b`, tree `ba17a2f83c19bc65c7fe779402648b7d7a787140`. Task: ARGUS-SCIENCE-RAW-CUSTODY-COMMIT-SEALING-007. No canonical merge, installed configuration change, new service/account/credential, provider contact or Paper/live/execution authority.

## Owner and trust unit

COMMITTED_CUSTODY_OWNER = EXISTING_CONTINUOUS_WRITER. Owner disposition preceded source work. Existing installation architecture names LOCAL SERVICE for the Writer and a distinct virtual service account for Science. The Writer's account domain—not exclusive process identity—is the trusted finalizer. Other processes under that same account, privileged administrators and the OS remain in the trust base. This candidate does not claim those processes are mutually isolated.

Current direct `WriterPhysicalStorage` creates objects as its caller. Its owner-evidence JSON is a logical custody profile, not `TokenOwner` or a queried file owner. It cannot by itself certify a Science/non-Science boundary. The existing production Writer protocol also has no Science-specific authenticated route: sharing its key, HELLO, mutable session identity or queue is not allowed. This design uses a separate, explicitly bound, single-publication filesystem mailbox authorized by Windows account/object security. No new secret or privileged component is created.

The existing in-process authenticated evidence-writer client provides durability but shares its caller's token. It is not an alternative nonowner mechanism. The shared Windows storage helper supplies useful pinned-handle/atomic publication precedents but cannot make Science-created final objects non-Science-owned. No other already-accepted final owner was found in the inspected canonical custody paths.

## Rights diagnosis and historical limits

015D denied `FILE_DELETE_CHILD` (0x40) on the parent, while its inherited Modify mask 0x1301bf still granted DELETE (0x10000) on the child. Three deletes therefore had an independent sufficient child-DELETE route. Source DELETE plus destination ADD_FILE permits rename; replacement also requires target deletion authority, available through target DELETE. The five successful attacks did not require WRITE_DAC, WRITE_OWNER or an owner change. The parent-only denial did not remove these sufficient rights.

The retained 015D probe did not capture every pre-operation child descriptor, native internal open or kernel-selected ACE. The rights map is a source/receipt-backed reconstruction of sufficient authorization, not an invented historical kernel trace. Preserve that Tier-3 limitation and the original blocked disposition. No later fixture repairs the historical receipt.

An object owner ordinarily has implicit READ_CONTROL/WRITE_DAC. Windows OWNER RIGHTS ACEs can qualify those implicit rights; the statement that ownership can never be restricted is not a universal Windows theorem. The actual inherited-Modify Science-created model had no demonstrated safe owner restriction and failed its physical tests. The selected architecture avoids depending on an owner-restriction trick: Science never owns the final object.

Authoritative API references: [file access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants), [file security](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights), [DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew), and [OWNER RIGHTS SID](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-dtyp/81d92bba-d22b-4a8c-908a-554ab29148ab).

## Storage and host-readiness contract

| Role | Science | Trusted owner / restrictions |
| --- | --- | --- |
| SCIENCE_STAGING / request transport | Create, write, flush, read, recover and delete temporary work | Separate bound namespace; mutable rights never inherit into final custody |
| COMMITTED_RAW_CUSTODY | Read/audit | Existing Writer creates a distinct object; Science has no write, append, DELETE, WRITE_DAC, WRITE_OWNER, rename/replace or parent delete/add authority |
| DERIVED_REBUILDABLE_STATE | Mutable local views and operational locks | Never raw authority; rebuild from immutable evidence |
| LOGS | Only operational logging required by host policy | No raw-custody authority or ancestor replacement path |
| CONFIG | Read-only | Protected nonsecret root/SID/descriptor/limit bindings; no Science rebind |

The canonical `SCIENCE_STORAGE_ROLE_SECURITY_CONTRACT` is declared in `science_custody_readonly.py`. Native policy validates the actual roots, every replaceable ancestor, token identity, owner and descriptors. Merely naming a role or passing a favorable boolean is not readiness proof. Committed directories deny Science ADD_FILE, ADD_SUBDIRECTORY, DELETE_CHILD, DELETE, WRITE_DAC and WRITE_OWNER; final files deny write/append/delete/security modification. Science read rights and valid staging operations must also work. A read failure is not successful isolation qualification.

The fixed derived-directory descriptor is not a generic inherited file-write descriptor. The ordinary Reader opens its mutable `.reader.lock` with read/write access, including attributes and extended attributes. Its native backend must prepare that one child with the explicit Science-owned mutable-file descriptor after acquiring the lifetime Science lease, before exposing the derived root. Existing incompatible children fail validation unchanged; there is no in-place permission repair or change to committed-custody rights. A representative native probe preserved a successful initial creation followed by a failed reopen under default inheritance, and successful initial/repeated opens of a separate explicit-descriptor control. This remains distinct from actual SCM Science-factory qualification.

## Publication and recovery

```text
Science-owned staging -> closed exact candidate + fixed request
  -> separate existing Writer account-domain channel
  -> independently opened, bounded bytes + stable logical identity
  -> durable immutable identity claim
  -> distinct Writer-created private object -> flush -> immutable final singleton
  -> actual owner/descriptor/file-ID/hash readback -> durable receipt
  -> Science exact readback + singleton registration + notification drain
  -> conditional same-object/generation staging/request cleanup
```

Requests cannot choose roots, SIDs, ACLs or arbitrary operations. Stable identity is independent of raw-content hash. Exact final path and digest are separately bound. Same logical identity with a different path or bytes fails closed; one claim reserves one final. The authoritative receipt binds the original request/staging identity, claim, policy, final file identity, owner/descriptor and exact final digest. A lost receipt can be deterministically completed from the original immutable claim and final; raw capture times are not regenerated. Final-without-claim, missing receipted final, changed inode/security, malformed input or unproven state cannot be adopted as success.

Wire requests retain their configured finite ceiling, at most 64 KiB. Writer-generated claims and receipts use the protocol's separate fixed 64 KiB internal metadata ceiling; they include provenance beyond the original request, so a smaller wire ceiling is not their storage limit. Every metadata read, creation and explicit audit uses the same ceiling. Raw-artifact ceilings remain separate and unchanged. Policy admits exactly two staging entries for the bounded orphan/receipt recovery protocol, with a third enumeration entry used only as an overflow sentinel; a one-stage configuration is not a supported variant.

All three raw surfaces use this protocol: arrivals ledger; custody source/payload/scientific receipt/checkpoint/conflict/final manifest/checksum/quarantine receipt; Reader cursor journal. Reader's mutable singleton lock lives in DERIVED_REBUILDABLE_STATE, not committed cursors. The default offline recorder API remains for compatibility and is explicitly **not** physical-isolation readiness. A sealed recorder cannot silently pair with an unsealed Reader cursor sink.

Before opening a new process's namespace guards, it may reconcile an exact old transport receipt and conditionally retire the old request. That is transport cleanup, not scientific admission. The normal canonical full startup/recovery audit must still succeed before fresh ingestion. During an active generation, no next publication can occur until the prior singleton passes existing readback/register/drain. Unknown namespace events still reject the affected call. Actual native notification loss/overflow poisons its guard and requires close/reopen audit. An unknown but successfully delivered transient cursor name follows the existing distinct canonical path: first-call rejection followed by full audited same-instance recovery if the transient is gone and every surviving raw object verifies. It is not silently ignored, nor newly classified as native queue loss. No batching or event suppression is introduced.

Unsubmitted orphan stages are NOT_ADMITTED. Their metadata receipts are explicitly new recovery observations, with an explicit current clock, not recovered original observation times. Existing original raw records are never rewritten to make cleanup or restart pass. Incomplete nonauthoritative transport serialization and committed raw evidence have different retention roles; exact bounded scratch policy and its crash tests belong to the native/mailbox implementation, not a generic raw-file delete operation.

## Writer liveness and scaling boundaries

`ProductionWriterServer(..., science_custody_policy=None)` is dormant by default: no Science roots, worker, config lookup or timer. An explicitly provided immutable policy uses a separate worker, lock and bounded one-item mailbox; it does not borrow the production session/key/queue. Science failure is reported separately. A blocked native I/O cannot be forcibly cancelled by a Python shutdown timeout; STOP_PENDING is not a clean close. The channels still share a process, CPU and disk, so source separation is not a disk quota, hard latency deadline or standalone proof of combined-load liveness.

Normal commits make direct identity-keyed claim/receipt/final lookups and bounded transport operations. Historical scans remain explicit startup/recovery/audit work. Required qualification includes measured 1/10/100-style representative commits/fanout, Science005 notification tests, Writer005/Engine008 interactions, failure/load controls and the full applicable suite on exact frozen bytes.

## Exact 013B successor handoff

The current installed-host guard exists only in frozen 013B and is not imported or changed here. After separate accepted canonical custody integration, a newly authorized 013B reconciliation must:

1. Verify integrated source ancestry and exact 007 accepted byte identities; retain all original 013B/015D evidence and dispositions.
2. Bind actual existing Writer and Science token users/owners/groups/privileges/IL/session plus exact protected roots/configuration. Do not assume names prove SID, TokenOwner or integrity. The preserved Science IL 12288 is HIGH, not SYSTEM 16384.
3. Replace generic Science final-write/delete/owner requirements with the five explicit storage roles. Science must pass staging positive controls and read-only raw validation; forbidden committed rights must remain absent.
4. Use the separately authorized real SCM path to repeat full post-commit final/ancestor write, append, delete, rename, replacement, DACL and owner denials, including process close/restart and durable receipt recovery. A translated anonymous fixture is architecture/native evidence, not the sole production claim.
5. Requalify owner regression, Writer/Engine liveness and relevant host interaction on the exact reconciled candidate. Seek new independent acceptance; do not inherit an activation or physical/UAC test authorization from this source-only task.

007 qualification and integration readiness remain pending until its required native crash/denial matrix, complete focused/full suites, immutable evidence custody and fresh independent Astra acceptance all pass. No deployment or activation is authorized by this document.
