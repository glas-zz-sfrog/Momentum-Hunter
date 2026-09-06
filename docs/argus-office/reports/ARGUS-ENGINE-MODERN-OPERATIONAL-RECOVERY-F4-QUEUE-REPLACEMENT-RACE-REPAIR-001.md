# F4 Queue Replacement Capacity Race Repair

Status: IMPLEMENTED_PENDING_MERGE / PENDING_INDEPENDENT_SECOND_EYE.
No merge, deployment, activation, provider call, or execution is authorized here.

## Identity And Scope

- Task: ARGUS-ENGINE-MODERN-OPERATIONAL-RECOVERY-F4-QUEUE-REPLACEMENT-RACE-REPAIR-001
- Branch: codex/ARGUS-ENGINE-MODERN-OPERATIONAL-RECOVERY-F4-QUEUE-REPLACEMENT-RACE-REPAIR-001
- Rejected parent: c61e7d60271ee3c4d35274f69dd79d8172ce74e3, preserved unchanged.
- Canonical: 2bceeeadd06f5ed85943942f1c0f81b7094620f7, unchanged.
- Product delta: momentum_hunter/continuous_runtime.py only.
- Tests: new test_modern_recovery_queue_capacity.py; remove the redundant
  explicit checkpoint from the existing modern checkpoint fixture because
  queue admission now persists its own complete operation.
- Shared Roadmap, Branch Ledger, Task Log, GUI, Science, and production are not
  edited by this Engine-lane task.

## Root Finding

The historical replacement call did not reach its own save: request_discovery
could return REPLACED_OBSOLETE while its replacement existed only in memory.
A competing direct publication or prepared-journal completion could consume the
last slot after a positive precheck. The runtime still advertised active work.
The new tests separately exercise both that earlier enqueue interleaving and
the explicit store-save boundary losing its last slot.

## Repair

Modern state-changing operations serialize against inspection. Queue admissions
and their complete parent processing require authoritative persistence before
returning success. Nested discovery/readiness, composition plus denominator,
provider-bound, event, and evidence work commits as a complete parent operation.
Comparing the actual checkpoint-coupled state suppresses no-op writes without
weakening required persistence; an idle tick retains its one ordinary checkpoint.

Capacity failure permanently blocks that runtime instance, disables new work,
releases its logical active lease, and restores the committed inspection state.
The failed proposal is memory-only with authority NONE. Independent durable
attempt/fill/position/writer stores are never rolled back. If current inspection
fails, only a last-known committed cache can be used, with an explicit public
inspection-unavailable health flag. Lifetime physical owner exclusion may remain
solely for inspection/cleanup until the owning context exits; it is not an active
logical lease and grants no additional work.

Exactly 4096 remains readable/validatable/inspectable but not actively writable
or restartable. A legitimate final-slot commit is retained and then the runtime
blocks. No 4097/4098 write, limit increase, truncation, or history rollover is added.

## Verification

- Before controls: six expected failures on the rejected product; four expected
  failures reproduce the first intermediate review's parent-atomicity defects;
  three expected failures reproduce the second review's no-op checkpoint churn.
- Final targeted controls: 42 tests, zero failures/errors.
- Fresh complete discovery: 3212 tests, zero failures/errors, one expected
  Windows symlink-privilege skip; approved interpreter/environment only.
- Full discovery includes all three real unpatched 4096 history/race tests.
- F3, P1/P2, fill custody, queue/JSON, snapshot TOCTOU, Continuous/Opening
  separation, obligations and unchanged risk/sizing/economics regressions pass.
- Compileall, scoped diff/byte checks, and changed-file secret scan pass.
- One bounded non-Astra reviewer: REVIEW-01 and REVIEW-02 rejected intermediate
  snapshots; REVIEW-03 returns ACCEPT_PRE_FREEZE on the final product/test bytes.
- Formal independent second-eye remains pending; no Astra acceptance is claimed.
- No WRITER_SLOW failure recurred; writer code and timing budgets are unchanged.

The immutable packet binds the final commit/tree to exact Git blobs and the full
suite source-byte inventory. Packaged-source and extracted-ZIP reruns are separate
mandatory handoff gates, recorded in the external final receipts rather than
being inferred from these source-level results.

## Evidence And Remaining Gates

External evidence root:
C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-OPENING-ENGINE\evidence\ARGUS-ENGINE-MODERN-OPERATIONAL-RECOVERY-F4-QUEUE-REPLACEMENT-RACE-REPAIR-001

Use FINAL-REPORT.json, FINAL-PACKAGE-RESULT.json, QUALIFICATION.json,
FULL-SUITE-ROSTER.json, REGRESSION-MAP.md, ROOT-AND-LEASE-AUDIT.md, and
pre-freeze-review/REVIEW-03.md for the exact final handoff facts.

The rejected ZIP remains A1072920181A3E84BE3266837230E7624E9CBF3118C73E1B1DE80777B87F640F.
Its independent-review manifest remains 0803D7B1B299388FE15A8D9AD10E63B3A9BD32A5543FD8302FA442A03E249C0B.

Next: fresh independent second-eye of this frozen candidate. Canonical integration
is NO_PENDING_SECOND_EYE; Paper readiness is NO. Checkpoint-history management,
524 KB discovery custody V3, native Continuous risk production, and C# rebinding
remain separate downstream work. No operator/manual visual check is required.
