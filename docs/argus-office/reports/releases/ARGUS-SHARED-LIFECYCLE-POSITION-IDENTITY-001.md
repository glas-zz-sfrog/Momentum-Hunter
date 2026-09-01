# ARGUS-SHARED-LIFECYCLE-POSITION-IDENTITY-001

## Classification

- Status: `IMPLEMENTED_PENDING_INDEPENDENT_SECOND_EYE / NOT_MERGED`.
- Role: `INTEGRATION_STEWARD`.
- Task class: `SERIALIZED_CROSS_LANE_CONTRACT`.
- Canonical base: `986407467ae8de27df1bc228d843a8701014ac06`.
- Implementation commit: `a7858373c7eb4b8c8461aa13c881a199e6e75a9f`.
- Production activation: `NO`.
- Merge authorization: `NO`.
- GUI resume authorization: `NO`.

## Phase 1 Contract Inventory

- `LIFECYCLE_OPPORTUNITY_ID_AUTHORITY`:
  `candidate_lifecycle.expected_opportunity_id()` hashes the normalized symbol,
  session date, and originating evidence family under
  `candidate-opportunity-v1`; `CandidateLifecycleEvent.opportunity_id` and
  `CandidateLifecycleSnapshot.opportunity_id` persist it.
- `LIFECYCLE_SETUP_ID_AUTHORITY`:
  `candidate_lifecycle.expected_setup_id()` hashes the opportunity, setup
  family, and positive setup sequence under `candidate-setup-v1`;
  `CandidateLifecycleEvent.setup_id` and
  `CandidateLifecycleSnapshot.current_setup_id` persist it, with predecessor
  chronology for successors.
- `TRADE_PLAN_ID_AUTHORITY`:
  `IntradayPlanEvidence.plan_id`, created by the versioned intraday-plan
  canonical hash and persisted as `ContinuousProducerRecord.trade_plan_id`.
- `SHADOW_SELECTION_IDENTITY_AUTHORITY` before this task:
  `shadow_market_validity.opportunity_identity()` generated an independent
  `shadow-opportunity-v1` hash from report-row attributes, session, and plan
  fingerprint. It was not the lifecycle opportunity authority.
- `POSITION_ID_AUTHORITY`:
  `stable_id("shadow-position", shadow_trade_id)` at the prospective
  FakeBroker fill boundary.
- `OPENED_AT_AUTHORITY`:
  the accepted fill quote's exact timezone-aware `quote.timestamp`, persisted
  in `ShadowPosition.opened_at`.

The exact pre-task breaks were:

1. Continuous Producer did not expose `opportunity_id` as a first-class record
   field even though its lifecycle proposal owned it.
2. The persisted trade-planning row had no producer-issued lifecycle binding.
3. Shadow recomputed both a `shadow-opportunity-v1` identity and a legacy
   `tp-*` plan identity instead of consuming lifecycle opportunity/setup and
   producer TradePlan identities.
4. `ShadowTrade` and `ShadowOrderTicket` had no lifecycle `setup_id` or
   separately named Shadow selection identity.
5. `ShadowPosition` persisted position identity and chronology but no upstream
   opportunity/setup/TradePlan provenance.
6. The Python Engine read model and C# shared contract omitted lifecycle,
   position, and opened-at fields.
7. Legacy records could not be distinguished from a proven end-to-end join.

## Minimum Shared Contract

`momentum_hunter.lifecycle_position_identity` defines one additive, versioned
producer binding containing:

- `opportunity_id`
- `setup_id`
- `trade_plan_id`
- `producer_record_id`
- `producer_record_fingerprint`
- `binding_fingerprint`

The binding is accepted only when all three upstream IDs are lowercase
SHA-256 values, its shape/version/authority and fingerprint verify, and its
`trade_plan_id` exactly equals the persisted TradePlan row's embedded
`intraday_evidence.plan_id`. Symbol and timestamp are never inputs to this
join. The existing `shadow-opportunity-v1` value remains separately persisted
as optional `shadow_selection_id` and is no longer overloaded as lifecycle
opportunity identity.

New Producer records persist the lifecycle opportunity alongside setup and
TradePlan IDs. Pre-contract Producer records remain readable, omit
`opportunity_id` from their legacy fingerprint reconstruction, and cannot emit
a proven downstream binding.

## Shadow And Position Binding

Automatic selection now freezes all four distinct values in its decision
cycle: lifecycle opportunity, lifecycle setup, producer TradePlan, and Shadow
selection identity. `ShadowTradingService.start_trade()` rereads and validates
the persisted row binding and fails closed if the supplied selection evidence
does not match it exactly. Allocation and risk evidence use the producer
TradePlan ID.

At the first prospective fill, immutable `ShadowPosition` provenance receives
the exact `ShadowTrade` opportunity, setup, and TradePlan IDs in addition to
the existing authoritative `position_id` and `opened_at`. Partial fills and
later read refreshes preserve the original values. A later setup or TradePlan
for the same symbol cannot rewrite the stored position chain.

State validation rejects partial or contradictory new provenance. Legacy
positions with none of the additive fields remain loadable, but their read
linkage is `UNKNOWN`; they cannot join to Accepted. A pending trade without a
position is `NOT_AVAILABLE`. `PROVEN` additionally requires the producer-bound
row, exact trade/position ID equality, deterministic position identity, and a
parseable opened-at timestamp.

## Read Boundary And GUI Contract

The existing read-only Shadow review command now exposes `opportunityId`,
`setupId`, `tradePlanId`, `positionId`, `openedAt`, and `identityLinkage`.
`ShadowTradeIdentity` in the shared C# contracts carries the same fields. The
C# mapper rejects a claimed `PROVEN` chain without complete position chronology
and maps absent legacy fields to `UNKNOWN` / `NOT_AVAILABLE`.

No WPF view, view model, layout, visual binding, or presentation behavior was
implemented. No write command or execution capability was added.

## Exact Regression Proof

`tests.test_lifecycle_position_identity` proves all requested cases:

1. Accepted lifecycle setup through producer TradePlan to position: exact pass.
2. Two setups for one symbol: distinct setup and position chains.
3. Two TradePlans for one symbol: exact plan-to-position binding.
4. Legacy position without setup: `UNKNOWN` and non-joinable.
5. Missing position TradePlan ID: `UNKNOWN` and persistence rejection.
6. Mismatched setup/TradePlan provenance: persistence rejection.
7. Matching symbol with differing IDs: no join.
8. Exact IDs: `PROVEN` join.
9. `opened_at`: persistence/restart safe.
10. `position_id`: immutable across read refresh; tamper becomes `UNKNOWN`.
11. Successor setup after open: original position chain unchanged.

An additional tamper case rejects a report binding whose TradePlan ID no longer
matches its binding fingerprint and embedded plan. Producer tests prove the
actual lifecycle proposal's opportunity/setup and Producer plan form the
report-safe binding. C# tests prove complete, incomplete, and legacy mapping.

## Hard Chew

- Focused lifecycle/Producer/Shadow/selection/Engine tests: `155/155 PASS`.
- Exact identity-contract tests: `12/12 PASS`.
- Final approved-environment discovery: `2,892/2,892 PASS`, one expected
  Windows skip, `1,085.058s` unittest time.
- Approved environment fingerprint:
  `791197DEDD392BD3D5FA0D6FB051F395562E336ABF995FC9FBD633FAC28760C8`.
- .NET solution tests: `261/261 PASS` (`204` Presentation, `51` Integration,
  `6` Layout).
- Release build: `PASS`, zero warnings and zero errors.
- Compileall: `PASS`.
- Git diff check: `PASS`.
- Secret scan: `PASS`, zero matches.
- New provider/authentication/order capability scan: `PASS`, zero matches.
- Protected-path review: `PASS`; only the declared lifecycle, Producer,
  Shadow, Engine read-boundary, shared C# contract, tests, and Integration-owned
  governance/report paths changed.

The full approved runner proved it loaded this isolated task worktree from the
external approved environment and that the worktree contained no local
`.venv`. No provider, authentication, broker, account, Paper, live-order,
service, scheduler, installed runtime, database, or production-state call was
performed.

## Lane Impact And Boundaries

- `LIFECYCLE`: additive downstream identity preservation only.
- `CONTINUOUS_PRODUCER`: additive opportunity field and binding export.
- `SHADOW`: selection provenance and position persistence only; not activated.
- `ENGINE_READ_BOUNDARY`: additive read-only fields only.
- `GUI_SHARED_CONTRACT`: additive shared record fields only.
- GUI presentation implementation: none.
- Science research semantics: unchanged.
- Candidate qualification, scoring, readiness, TradePlan generation, entry,
  stop/target, selection policy, position sizing, risk, exits, and broker/order
  authority: unchanged.

## Required Agent Closeout

- Branch: `codex/ARGUS-SHARED-LIFECYCLE-POSITION-IDENTITY-001`.
- Scope: minimum authoritative lifecycle-to-Shadow-position provenance bridge.
- Files changed: five Python runtime/bridge files, one new Python contract,
  two shared C# contract/mapper files, three test files, and Integration-owned
  closeout documents.
- Tests/checks: exact identity cases, lifecycle, Producer, Shadow, restart,
  Engine read model, C# mapping, full Python, full .NET, Release build,
  compileall, diff, secret, capability, and protected-path checks.
- Evidence for changed behavior: only a complete producer-bound exact ID chain
  can return `PROVEN`; legacy, partial, mismatched, symbol-only, and tampered
  chains remain non-joinable.
- Protected areas reviewed: runtime persistence and Shadow behavior were
  changed only for provenance; no trading or execution semantic changed.
- Push/merge status: candidate branch is to be pushed normally; canonical
  remains unchanged; merge is not authorized.
- Risks: consumers must supply the new producer-issued report binding; older
  reports and records intentionally fail closed for Accepted-to-Active joins.
- Manual QA: none; no visual implementation.
- Open questions: independent second-eye adjudication is required.
- Recommendation: independently reproduce the package, review exact provenance
  and fail-closed cases, and authorize a separate integration task only after a
  passing decision.

## Final Classifications

```text
AUTHORITATIVE_OPPORTUNITY_ID_PRESERVED = YES
AUTHORITATIVE_SETUP_ID_PRESERVED = YES
AUTHORITATIVE_TRADE_PLAN_ID_PRESERVED = YES
AUTHORITATIVE_POSITION_ID_PRESERVED = YES
AUTHORITATIVE_OPENED_AT_PRESERVED = YES
SHADOW_CONSUMES_AUTHORITATIVE_OPPORTUNITY_ID = YES
SHADOW_CONSUMES_AUTHORITATIVE_SETUP_ID = YES
SHADOW_CONSUMES_AUTHORITATIVE_TRADE_PLAN_ID = YES
SYMBOL_ONLY_MATCHING_USED = NO
TIMESTAMP_HEURISTIC_MATCHING_USED = NO
ACCEPTED_ACTIVE_JOIN_PROVEN = YES
TWO_SETUPS_SAME_SYMBOL_DISTINGUISHED = YES
LEGACY_UNKNOWN_STATES_PRESERVED = YES
IDENTITY_CHAIN_RESTART_SAFE = YES
READ_BOUNDARY_EXPOSES_OPPORTUNITY_ID = YES
READ_BOUNDARY_EXPOSES_SETUP_ID = YES
READ_BOUNDARY_EXPOSES_TRADE_PLAN_ID = YES
READ_BOUNDARY_EXPOSES_POSITION_ID = YES
READ_BOUNDARY_EXPOSES_OPENED_AT = YES
GUI_PRESENTATION_IMPLEMENTED = NO
TRADING_POLICY_CHANGED = NO
SHADOW_SELECTION_POLICY_CHANGED = NO
EXECUTION_AUTHORITY_CHANGED = NO
SCIENCE_LANE_SEMANTICS_CHANGED = NO
SECOND_EYE_ZIP_REQUIRED = YES
MERGE_AUTHORIZED = NO
GUI_RESUME_AUTHORIZED = NO
```
