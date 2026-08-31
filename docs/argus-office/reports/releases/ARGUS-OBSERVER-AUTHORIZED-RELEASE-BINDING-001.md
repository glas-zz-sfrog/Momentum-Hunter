# ARGUS-OBSERVER-AUTHORIZED-RELEASE-BINDING-001

## Classification

- Status: `IMPLEMENTED_PENDING_SECOND_EYE / UNMERGED / UNDEPLOYED`
- Lane: `OPENING_ENGINE`
- Base canonical: `4a8b0bbbb5354dd31ea4c3a847a4061ab18fbf49`
- Task branch: `codex/ARGUS-OBSERVER-AUTHORIZED-RELEASE-BINDING-001`
- Implementation commit: `2e1f1f7`
- Product strategy semantics changed: `NO`
- Statistical semantics changed: `NO`
- Provider semantics changed: `NO`
- Execution authority changed: `NO`
- Scheduler mutation required or performed: `NO`
- Cross-lane contract change required: `NO`
- Second-eye review required: `YES`

## Root Cause

The stale expectation did not originate in repository source, installed runtime
configuration, or a Windows Scheduled Task. It was copied directly into the
one-time Codex heartbeat payload named `argus-monday-freeze-checkpoint` when
that observer was created.

The preserved source record is:

- session file:
  `C:\Users\steve\.codex\sessions\2026\08\26\rollout-2026-08-26T20-00-02-01a040bb-293a-74b3-930c-c435010a19c0.jsonl`
- record timestamp: `2026-08-31T13:35:32.406Z`
- record ordinal: `10384`
- embedded predecessor release:
  `OPENING-RUNTIME-F18C1CE093F7ECCB489F`
- embedded predecessor fingerprint:
  `f18c1ce093f7eccb489fcf1d839996da894970e49bc3b1e56477012df25a397a`

The task-time snapshot assumption therefore outlived an independently reviewed
promotion to successor release `OPENING-RUNTIME-1C49F7F328503BF8FECF`.
There was no separate observer state or repository function that refreshed the
copied values before the heartbeat ran.

## Authority And Repair

Default operational observation now uses explicit mode
`CURRENT_AUTHORIZED_RELEASE`. At evaluation time it reads and verifies the
existing authoritative Opening release mechanism:

`C:\ProgramData\MomentumHunter\Automation\opening-runtime\channels\opening-capture.json`

Resolution delegates to `OpeningRuntimeReleaseStore.verify_channel()`, which
validates the channel pointer fingerprint, complete ordered promotion receipt
chain, receipt fingerprints and predecessor relationships, and the referenced
immutable release record. The observer never treats the installed runtime as
authority merely because it exists.

An explicit `FIXED_EXPECTED_RELEASE` mode remains available for intentional
historical replay. It requires both release identity and runtime fingerprint,
then verifies that pair against the immutable release record. It is not the
operational default.

Independent observation evidence remains mandatory and is separately checked
for schema, actual release identity, actual runtime fingerprint, canonical Git
identity, and canonical worktree cleanliness. Missing or malformed authority,
inconsistent promotion data, unreadable observation evidence, runtime mismatch,
and canonical drift all fail closed.

## Monday Replay

Persisted Monday opening truth showed:

- job: `opening-capture-20260831`
- status: `COMPLETED`
- exit code: `0`
- started: `2026-08-31T08:35:00.138251-05:00`
- completed: `2026-08-31T08:35:16.641187-05:00`
- actual release: `OPENING-RUNTIME-1C49F7F328503BF8FECF`
- actual runtime fingerprint:
  `1c49f7f328503bf8fecfd359af084c01d5a731133ae4ec1555aa5b1f88997151`
- canonical Git at execution:
  `23ee162373654e1db91af4c19f75bbc7887e3174`
- runtime match: `true`

The exact preserved observation evaluated in fixed predecessor mode returns:

`MONDAY_REPLAY_BEFORE_FIX = FAIL_STALE_EXPECTATION`

It reports `RUNTIME_DRIFT` because F18 is intentionally compared with actual
1C49. The same evidence evaluated in current-authorized mode resolves 1C49 from
the verified channel and returns:

`MONDAY_REPLAY_AFTER_FIX = PASS`

with `AUTHORIZED_RUNTIME_MATCH`, equal expected/actual release and fingerprint,
and no runtime or canonical drift.

## Negative And Transition Proof

Focused coverage passes 11/11 cases:

1. Authorized A plus actual A passes.
2. Authorized successor B plus actual predecessor A fails `RUNTIME_DRIFT`.
3. Unknown or malformed actual fingerprint fails evidence validation.
4. Missing channel fails closed.
5. Missing authority root fails closed without creating the root.
6. Malformed promotion receipt fails closed.
7. Matching release name with a different fingerprint fails.
8. Matching fingerprint with inconsistent channel metadata fails closed.
9. Canonical SHA drift fails.
10. Dirty canonical worktree fails.
11. Promotion A to B before observer execution resolves B dynamically, while
    explicit fixed-A mode remains bound to A and rejects actual B.

## Opening Closure Proof

The three task files were overlaid onto identical canonical Product bytes in a
single disposable root and the authoritative Opening identity was recomputed
before and after the overlay. Both computations produced:

- component count: `99`
- approved runtime fingerprint:
  `f4951e228b19cb42d6a5db701898ae85abc4fd4fc19433b1965beb04bd0e3cbe`
- runtime surface fingerprint:
  `b0b3fffeed0ab0aa71cd506d6b0819a1b1ebab6d4ce2cc37fddab2fe8eee9695`
- configuration fingerprint:
  `00e48de1ab055ab235fdd9b60b190da3f84ccba49fccac9183511c0b806af18a`
- environment fingerprint:
  `bebbd08cb0916b4167a160eb1847611bb5ba0e5a8aba893b428c769854fad5fd`

The observer module, verifier tool, and observer test are excluded from the
authoritative opening dependency closure. The approved runtime identity is
unchanged.

## Hard Chew

- Focused observer tests: `11/11 PASS`.
- Opening identity/release/automation regressions: `171/171 PASS`, one expected
  Windows symlink-privilege skip.
- Full Python discovery: `2880/2880 PASS`, one expected Windows skip, completed
  in `1044.466s`.
- `compileall`: `PASS`.
- PowerShell parsing: `NOT_APPLICABLE`; no PowerShell changed.
- `git diff --check`: `PASS`.
- Capability scan: `PASS`; no provider, network, subprocess, service, scheduler,
  credential, account, broker, position, Paper, Shadow, or order capability is
  imported or acquired.
- Protected-path review: `PASS`; no strategy, scoring, readiness, TradePlan,
  provider, statistical, Paper, Shadow, account, broker, position, order,
  service, manifest, scheduler, installed-runtime, or canonical bytes changed.
- Canonical production checkout: clean synchronized `master` at the accepted
  base throughout Builder work.
- Production Automation and Continuous manifests: byte-unchanged.
- Opening authorized-channel pointer: byte-unchanged.
- Automation, Continuous Runtime, and Continuous Writer services:
  `Running / Automatic`, unchanged.
- The task made no provider call and did not read or write credential contents.
  During the long verification run, the independently installed research-only
  Continuous Runtime naturally advanced a discovery cycle at
  2026-08-31T19:05:20Z. Its Finviz source evidence and writer records have that
  timestamp, and encrypted secrets.bin refreshed at
  2026-08-31T19:05:20.9107488Z. The account-binding and refresh-lock files
  remained byte-identical. This is preserved as authorized external production
  activity, not task provider contact or task-caused auth mutation.

## Files Changed

- `momentum_hunter/opening_runtime_observer.py`
- `tools/verify_opening_runtime_observer.py`
- `tests/test_opening_runtime_observer.py`
- this task release report

## Evidence

Task evidence is under:

`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-OPENING-ENGINE\ARGUS-OBSERVER-AUTHORIZED-RELEASE-BINDING-001-4a8b0bbbb535`

It includes the stale-payload source extraction, independent Monday runtime
observation, pre-fix and post-fix replay results, complete authoritative release
fixture, opening-closure proof, focused log, and full-suite log.

## Protected Boundary And Risk

No scheduler, installed observer, runtime, release, channel, manifest, service,
canonical checkout, Paper, Shadow, brokerage, account, position, or order state
was modified by this task. The independently running Continuous service's
ordinary auth refresh is recorded separately above. The branch is intentionally
unmerged and undeployed. Until a separately authorized activation replaces
future fixed heartbeat values with this verifier, production behavior remains
unchanged.

## Required Agent Closeout

- Branch: `codex/ARGUS-OBSERVER-AUTHORIZED-RELEASE-BINDING-001`.
- Scope: dynamic authorized Opening release binding and fail-closed observer
  integrity only.
- Tests or checks run: focused, adjacent Opening/automation regressions, full
  Python discovery, compileall, replay, closure identity, diff, capability,
  protected-state, and secret checks.
- Evidence for changed behavior: Monday fixed-F18 replay fails while the same
  observation resolves and passes authorized 1C49 in current-authorized mode.
- Protected areas reviewed: all listed above; unchanged.
- Push/merge status: implementation and qualification commits are pushed;
  second-eye sealing follows the frozen documentation head. Merge and
  deployment are unauthorized.
- Risks: activation is intentionally deferred; future observer creation must
  invoke the reviewed current-authorized verifier rather than copy release IDs.
- Manual QA: none; this task is nonvisual.
- Open questions: none within implementation scope.
- Recommendation: complete independent second-eye review before any merge or
  scheduler/observer activation directive.

## Final Classifications

```text
OBSERVER_AUTHORIZED_RELEASE_BINDING_IMPLEMENTED = YES
STALE_EXPECTATION_ROOT_CAUSE = ONE_TIME_CODEX_HEARTBEAT_PAYLOAD_COPIED_F18_AT_CREATION
CURRENT_AUTHORIZED_RELEASE_SOURCE = OPENING_CAPTURE_CHANNEL_PLUS_VERIFIED_PROMOTION_CHAIN_AND_IMMUTABLE_RELEASE
HARDCODED_PREDECESSOR_BINDING_REMOVED = YES
CURRENT_AUTHORIZED_RELEASE_MODE = PASS
FAIL_CLOSED_ON_UNKNOWN_AUTHORITY = YES
FAIL_CLOSED_ON_RUNTIME_MISMATCH = YES
MONDAY_REPLAY_BEFORE_FIX = FAIL_STALE_EXPECTATION
MONDAY_REPLAY_AFTER_FIX = PASS
MONDAY_EXPECTED_RELEASE = OPENING-RUNTIME-1C49F7F328503BF8FECF
MONDAY_RUNTIME_DRIFT_AFTER_FIX = NO
PROMOTION_A_TO_B_TRANSITION_TEST = PASS
STRATEGY_SEMANTICS_CHANGED = NO
STATISTICAL_SEMANTICS_CHANGED = NO
PROVIDER_SEMANTICS_CHANGED = NO
EXECUTION_AUTHORITY_CHANGED = NO
CROSS_LANE_CONTRACT_CHANGE_REQUIRED = NO
SCHEDULER_MUTATION_REQUIRED = NO
FULL_HARD_CHEW = PASS
SECOND_EYE_ZIP_REQUIRED = YES
SECOND_EYE_ZIP_CREATED = PENDING
READY_FOR_SECOND_EYE_REVIEW = PENDING_PACKAGE
MASTER_CHANGED_BY_BUILDER = NO
PRODUCTION_CHECKOUT_CHANGED = NO
PAPER_OR_EXECUTION_AUTHORITY_USED = NO
TASK_PROVIDER_CONTACT = NO
PROVIDER_AUTH_STATE_CHANGED_BY_TASK = NO
AUTHORIZED_EXTERNAL_PROVIDER_AUTH_REFRESH_OBSERVED = YES
MERGE_AUTHORIZED = NO
```
