# ARGUS-OBSERVER-REMOVE-SOURCE-GIT-EQUALITY-OVERBINDING-001

## Classification

- Status: `IMPLEMENTED_PENDING_SECOND_EYE / NOT_MERGED / NOT_DEPLOYED`
- Lane: `OPENING_ENGINE`
- Base canonical: `986407467ae8de27df1bc228d843a8701014ac06`
- Implementation commit: `c2051845d81feee87b366d23cf7095de5221333e`
- Authoritative Observer: `argus-opening-authorized-release-observer`
- Authoritative release: `OPENING-RUNTIME-1C49F7F328503BF8FECF`
- Cross-lane activation required: `YES / INTEGRATION_STEWARD`

The Engine-owned Observer policy now records current-canonical versus immutable
release-source Git as an explicit diagnostic relationship. Inequality alone is
not a runtime-validity gate after the accepted release-binding verifier passes.
The policy remains fail-closed for every required identity, promotion,
canonical, singleton, read-only, protected-state, and execution predicate.

The live production heartbeat was not modified. It still contains the obsolete
natural-language predicate and must not be used for another accepted natural
capture until independent review and separately authorized Integration
activation are complete.

## Exact Stale Predicate

- File:
  `C:\Users\steve\.codex\automations\argus-opening-authorized-release-observer\automation.toml`
- Function: `NONE`; this is natural-language policy in the `prompt` field.
- Payload/configuration source: active Codex heartbeat TOML.
- Obsolete validation branch: require persisted execution Git to match
  immutable authorized release-source Git after the integrated verifier passes.
- Failure classification: `OBSERVER_SOURCE_GIT_EQUALITY_OVERBINDING`.
- Baseline automation SHA-256:
  `B1C00CEFCB8FE7939B396F6C55E2119087471E05F1EDC075D0E21198009C2DEF`.

The stale predicate is absent from the accepted
`observe_opening_runtime()` verifier. The production prompt added it afterward,
outside the verified Engine contract.

## Repair

`momentum_hunter.opening_runtime_observer` now exposes:

- `authorizedReleaseSourceProvenanceVerified`;
- `currentSourceEqualsReleaseSource`;
- `sourceGitRelationship`;
- `evaluate_opening_observer_heartbeat()`;
- strict `OpeningObserverHeartbeatSafetyV1` evidence parsing.

The structured heartbeat policy requires a passing authorized-release binding
and independently validates Observer identity, current release mode, channel,
promotion receipt, immutable release/source fingerprints, canonical identity
and local/origin synchronization, runtime identity/fingerprint, singleton
count, read-only state, protected hashes, services/scheduler stability,
external/provider/broker/account noncontact, and unavailable execution/order
authority.

It computes the Git relationship from the verified identities and fails if the
diagnostic contradicts them. It does not fail merely because the two valid Git
identities differ.

## September 1 Regression

The pre-fix evidence reproduces:

```text
AUTHORIZED_RELEASE_BINDING = PASS
AUTHORIZED_RUNTIME_IDENTITY = PASS
AUTHORIZED_RELEASE_IDENTITY = PASS
AUTHORIZED_RELEASE_SOURCE_PROVENANCE = PASS
CURRENT_CANONICAL_VALID = YES
CURRENT_CANONICAL_GIT = 986407467ae8de27df1bc228d843a8701014ac06
AUTHORIZED_RELEASE_SOURCE_GIT = 23ee162373654e1db91af4c19f75bbc7887e3174
LEGACY_PROMPT_RESULT = FAIL_SOURCE_GIT_EQUALITY_OVERBINDING
```

The isolated post-fix replay returns:

```text
heartbeatResult = PASS
classification = AUTHORIZED_OBSERVER_CAPTURE_VALID
sourceGitRelationship = CURRENT_CANONICAL_DIFFERS_FROM_AUTHORIZED_RELEASE_SOURCE
authorizedReleaseSourceProvenanceVerified = true
```

This is a policy replay only. The September 1 record was not modified, retried,
or reclassified.

## Verification

- Focused Observer/policy: `25/25 PASS` in `2.151s`.
- Opening/automation regression: `173/173 PASS` in `191.452s`, one expected
  Windows symlink-privilege skip.
- Full approved-environment discovery: `2,894/2,894 PASS` in `1,146.625s`, one
  expected Windows symlink-privilege skip.
- Compileall: `PASS`.
- Git diff check: `PASS`.
- Capability scan: `PASS`.
- Protected-path review: `PASS`.
- Secret scan: `PASS`.
- Pre-ZIP focused verification: `PASS`.
- Extracted-ZIP focused verification: `PASS`.
- Staging and extracted manifest verification: `PASS`.
- Extracted ZIP secret scan: `PASS`.

Every mandated negative case remains fail-closed, including unauthorized
release/runtime, runtime-fingerprint mismatch, broken channel/promotion chain,
unverified release-source provenance, invalid canonical state, singleton and
read-only violations, protected mutation, external contact, control-state
change, and execution authority.

## Nonmutation

Protected production hashes and September 1 artifact hashes match the pre-task
baseline exactly. Canonical remains clean and synchronized at `9864074`.
The active Observer automation remains byte-identical, exactly one matching
automation exists, all three Momentum Hunter services remain Running/Automatic,
and enabled Paper and Shadow job counts remain zero.

The GUI lane remained clean and untouched. Concurrent, unrelated Science work
became visible on
`codex/ARGUS-SCIENCE-ALWAYS-ON-RECORDER-IMPLEMENTATION-001` while this task was
running. Its untracked files are confined to `strategy_science_recorder` and
matching tests; this Engine task performed no write in that lane and left it
untouched.

## Second-Eye Package

- ZIP:
  `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-OBSERVER-REMOVE-SOURCE-GIT-EQUALITY-OVERBINDING-001-SECOND-EYE.zip`
- SHA-256:
  `1F539B9B4A0C80F25FFCBBA791B0B4058799EB88B4D2976BB221C3369B61C136`
- Files: `37`.
- Manifest entries: `36`.
- Sanitization: `PASS`.
- Pre-ZIP verification: `PASS`.
- Extracted-ZIP verification: `PASS`.

The first packaging attempt stopped before ZIP creation because this repository
uses a namespace-style `tests` directory without `tests/__init__.py`. The
corrected package uses the actual dependency layout; the failed attempt is
preserved in the review evidence.

## Required Report

```text
TASK_STATUS = IMPLEMENTED_PENDING_SECOND_EYE_NOT_DEPLOYED
LANE = OPENING_ENGINE
BASE_CANONICAL = 986407467ae8de27df1bc228d843a8701014ac06
BRANCH = codex/ARGUS-OBSERVER-REMOVE-SOURCE-GIT-EQUALITY-OVERBINDING-001
IMPLEMENTATION_HEAD = c2051845d81feee87b366d23cf7095de5221333e
FINAL_HEAD = DOCS_ONLY_CLOSEOUT_COMMIT_AFTER_IMPLEMENTATION_HEAD

OBSOLETE_SOURCE_GIT_EQUALITY_PREDICATE_FOUND = YES
STALE_PREDICATE_LOCATION = C:\Users\steve\.codex\automations\argus-opening-authorized-release-observer\automation.toml::prompt
OVERBINDING_PROVEN = YES
SOURCE_GIT_EQUALITY_REQUIREMENT_REMOVED_OR_NARROWED = YES_ENGINE_POLICY_ONLY
ACTIVE_PRODUCTION_PROMPT_CHANGED = NO

AUTHORIZED_RELEASE_BINDING_REMAINS_AUTHORITATIVE = YES
AUTHORIZED_RELEASE_SOURCE_PROVENANCE_PRESERVED = YES
CURRENT_CANONICAL_INTEGRITY_CHECK_PRESERVED = YES
RUNTIME_IDENTITY_VERIFICATION_PRESERVED = YES
RELEASE_IDENTITY_VERIFICATION_PRESERVED = YES
PROMOTION_CHAIN_VERIFICATION_PRESERVED = YES
SINGLETON_ENFORCEMENT_PRESERVED = YES
READ_ONLY_ENFORCEMENT_PRESERVED = YES
EXECUTION_AUTHORITY_PROHIBITION_PRESERVED = YES
PROTECTED_PRODUCTION_CHECKS_PRESERVED = YES

SEPTEMBER_1_CAPTURE_MODIFIED = NO
SEPTEMBER_1_CAPTURE_RETRIED = NO
SEPTEMBER_1_CAPTURE_RECLASSIFIED = NO

EXACT_ANOMALY_REGRESSION_PASS = YES
CANONICAL_ADVANCED_AUTHORIZED_RELEASE_STILL_VALID = PASS
UNAUTHORIZED_RELEASE_FAIL_CLOSED = PASS
UNAUTHORIZED_RUNTIME_FAIL_CLOSED = PASS
BROKEN_PROMOTION_CHAIN_FAIL_CLOSED = PASS
UNVERIFIED_RELEASE_SOURCE_FAIL_CLOSED = PASS

FOCUSED_TESTS = 25/25 PASS
OPENING_AUTOMATION_REGRESSION = 173/173 PASS
FULL_HARD_CHEW = PASS
FULL_SUITE = 2894/2894 PASS
EXPECTED_SKIPS = 1_WINDOWS_SYMLINK_PRIVILEGE

SCIENCE_LANE_TOUCHED = NO
GUI_LANE_TOUCHED = NO
CROSS_LANE_CONTRACT_CHANGE_REQUIRED = YES

MASTER_CHANGED_BY_BUILDER = NO
CANONICAL_CLEAN = YES
LOCAL_ORIGIN_SYNC = YES

SECOND_EYE_ZIP_REQUIRED = YES
SECOND_EYE_ZIP_CREATED = YES
READY_FOR_SECOND_EYE_REVIEW = YES

READY_FOR_CANONICAL_INTEGRATION = NO
READY_FOR_NEXT_NATURAL_PROSPECTIVE_CAPTURE = NO
```

## Agent Report

- Branch: `codex/ARGUS-OBSERVER-REMOVE-SOURCE-GIT-EQUALITY-OVERBINDING-001`.
- Scope: Engine-owned Observer validation contract and deterministic evidence.
- Files changed: one Observer source module, two focused test modules, one
  regression fixture, and this unique release report.
- Tests/checks: focused, Opening/automation, full discovery, compileall, diff,
  capability, protected-path, secret, package-manifest, and extracted-package
  verification.
- Evidence: external review root and sealed ZIP listed above.
- Protected areas: reviewed; no production, capture, scheduler, service,
  provider-authentication, strategy, TradePlan, Paper, Shadow, broker, account,
  position, order, Science, or GUI mutation.
- Push/merge: branch-only; no merge or deployment authorized.
- Risks: the live prompt still contains the stale predicate until reviewed
  Integration activation. Concurrent Science work is unrelated and untouched.
- Manual QA: none; nonvisual contract and evidence task.
- Open questions: none inside Engine scope.
- Recommendation: obtain independent second-eye review, then issue a separate
  Integration-owned activation directive that updates only the live heartbeat
  prompt to call the reviewed structured policy.
