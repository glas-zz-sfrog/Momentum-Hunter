# ARGUS-CONTINUOUS-003 Current-Head Integration

## Classification

`IMPLEMENTED_PENDING_MERGE`

## Baseline And Lineage

- Current canonical base: `e98b5cc1bab336c19305d1ca48b19b0aec45c9c6`.
- Integration branch: `codex/ARGUS-CONTINUOUS-003-current-head-integration`.
- Proven source branch: `codex/ARGUS-CONTINUOUS-002-offline-contract-reconciliation`
  at `657cb37`.
- Continuous prerequisite: `f6b776e`.
- Source slices: MONITOR-001, REGIME-001, EVENT-001, CATALYST-002A,
  BREAKOUT-001/002A, PLAN-002A, and SHADOW-025A.

## Integrated Dormant Contracts

- Candidate lifecycle and material-trigger coordination.
- Rolling market/sector regime and macro-event context.
- Provider-neutral catalyst evidence.
- Immutable prospective plan versions and authority binding.
- Sequential breakout research/outcome evidence.
- Non-live event-driven decision cycles and suppression receipts.

The eight modules remain dormant. Existing runtime code does not import them,
and this task adds no source loop, persistence writer, provider capability, or
execution path.

## Verification

- Python compileall: PASS.
- Eight-module focused suite: 254 / 254 PASS.
- Adjacent plan, RVOL, allocation, Paper, Shadow, and candle tests:
  228 / 228 PASS.
- Full Python discovery: 1,715 / 1,715 PASS in 222.673 seconds.
- The first discovery launch was deliberately terminated by an undersized shell
  timeout. Its immediate rerun encountered one leftover write-once test artifact
  and one process-order count assertion. Both affected modules passed 15 / 15
  together after cleanup, and the clean full rerun above passed without a code
  change; neither initial result is counted as passing evidence.
- Source identity: 29 / 29 restored artifacts match `657cb37` exactly.
- Existing-runtime import scan: zero hits.
- Network/provider/broker/order/production-data capability scan: zero hits.
- Changed-file credential-shape scan: zero hits.
- Protected-path review: only the eight new dormant modules, their eight tests,
  and governance/release evidence changed; no existing protected implementation
  file changed.
- Cached `git diff --check`: PASS.
- Staged-diff self-review: PASS; 36 expected paths and no unrelated path.

## Protected Boundary

No existing runtime module, score, readiness rule, alert, selection path,
TradePlan semantics, Risk Governor, allocation policy, Shadow state, Paper
state, account/provider/broker/order path, service, scheduler, Engine Host,
WPF, database/schema, package, credential, raw capture, generated report, or
production persistence behavior is changed.

## Remaining Work

After integration, the next task must define one serialized prospective runtime
source and writer boundary. Dormant contracts do not make continuous discovery
operational, and no official strategy cohort may start from them alone.
