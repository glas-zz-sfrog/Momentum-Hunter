# 020G Architecture-B Product Successor

Status: IMPLEMENTED_PENDING_QUALIFICATION_AND_REVIEW. Not canonical, deployed,
or physically accepted. No service, privilege, provider or execution activation.

Base Product: `a90b83808f89a8d8c3e587b30fcc6dfa421e7fd7`.
Protected canonical: `8fe5e9b6a686678c7eed7d462a7ef24966449dda`.
Branch: `codex/ARGUS-013B-020G-ARCHITECTURE-B-PRODUCT`.
Authorizing directive: ARGUS-013B-ARCHITECTURE-B-PRODUCT-SUCCESSOR-IMPLEMENTATION-AND-HOST-CLOSEOUT-020G.

## Contract

`SCIENCE_MUTABLE_POLICY_V2` is explicitly version 2. Version 1 keeps its original
topology, descriptors and policy digest. This successor does not migrate,
restamp, or relabel v1 objects or obligations. A pending request/receipt remains
bound to its original policy hash. A mismatched policy is rejected, not repaired.

Fixed mutable parents under the configured Science state root:

| Namespace | Fixed path | Science child mask |
| --- | --- | --- |
| owner | mutable-v2/owner-lease | 0x00120081 |
| derived (Reader lock only) | mutable-v2/reader-lock | 0x00120083 |
| scratch | mutable-v2/transport-scratch | 0x00130083 |
| staging | staging-v2 | 0x00130083 |
| requests | requests-v2 | 0x00130083 |

`mutable-v2` is an exact protected common ancestor, not a Science-owned parent.
Recovery requests 0x00130081. Class parents prohibit Science root delete,
DELETE_CHILD, ADD_SUBDIRECTORY, WRITE_DAC and WRITE_OWNER. Parent security is
owner/group Local Service, exact ordered ACEs, control 0x9C14, and HIGH/NW.
The common parent's ACEs/label flags differ explicitly from class parents.

The setup-only `provision_mutable_parents` creates/verifies these fixed parents
under a supplied hash/file-ID-bound ancestry. It cannot change an existing
descriptor, grant privileges or create runtime children. The authorized setup
owner must supply its existing fixture/install authority. Science does not
invoke setup.

Runtime child creation passes NULL security attributes. Opened children must
have the admitted Science owner/group, exact class-specific inherited ACE order,
masks and flags, control 0x8C14, inherited HIGH/NW, ordinary file type, one link,
no reparse, exact final path and pinned ancestry. Required handle access is
checked against actual granted access. Opening successfully is not acceptance.

Every transaction rechecks admitted actor/generation identity and fixed parent
security/file identity. Publication additionally rechecks parents after rename.
A parent/actor/policy recheck failure closes the v2 lane. No live ACL repair or
resurrection exists; restart must independently admit a valid immutable policy.

## Reader And Writer

The sealed v2 Reader obtains its exact 0x00120083 handle from the native backend
and transfers that handle to Python's binary stream without reopening a path.
The existing Reader still initializes one byte, flushes/fsyncs, seeks, uses the
nonblocking byte-range lock, unlocks and closes. Failed stream initialization
closes the handle without misclassifying a durability error as contention.
Offline/v1 Reader behavior remains distinct; no fallback is allowed after a
native adapter failure.

Writer remains the trusted finalizer, not OS-WORM. Science stages/requests are
untrusted input to the unchanged commit protocol. Writer creates a fresh
trusted object, checks raw bytes and identity, crosses existing durable
barriers, publishes its receipt/completion, and Science acknowledges/cleans
only the matching mutable identity. Writer cannot mutate the B parents or
Science-derived children. No additional Writer token authority is granted.

Host and Writer diagnostic paths are version-aware. V2 class-parent Writer
checks use the qualified metadata rights, not v1's broader EA-read request.
Python and compiled protocol inventories must agree; the fixed bound remains
64 targets / 1000 probes. The v2 test inventory has 55 targets, v1 has 52.

## Qualification Map

Tests in `tests/test_science_mutable_policy_020g.py` cover A-H exact policy,
NULL creation, granted masks, Reader semantics, transport/recovery and rename;
I-L substitution/wrong actor/stale generation/path/reparse/hardlink/replacement;
M-N startup and mid-publication parent drift, partial-write restart;
O Product finalizer lost-reply/durability recovery; P-R version isolation,
policy mismatch, existing-object rejection and no restamp. Existing custody,
mailbox, durability, recorder, Reader, actor and host suites remain applicable.

The non-elevated native Reader test proves handle-to-CRT/locking mechanics only,
not restricted SCM authority. Primitive doubles prove Product control flow,
not OS-level denial. Physical B Product qualification and exact A14-A18 remain
mandatory after explicit fresh user UAC approval.

Sealed feasibility source:
`F:/ArgusQualification/Engine/ARGUS-013B-020F-DRIFT-ONLY-SUCCESSOR-20260921T044937Z`.
020F final seal SHA-256:
`E6D9A6096E60FF1CFFC80F1F2A22019630403EB15F3897D2443699F5C3CF4DC7`.
020G task registration, readmission, failing receipts, regressions and contract
conformance are external at `F:/ArgusQualification/Engine/ARGUS-013B-020G-PRODUCT`.

## Gates And Limitations

Freeze only after focused qualification. Then one independent accumulated-delta
security review, required full suite, actual preparation and compiled owner
preflight. Stop and request explicit UAC before any physical execution.
Physical acceptance is Tier 1 for progression into A14-A18. Missing physical
proof cannot be replaced with 020F model evidence or unit-test results.

No canonical merge, production changes, provider/auth contact, Paper/live/order
authority, Architecture A implementation, new persistent service or new runtime
privilege is authorized. Shared Roadmap/ledger are Integration-owned and are
not edited by this isolated Engine task.
