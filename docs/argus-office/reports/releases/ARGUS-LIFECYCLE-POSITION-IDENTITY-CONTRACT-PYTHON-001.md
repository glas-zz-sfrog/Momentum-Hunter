# ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-001

## Classification

- Status: `IMPLEMENTED_PENDING_INDEPENDENT_SECOND_EYE / NOT_MERGED`.
- Lane: `OPENING_ENGINE`.
- Canonical base: `2bceeeadd06f5ed85943942f1c0f81b7094620f7`.
- Executable implementation head: `059de30c4f1b32e9ce8e1f28e1f923cdc27833ee`.
- Production activation: `NO`.
- Friday canonical freeze: `PRESERVED`.

## Implemented Contract

The existing lifecycle authority remains unchanged. Its persisted
`opportunity_id` and `setup_id` now flow into `ContinuousProducerRecord`, a
fingerprinted Producer-to-report binding, the Shadow trade and ticket, and the
first prospectively filled `ShadowPosition`. The resulting chain is:

```text
opportunity_id
-> setup_id
-> trade_plan_id
-> position_id
-> opened_at
```

The Producer payload preserves all three upstream identities and validates
them against the exact composition member result. A report row can acquire
authoritative provenance only through the complete Producer binding. The
embedded TradePlan ID must equal the row's exact intraday plan ID; symbol and
timestamp are not identity inputs.

Shadow preserves the existing independent selection identity as
`shadow_selection_id`. It is no longer overloaded as lifecycle opportunity
identity. At first fill, the exact upstream triple is copied to the position;
partial-fill completion and restart preserve the original `position_id` and
first `opened_at` timestamp.

## Linkage States

The Python read/review boundary exposes `opportunityId`, `setupId`,
`tradePlanId`, `positionId`, `openedAt`, and `linkageStatus`.

- `PROVEN`: complete Producer binding, exact trade/position provenance,
  deterministic position identity, and persisted opening chronology verify.
- `UNAVAILABLE`: a complete authoritative trade chain exists, but no position
  has been created yet.
- `LEGACY_UNBOUND`: the pre-contract record/report contains no authoritative
  Producer binding or position provenance.
- `UNKNOWN`: provenance is partial, malformed, contradictory, or tampered.

Legacy records remain readable and never become `PROVEN`. A malformed claimed
binding cannot fall back to legacy behavior. Duplicate same-symbol rows,
supplied-ID disagreement, position provenance drift, and partial authoritative
chains fail closed.

## Files And Scope

Runtime/read-boundary changes:

- `momentum_hunter/lifecycle_position_identity.py`
- `momentum_hunter/continuous_tradeplan_producer.py`
- `momentum_hunter/shadow_selection.py`
- `momentum_hunter/shadow_trading.py`
- `momentum_hunter/terminal_review_packet.py`
- `momentum_hunter/workstation_shadow.py`

Test changes:

- `tests/test_lifecycle_position_identity.py`
- `tests/test_continuous_tradeplan_producer.py`
- `tests/test_shadow_trading.py`

No C#, GUI, Science, provider, service, scheduler, manifest, configuration,
Paper/live broker, account, position-source, or order-transmission file changed.
Trading policy, setup semantics, entry/exit logic, risk, and sizing are unchanged.

## Verification

- Exact identity-contract tests: `11/11 PASS`.
- Approved focused/adjacent suite: `374/374 PASS` in `148.596s`.
- Full approved-environment discovery: `3039/3039 PASS` in `1168.253s`
  unittest time, one expected Windows symlink-privilege skip.
- Approved environment fingerprint:
  `791197DEDD392BD3D5FA0D6FB051F395562E336ABF995FC9FBD633FAC28760C8`.
- Loaded package root: this isolated Engine lane.
- Lane-local virtual environment: absent.
- Compileall: `PASS`.
- Git diff check: `PASS`.
- Secret scan: `PASS`, zero findings.
- New execution-capability scan: `PASS`, zero findings.
- Protected-path review: `PASS`.
- Canonical nonmutation: `PASS`; local/origin master remained synchronized and
  clean at the frozen canonical SHA.

## Boundaries And Risks

This is a dormant Python contract. It creates no provider contact, process,
service, schedule, account read, Paper/live authority, or order capability.
The existing Shadow engine remains nontransmitting and was not activated.

The C# GUI contract does not yet consume these additive fields, by directive.
That is the intended next separately authorized cross-lane implementation after
independent review. Producer consumers must explicitly bind report rows before
claiming a proven lifecycle-to-position chain.

## Required Closeout

```text
TASK_STATUS = IMPLEMENTED_PENDING_INDEPENDENT_SECOND_EYE
PRE_TASK_CANONICAL = 2bceeeadd06f5ed85943942f1c0f81b7094620f7
AUTHORITATIVE_OPPORTUNITY_ID_END_TO_END = YES
AUTHORITATIVE_SETUP_ID_END_TO_END = YES
AUTHORITATIVE_TRADE_PLAN_ID_END_TO_END = YES
AUTHORITATIVE_POSITION_ID_PRESERVED = YES
AUTHORITATIVE_OPENED_AT_PRESERVED = YES
PRODUCER_OPPORTUNITY_BINDING_IMPLEMENTED = YES
SHADOW_UPSTREAM_PROVENANCE_IMPLEMENTED = YES
PYTHON_READ_BOUNDARY_COMPLETE = YES
LINKAGE_STATUS_STATES = PROVEN / UNKNOWN / UNAVAILABLE / LEGACY_UNBOUND
SYMBOL_ONLY_MATCHING_USED = NO
HEURISTIC_RECONSTRUCTION_USED = NO
LEGACY_UNBOUND_PRESERVED = YES
TRADING_POLICY_CHANGED = NO
GUI_CHANGED = NO
SCIENCE_LANE_TOUCHED = NO
PROVIDER_CHANGED = NO
SERVICE_CHANGED = NO
SCHEDULER_CHANGED = NO
PAPER_OR_EXECUTION_AUTHORITY_USED = NO
FOCUSED_TESTS = 374/374 PASS
FULL_HARD_CHEW = PASS
FULL_SUITE = 3039/3039 PASS
EXPECTED_SKIPS = 1
IMPLEMENTATION_HEAD = 059de30c4f1b32e9ce8e1f28e1f923cdc27833ee
BRANCH = codex/ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-001
PUSHED = YES
CANONICAL_CHANGED = NO
MERGE_PERFORMED = NO
CANONICAL_CLEAN = YES
LOCAL_ORIGIN_SYNC = YES
READY_FOR_INDEPENDENT_SECOND_EYE_REVIEW = YES
READY_FOR_GUI_CSHARP_CONTRACT_IMPLEMENTATION = YES
```

## Agent Report

- Branch: `codex/ARGUS-LIFECYCLE-POSITION-IDENTITY-CONTRACT-PYTHON-001`.
- Scope: Python-only lifecycle-to-Shadow position provenance.
- Files changed: six Python runtime/read-boundary files, three test files, and
  this branch-specific report.
- Tests/checks: exact contract, adjacent Engine/Shadow/Continuous tests, full
  approved discovery, compileall, diff, secret, capability, and protected-path
  review.
- Evidence: only the exact persisted Producer chain can become `PROVEN`; all
  legacy, unavailable, partial, mismatched, repeated-symbol, and tampered cases
  remain explicitly non-proven.
- Protected areas: persistence/runtime identity only; trade economics and
  execution authority unchanged.
- Push/merge: implementation pushed; canonical not changed; merge prohibited.
- Risks: downstream C# consumption remains intentionally absent; review is
  required before any serialized integration.
- Manual QA: none; no visual change.
- Open questions: independent second-eye decision.
- Recommendation: review the immutable package, then authorize a separate
  integration and C# contract task only after PASS.
