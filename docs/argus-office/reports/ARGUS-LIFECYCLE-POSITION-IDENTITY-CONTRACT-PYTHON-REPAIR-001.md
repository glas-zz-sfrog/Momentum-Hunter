# Python Lifecycle Position Identity: Bounded Repair

Task: `ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-REPAIR-001`

Status: `IMPLEMENTED_PENDING_INDEPENDENT_SECOND_EYE` (unmerged). Branch-only; no integration authority.

## Frozen Lineage

- Canonical base: `2bceeeadd06f5ed85943942f1c0f81b7094620f7`.
- Rejected executable: `059de30c4f1b32e9ce8e1f28e1f923cdc27833ee`.
- Rejected final parent: `34dcd951b94738544d24acd68adaa1b3d3965993`.
- Rejected evidence summary remains `D6FA99C6412EB5CD015BEF8F8DA94941DC9D7FFBD4AFFC943E04899A29BB9975`.
- Rejected ZIP remains `5C885D6A9D0BEF89CD2BCF99816262CF8EECD045008D26EBE5795A42D3A9A0B4`.
- Parked C# candidate remains `9437d7e03cf09d92b03b9f5fdd55ca3a27fee7fd`.
- Repair branch: `codex/ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-REPAIR-001`.
- Implementation commit: `a8a010a397c5728d2bee9ba9f93c1833459fe914`. The final review head adds this report only and is bound by package metadata and Git history; neither rejected commit is rewritten.

## Repairs

1. `ContinuousTradePlanProducerStore` now persists deterministic bound report rows in its existing JSON `candidates` array alongside the authoritative `records`. Record/row projection happens before the same atomic write. Reload verifies the entire projection against the records, including levels and bindings. Marker-absent historical records are not retrospectively bound; present unsupported markers fail closed.
2. `producer_bound_report_row` is a real Product caller of `bind_report_row_to_producer_identity`. Normal `LiveCompositionSource.compose` also carries the same row in `naturalSteps[].producerBoundReportRow` before the existing natural preview transaction commits. No wrapper injects identity.
3. An ongoing setup evaluation without a new lifecycle proposal preserves opportunity/setup from the supplied authoritative lifecycle snapshot. The snapshot is preserved in the fingerprinted record and checked for exact identity derivation, symbol/session, event presence, and cutoff chronology. A no-plan evaluation does not invent a new TradePlan.
4. `ShadowTradingService.start_trade` selects by exact persisted opportunity/setup/TradePlan tuple when supplied, validates the binding, and only then checks symbol consistency. The frozen-evidence auditor uses the same selector. Contradictory/missing/duplicate exact claims fail closed. Legacy singleton lookup remains for actual unbound records; multiple same-symbol rows without exact disambiguation remain rejected.

## Proof Boundaries

All market inputs in this task are offline deterministic test inputs. No live provider/canary or production Shadow run occurred.

The natural Product-path proof starts with candle evidence and uses the existing natural setup/lifecycle and Producer classes to issue and persist the binding. Shadow consumes the exact persisted row. Those rows remain `RESEARCH_ONLY`, have no sizing or execution-readiness grant, and produce a blocked Shadow record with **no order and no position**. This repair does not create an execution adapter or fabricate risk authorization.

The repeated-MU proof separately uses Product lifecycle/Producer evaluation to persist plans A and B in one population, then selects B by exact identity in either row order. Both are research rows. Existing execution-ready synthetic Shadow fixtures separately prove preserved position identity, first-fill `opened_at`, later partial fills, restart, successor immutability, and all four linkage states.

An existing TradePlan can have multiple lifecycle revisions with the same exact tuple. This repair does not collapse those revisions or pick a latest row by timestamp/order. Duplicate exact tuples remain fail-closed. It does not claim every historical revision is uniquely selectable.

## Verification

- First broader approved-environment run: 402 tests PASS, 147.466 seconds; source plus then-current repair tests. The two subsequently added tests concern binding-failure atomicity and legacy no-upgrade, not a Product behavior change.
- Final focused repair tests: 21 PASS (9 natural/Producer plus 12 selector).
- Additional frozen-byte probes: no order/position from natural research rows; six unsupported marker type/value cases rejected.
- Full approved-environment discovery: 3,060 tests PASS in 1,347.612 seconds (runner elapsed 1,354.173 seconds); one expected Windows symlink-privilege skip (`WinError 1314`).
- All 518 source/test/tool working-tree byte hashes remained identical across full discovery; normalized Git blob identities bind these tested bytes to the implementation commit.
- Compileall over `momentum_hunter`, `tests`, and `tools`: PASS; generated cache confined to disposable TEMP.
- `git diff --check`: PASS.
- Protected-path review: PASS; only three Product files and three test files changed. 112 other existing Shadow methods remain AST-identical.
- Context-aware precommit secret scan: PASS, zero unresolved matches; inherited exact source/test literals from the prior scanned ZIP are disclosed.
- Builder self-review: no outstanding concrete blockers; not an independent second-eye acceptance.
- Pre-ZIP and extracted-ZIP focused reruns are separate release gates recorded by the accompanying external `package-result.json` and `CLOSEOUT.json`, not inferred from branch test success.
- Production nonmutation: PASS across before/after canonical, service state and executable hashes, task-definition hashes, manifests, and Observer configuration.

Approved Python: `C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe`.

Approved environment fingerprint: `791197DEDD392BD3D5FA0D6FB051F395562E336ABF995FC9FBD633FAC28760C8`.

External evidence root:
`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-OPENING-ENGINE\evidence\ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-REPAIR-001`.

Evidence includes task registration, source/test caller map, frozen executable inventories, complete test output, protected-state snapshots, additional probes, and exact Git/package binding. Full discovery runs in the Engine worktree; exported source is independently rerun with the applicable focused suite. The packet does not claim a full repository discovery from a source-only export lacking unrelated GUI/governance assets.

## Boundaries And Recommendation

No changes to trading policy, entry/exit economics, sizing, allocation, provider behavior, C#, GUI, Science, services, scheduler, installed runtime, or authentication. No Paper/live/order authority was used. No merge, deployment, activation, or canonical update was performed. The Friday canonical freeze remains in force.

The repair requires a new independent second-eye ACCEPT before serialized integration. The parked C# candidate requires rebind/review against the accepted repaired Python contract. No visual/manual QA is applicable. No open decision is delegated to Steven beyond independent review and later integration authority.

`READY_FOR_CANONICAL_INTEGRATION = NO`
