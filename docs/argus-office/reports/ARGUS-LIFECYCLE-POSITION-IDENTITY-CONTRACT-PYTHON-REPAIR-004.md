# Repair-004: Strict Nested Producer Schema Admission

Status: IMPLEMENTED_PENDING_MERGE / PENDING_INDEPENDENT_SECOND_EYE.
Branch-only Engine work; no integration or activation authority.

## Task Charter

- LANE: OPENING_ENGINE
- TASK_ID: ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-REPAIR-004
- BASE_CANONICAL_SHA: 2bceeeadd06f5ed85943942f1c0f81b7094620f7
- PARENT_IMPLEMENTATION: 22052f145127cb7b565cf93f3bf6558c5547aa13
- BRANCH: codex/ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-REPAIR-004
- WORKTREE: C:\Users\steve\AppData\Local\MomentumHunter\worktrees\LANE-OPENING-ENGINE
- OWNED_PATHS: momentum_hunter/continuous_tradeplan_producer.py; tests/test_producer_identity_admission.py; this unique report.
- PROTECTED_PATHS: all other Product, GUI, Science, provider, execution, runtime, service, scheduler and shared governance paths.
- ALLOWED_CAPABILITIES: offline implementation, approved-environment tests, isolated evidence, branch-only commit/push, sanitized packaging.
- PROHIBITED_CAPABILITIES: provider/account contact; activation; execution; production mutation; merge; C# changes.
- EVIDENCE_ROOT: C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-OPENING-ENGINE\evidence\ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-REPAIR-004
- TEMP_RUNTIME_ROOT: disposable test-owned temporary children only.
- PACKAGE_ROOT: C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-OPENING-ENGINE\packages
- PACKAGE_GATE: new immutable byte-verified sanitized second-eye ZIP.
- SECOND_EYE_GATE: fresh independent review required after candidate freeze.
- MERGE_GATE: NO_PENDING_SECOND_EYE; serialized Integration Steward only.

## Acceptance

Repair only F3 by reusing the native strict authoritative identity validator at
Producer projection admission. Exact integer 1 is valid; booleans, floats,
strings, missing/null, containers and unsupported integers fail closed.
Preserve F1 stripped-modern rejection, F2 exact historical cache compatibility,
same-symbol exact provenance, immutable first-fill/position identity and all
four public linkage states. No trading or Shadow implementation change.

Normal Codex implementation only. Astra has not contributed to this candidate.
Canonical/shared Roadmap remains frozen and Integration-Steward-owned.

Any unexpected fresh full-suite failure stops this repair; it is not permission
to fix an unrelated subsystem or substitute an isolated retry.

## Findings and Verification

F3 reproduced before repair for exact boolean-true and float-1.0 inputs,
matching independent review hashes 533FFED7... and 664DD09E.... Producer
document validation, selected-row validation and load accepted them; Shadow
rejected them. After repair all those paths reject the same unchanged bytes.

The native `authoritative_lifecycle_identity_from_report_row` validator is
reused. Exact integer schema 1 remains valid. Selected-row admission validates
both the selected input and its matching stored projection, preventing a
well-typed copy from masking malformed persisted bytes. Full load checks every
projected row. A distinct valid Product-issued same-symbol successor remains
selectable by exact provenance beside a rejected malformed sibling.

- Admission matrix: 16/16 PASS, including six new nested/path matrix methods.
- Approved-environment focused/adjacent qualification: 431/431 PASS.
- Fresh full discovery: 3,087 run; 3,086 PASS, one expected skip, zero failures
  or errors. Runner elapsed 1,030.808 seconds; no isolated retry substituted.
- Expected skip: Windows symlink creation privilege unavailable in the
  opening-runtime reparse-component test; the established baseline skip.
- Compileall and PowerShell parser: PASS; no production script changed.
- Diff, scope, secret scan and source/test/tool nonmutation: PASS.
- All 601 non-owned protected source/test/tool/C# blobs checked against the
  rejected parent remain unchanged. Only the Producer validation method and
  its imports changed in Product; no Shadow implementation change.
- Production canonical, service, task, manifest and Observer snapshots match.
- F1/F2 controls pass, including the exact canonical-generated pre-contract
  fixture SHA-256 664885014323AC60819AA2BCEA5178003344E81DD60871FE7ADA7E4F995E2596.

The exact tested source/test/tool inventories and full discovered module list
are preserved in the external evidence root. Reports record the pre-commit
Git HEAD plus exact working bytes; the second-eye source inventory binds the
frozen implementation commit to those bytes and repeats focused verification
from packaged/extracted source. Final ZIP hash, manifest counts and extraction
results belong in external TERMINAL-CLOSEOUT.json, avoiding a self-referential
Git/package identity. Packaging is a separate mandatory closeout gate.

## Disposition and Limits

No canonical merge, deployment, activation, provider/account contact, GUI,
Science or C# work occurred. Rejected predecessor branches, packages and
independent review remain preserved. This is offline deterministic proof,
not live trading or independent Repair-004 acceptance. Existing unkeyed hashes
are not authentication against coordinated replacement and recomputation.

NEXT: freeze and normally push this branch, complete byte-verified sanitized
packaging and extracted verification, then stop for fresh independent review.
READY_FOR_CANONICAL_INTEGRATION = NO_PENDING_SECOND_EYE.
CSHARP_REBIND_REVIEW_REQUIRED = YES, only after independent Python ACCEPT.
Manual GUI QA is not applicable. No unresolved Product finding is known from
this implementation's tests/self-review; independent review remains required.
