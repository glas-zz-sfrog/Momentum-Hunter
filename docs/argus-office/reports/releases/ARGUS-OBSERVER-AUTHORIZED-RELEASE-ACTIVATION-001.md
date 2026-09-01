# ARGUS-OBSERVER-AUTHORIZED-RELEASE-ACTIVATION-001

## Classification

- Status: `IMPLEMENTED_PENDING_SECOND_EYE / UNMERGED / UNDEPLOYED`
- Lane: `OPENING_ENGINE`
- Immutable base:
  `e6ece7e63623911c328b3a499e94b6282970b47d`
- Task branch:
  `codex/ARGUS-OBSERVER-AUTHORIZED-RELEASE-ACTIVATION-001`
- Implementation commit:
  `692940aed693c64d66cd7361e1cf0463a224a03e`
- Strategy, statistical, provider, Paper, Shadow, broker, account, position,
  order, GUI, and Opening-capture semantics changed: `NO`
- Scheduler, service, manifest, release, or channel mutation by Builder: `NO`
- Second-eye review required: `YES`

## Scope And Authority

The task adds one stable operational creation/execution boundary for future
Opening observers. It reuses the accepted
`momentum_hunter.opening_runtime_observer.observe_opening_runtime` verifier and
does not duplicate release/channel verification.

The default `CURRENT_AUTHORIZED_RELEASE` activation payload contains:

- stable mode and `opening-capture` channel;
- authority timing `AT_OBSERVATION_TIME`;
- accepted verifier entrypoint identity;
- read-only, no-provider, no-mutation, and order-unavailable safety fields;
- creation timestamp and an activation-payload integrity fingerprint.

It contains no expected Opening release ID and no expected runtime fingerprint.
The generated heartbeat text names the stable module invocation:

`python -m tools.prepare_opening_runtime_observer observe`

`FIXED_EXPECTED_RELEASE` remains available only with an explicit immutable
release ID and runtime fingerprint. Current mode plus that fixed pair is
rejected before an activation file is written. Fixed mode without a complete
pair is also rejected.

## Observation Receipt

Execution validates the activation, delegates once to the accepted verifier,
and records a write-once receipt containing:

- observer mode and observation timestamp;
- channel and authority source;
- resolved authorized release/runtime/release fingerprint/source Git;
- promotion receipt fingerprint and chain-verification status;
- actual release/runtime/canonical identity and cleanliness;
- PASS/FAIL classification and exact diagnostic;
- runtime/canonical drift flags;
- mutation, provider-contact, and order-transmission safety fields;
- complete accepted-verifier result and receipt fingerprint.

The authority is resolved once at execution. A later promotion cannot rewrite
the receipt, and exclusive creation rejects a second write to the same path.
Fixed historical mode verifies its immutable release but does not falsely claim
that it verified the current promotion chain.

## Promotion And Monday Proof

A deterministic physical chronology proves:

1. an operational activation is created while release A is authorized;
2. B is promoted without changing that activation;
3. actual B is observed;
4. current mode resolves B and passes;
5. C is promoted after observation;
6. the already-created receipt remains bound to B and byte-unchanged;
7. explicit fixed-A mode against actual B fails `RUNTIME_DRIFT`.

The preserved Monday production observation was replayed against the complete
seven-release fixture. Current-authorized mode resolves
`OPENING-RUNTIME-1C49F7F328503BF8FECF` and passes
`AUTHORIZED_RUNTIME_MATCH`. The old explicit F18 expectation against the same
actual 1C49 evidence fails `RUNTIME_DRIFT`. This reproduces both the defect and
the repaired future-creation behavior without changing production state.

## Negative Coverage

Focused tests prove:

- current authority plus matching runtime passes;
- successor authority plus predecessor runtime fails;
- missing or malformed channel fails closed;
- malformed/broken promotion evidence fails closed;
- release/fingerprint inconsistency fails closed;
- dirty or divergent canonical evidence fails;
- current mode plus fixed identity is rejected;
- fixed mode without explicit identity is rejected;
- valid fixed historical mode retains accepted verifier semantics;
- activation tampering is detected;
- module CLI creation and validation work from repository root;
- authority snapshot and receipt remain immutable.

## Operational State Reconciliation

While this Builder task was running, a separate authorized Integration Steward
task advanced canonical from the immutable task base to
`986407467ae8de27df1bc228d843a8701014ac06` with one docs/governance-only commit
and created the read-only Codex heartbeat
`argus-opening-authorized-release-observer`. The task branch was not rebased and
did not import that commit.

The external heartbeat inventory shows one active weekday heartbeat. Its prompt
contains `CURRENT_AUTHORIZED_RELEASE`, no `OPENING-RUNTIME-*` release ID, no
64-character expected runtime fingerprint, and explicit provider/mutation
prohibitions. Its raw TOML and target thread ID are not in the packet. The
Builder did not create, update, delete, or run that heartbeat.

There is no executable, test, tool, or task-owned path overlap in the external
canonical delta. The current task remains correctly based on its mandated
immutable canonical SHA.

## Opening Closure And Protected Paths

Authoritative boundary analysis reports 99 Opening files before and after this
task, with identical fingerprint
`c37217b68091b5bc6222a487cfcc303542e152cbcbde5d53c4876a75dbf34505`.
The activation module is explicitly excluded as unreachable, and the launcher
is not an explicit Opening runtime input.

No Science or GUI path changed. No strategy, scoring, readiness, TradePlan,
provider, statistical, Paper, Shadow, broker/account/position/order, service,
manifest, scheduler, installed runtime, release, channel, or canonical file was
changed by the Builder.

## Hard Chew

- Focused activation/accepted-observer tests: `24/24 PASS`.
- Adjacent Opening identity/release/boundary/automation tests:
  `139/139 PASS`, one expected Windows symlink-privilege skip.
- Full approved-environment discovery: `2,893/2,893 PASS`, one expected Windows
  skip, `1009.048s` unittest time.
- Approved environment fingerprint:
  `791197DEDD392BD3D5FA0D6FB051F395562E336ABF995FC9FBD633FAC28760C8`.
- Full suite imported this lane and found no lane-local `.venv`.
- `compileall`: `PASS`.
- `git diff --check`: `PASS`.
- PowerShell parsing: `NOT_APPLICABLE`; no PowerShell changed.
- Capability scan: `PASS`; production source/tool imports no network,
  provider, credential, service, scheduler, broker, account, position, Paper,
  Shadow, or order capability. Subprocess use is test-only for the CLI proof.
- Secret scan: `PASS`.
- Protected-path review: `PASS`.
- Production manifests, Opening channel, and three required services remained
  unchanged by this task.

Two development findings were preserved honestly: direct script invocation was
replaced by the stable `python -m` invocation, and the standalone proof script
now binds its source root explicitly. The corrected paths pass in staging and
after ZIP extraction.

## Second-Eye Packet

Authoritative packet:

`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-OPENING-ENGINE\packages\ARGUS-OBSERVER-AUTHORIZED-RELEASE-ACTIVATION-001-692940aed693c64d66cd7361e1cf0463a224a03e\ARGUS-OBSERVER-AUTHORIZED-RELEASE-ACTIVATION-001-SECOND-EYE.zip`

- SHA-256:
  `09534A9ADBB859796DD16883F375E27A2FB8FA06F758391B8FDF26F7A23503EC`
- File count: `71`
- Manifest entries: `70`
- Manifest verification: `PASS`
- Sanitization: `PASS`; zero secret/account-ending/thread-ID matches.
- Pre-ZIP focused/replay/promotion verification: `PASS`
- Extracted-ZIP focused tests, promotion proof, activation validation, Monday
  replay, and manifest verification: `PASS`

## Required Agent Report

- Branch: `codex/ARGUS-OBSERVER-AUTHORIZED-RELEASE-ACTIVATION-001`.
- Scope: future operational observer creation, activation validation, accepted
  verifier delegation, and immutable result receipt only.
- Files changed: activation module, stable CLI tool, focused tests, and this
  unique release report.
- Tests/checks: focused, adjacent, full discovery, compileall, closure,
  transition/replay, CLI, diff, capability, protected-path, secret, manifest,
  and extracted-packet checks.
- Evidence: isolated task evidence and authoritative second-eye packet above.
- Protected areas: reviewed and unchanged as listed above.
- Push/merge: the final task branch push is required for closeout;
  merge/deployment remain unauthorized.
- Risks: until this branch passes second-eye and serialized integration, future
  manually authored observer prompts can still bypass the new creator even
  though the current active heartbeat is independently compliant.
- Manual QA: none; this task is nonvisual.
- Open questions: none within scope.
- Recommendation: independent second-eye review, then a separate serialized
  integration directive if accepted.

## Final Classifications

```text
OBSERVER_OPERATIONAL_ACTIVATION_IMPLEMENTED = YES
DEFAULT_OPERATIONAL_MODE = CURRENT_AUTHORIZED_RELEASE
OPERATIONAL_PAYLOAD_EMBEDS_RELEASE = NO
OPERATIONAL_PAYLOAD_EMBEDS_FINGERPRINT = NO_EXPECTED_RUNTIME_FINGERPRINT
FIXED_HISTORICAL_MODE_PRESERVED = YES
FIXED_MODE_REQUIRES_EXPLICIT_IDENTITY = YES
CURRENT_MODE_PLUS_FIXED_IDENTITY_REJECTED = YES
PROMOTION_BETWEEN_CREATE_AND_RUN = PASS
OBSERVATION_AUTHORITY_SNAPSHOT_IMMUTABLE = YES
MONDAY_OPERATIONAL_REPLAY_AFTER_ACTIVATION = PASS
FAIL_CLOSED_ON_UNKNOWN_AUTHORITY = YES
FAIL_CLOSED_ON_RUNTIME_MISMATCH = YES
FAIL_CLOSED_ON_AMBIGUOUS_CONFIGURATION = YES
SCIENCE_PATHS_TOUCHED = 0
GUI_PATHS_TOUCHED = 0
CROSS_LANE_CONTRACT_CHANGE_REQUIRED = NO
PRODUCTION_SCHEDULER_MUTATION_REQUIRED = NO
STRATEGY_SEMANTICS_CHANGED = NO
STATISTICAL_SEMANTICS_CHANGED = NO
PROVIDER_SEMANTICS_CHANGED = NO
EXECUTION_AUTHORITY_CHANGED = NO
FULL_HARD_CHEW = PASS
SECOND_EYE_ZIP_REQUIRED = YES
SECOND_EYE_ZIP_CREATED = YES
READY_FOR_SECOND_EYE_REVIEW = YES
MASTER_CHANGED_BY_BUILDER = NO
PRODUCTION_CHECKOUT_CHANGED = NO
PRODUCTION_CHECKOUT_CHANGED_BY_BUILDER = NO
AUTHORIZED_EXTERNAL_DOCS_ONLY_CANONICAL_ADVANCE = YES
PAPER_OR_EXECUTION_AUTHORITY_USED = NO
MERGE_AUTHORIZED = NO
```
