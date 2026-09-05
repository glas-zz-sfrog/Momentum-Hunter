# Python Lifecycle-Position Identity Repair 002

## Disposition

`IMPLEMENTED_PENDING_MERGE / PENDING_INDEPENDENT_SECOND_EYE`.
Branch: `codex/ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-REPAIR-002`.
Frozen production canonical: `2bceeeadd06f5ed85943942f1c0f81b7094620f7`.
Rejected parent: `bd30d474a03809c029af7e29872b3b075e775f9b`.
This report does not authorize integration, deployment, activation, or a capture.
The final committed head and package hashes are bound in the external
`review-metadata.json`, `tested-head-binding.json`, and terminal closeout.

## Scope And Ownership

Normal Codex implementation, isolated Engine lane only. Astra did not design or
implement this repair. Its preserved rejection/probe artifact was replayed by
the implementer; that is not a new independent Astra review. A fresh independent
review of the frozen candidate remains required.

Only two Product modules change: `lifecycle_position_identity.py` and
`shadow_trading.py`. Test changes are `test_lifecycle_position_identity.py`,
`test_shadow_provenance_selection.py`, new `test_shadow_identity_integrity.py`,
and the byte-bound `tests/fixtures/identity_precontract` fixture. This unique
report is the only tracked governance change. Shared Roadmap/ledger/task log are
Integration-owned and remain untouched during the freeze.

## Four Repairs

1. Persisted row consistency: explicit opportunity/setup/TradePlan IDs must all
   agree with the nested Producer binding and actual persisted intraday plan.
   Partial claims and contradictory optional Producer IDs fail closed. Exact
   triple selection still precedes symbol consistency checking. No ID is chosen
   because it happens to match a symbol or timestamp.
2. Modern versus legacy: state envelope version 2 requires a strict record
   version and durable lineage corroborated by the original risk ledger event.
   New genuinely unbound input is `UNAVAILABLE`, never `LEGACY_UNBOUND`. Missing,
   partial, stripped, or contradictory modern provenance is `UNKNOWN` and cannot
   pass state validation. Genuine old schema-1 state is read without rewriting
   it and must also lack modern claims and pass frozen evidence verification.
3. First-fill binding: a position retains an explicit immutable binding of its
   ID, exact opened_at, upstream triple, frozen source hash, and first actual
   FakeBroker fill event ID/hash. Reload checks the event and binding; established
   saved bindings cannot be rewritten through the store. Partial/later fills
   preserve the first-fill timestamp. Timestamp, position ID, event, binding,
   and combined tampering fail closed.
4. Strict versions: authoritative envelope, Shadow state, record lineage, and
   position binding reject coercion. Required versions are actual Python/JSON
   integers; booleans, floats, strings, missing/null, negative, unsupported future
   versions, lists, and objects cannot masquerade as integer version 1.

The optional `lifecycle_identity_contract` report marker is validated if present
but is NOT newly emitted. Natural Product rows already contain the explicit
upstream triple. Preserving that projection prevents an unnecessary predecessor
Producer-store incompatibility; an exact intact predecessor snapshot reloads
without byte changes under this repair.

## Preserved Contracts

The Product caller remains `ContinuousTradePlanProducerStore`'s deterministic
`producer_bound_report_row` projection through
`bind_report_row_to_producer_identity`. Natural composition remains owned by
the existing staged production classes. `call-site-map.json` documents it.
Ongoing setups retain the authoritative lifecycle snapshot, including when no
new setup proposal exists. Same-symbol alternatives are selected by the exact
opportunity/setup/TradePlan triple, not collection order or symbol heuristics.

The Python read boundary remains opportunityId, setupId, tradePlanId, positionId,
openedAt, linkageStatus. The only states are PROVEN, UNKNOWN, UNAVAILABLE, and
LEGACY_UNBOUND. Natural research rows remain nontransmitting and lack execution
readiness/sizing authority. Their Shadow ingestion is identity-bound but blocked;
the first/partial/full-fill tests use separate preexisting synthetic fixtures.

Frozen evidence rank verification now replays the existing official admission
rule (persisted canonical row rank), not list position. Existing lifecycle
structural diagnostics still run before the added provenance validation. These
are narrow validation compatibility fixes, not changes to admission or economics.

## Qualification

Evidence root:
`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-OPENING-ENGINE\evidence\ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-REPAIR-002`.

Approved Python 3.12.6 environment fingerprint:
`791197DEDD392BD3D5FA0D6FB051F395562E336ABF995FC9FBD633FAC28760C8`.

- Final full discovery: 3,071 tests, zero failures/errors, one expected skip;
  `full-suite-final.json`, 2026-09-04 21:28:08 through 21:47:07 CT, 1,134.022 test
  seconds. Skip: Windows symlink creation privilege unavailable in an existing
  Opening identity test. No skip was introduced by this task.
- The final 523 source/test/tool files are bound by raw SHA-256 and normalized
  Git blob inventory before and after qualification. No executable edits after
  the final suite. Exact exported Git bytes receive their own focused rerun.
- Focused identity/selection/integrity suite: 43 tests pass. The expanded adjacent
  selection/integrity rerun passes 15 tests after the narrow rank/diagnostic fix.
- Original frozen Astra probes on the rejected head: 11/16 pass, five failing
  probe groups representing the four reported roots. On repaired source all
  five defect groups pass. Its sole remaining old assertion manufactures a new
  stripped row and calls it legacy, contradicting the repair requirement.
- Corrected-lineage probe derivative: 16/16 pass, including every original defect
  probe unchanged. Only its legacy fixture handling was corrected. These are
  implementer-executed reproductions, not independent approval.
- Additional boundary suite: 26/26 pass, including predecessor Producer-store
  compatibility, same-symbol contradictory chains in both orders, and attempted
  rewriting of an already-saved binding even with a recomputed fingerprint.
- The packet must additionally contain passing compileall, diff/secret checks,
  415-test pre-ZIP and extracted-ZIP focused runs, manifest verification, and
  protected-state proof. Terminal package results, not this prepackage report,
  are authoritative for those later checks.

`PROBE-ADJUDICATION.md` preserves all initial failures and their explanations.
The first full suite also passed but preceded the projection-compatibility
adjustment; only `full-suite-final.json` qualifies final Product bytes. The
initial adjacent-suite and fixture-harness failures were not deleted or hidden.

The legacy fixture is synthetic output generated offline by the exact actual
pre-contract canonical executable, not historical market evidence and not a
modern record relabeled by deleting fields. Its origin includes immutable
source/hash proof. `.gitattributes` preserves the serializer's exact CRLF bytes.
The default staged whitespace check flags those deliberately retained CR bytes.
The fixture is not normalized to hide that result: the packet preserves the
failure, the standard check excluding only that fixture, and a CR-at-EOL-aware
check retaining all other default whitespace rules for the complete staged diff.

## Protected Boundaries And Risks

No candidate qualification, entry/exit, stop/target, allocation, sizing, fill
economics, provider/authentication, GUI/C#, Science, service, scheduler, or order
authority changes. AST proof preserves the existing FakeBroker, close-position,
notional/PnL, and excursion economics. Related Producer/runtime/planning/risk
modules retain identical Git blobs. Compile caches and all simulated trading
state are disposable. No live provider/broker calls are part of this task.

Pre/post production snapshots match: canonical master clean/synchronized and
unchanged, service definitions/states, scheduled task definitions, Observer
configuration, and protected manifest/executable hashes unchanged. Both rejected
packages and Astra's rejection evidence remain preserved. The C# candidate stays
parked at `9437d7e03cf09d92b03b9f5fdd55ca3a27fee7fd`.

The binding proves persisted internal consistency and immutable store
transitions; it is not a claim of resistance to an attacker replacing every
local artifact and recomputing all hashes. Predecessor modern Shadow records
missing the new durable lineage fail closed rather than receiving retrospective
fabricated provenance. No production migration or activation is performed.
Windows privileged reparse proof is not newly performed by this Python task.

Manual GUI QA: not applicable; no visual changes. Open questions: independent
second-eye acceptance and subsequent C# rebind review remain outstanding.

## Recommendation

Preserve and normally push this isolated repair, verify the new sanitized
self-contained second-eye ZIP, then stop. No merge is authorized. If the packet
gates pass, `READY_FOR_INDEPENDENT_SECOND_EYE_REVIEW = YES` and
`READY_FOR_CANONICAL_INTEGRATION = NO_PENDING_SECOND_EYE`.
`CSHARP_REBIND_REVIEW_REQUIRED = YES`.
