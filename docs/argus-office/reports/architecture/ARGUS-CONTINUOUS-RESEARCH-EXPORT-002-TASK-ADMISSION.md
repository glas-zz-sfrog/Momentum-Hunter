# ARGUS-CONTINUOUS-RESEARCH-EXPORT-002 Task Admission

## Identity

- `LANE = SERIALIZED_CROSS_LANE`
- `ROLE = CONTINUOUS_OWNER`
- `TASK_ID = ARGUS-CONTINUOUS-RESEARCH-EXPORT-002`
- `BASE_CANONICAL_SHA = 367af2a33a34c76558eb60b65008df88414815f1`
- `BRANCH = codex/ARGUS-CONTINUOUS-RESEARCH-EXPORT-002`
- `WORKTREE = C:\Users\steve\AppData\Local\MomentumHunter\worktrees\INTEGRATION-ARGUS-CONTINUOUS-RESEARCH-EXPORT-002`
- `EVIDENCE_ROOT = C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\INTEGRATION\ARGUS-CONTINUOUS-RESEARCH-EXPORT-002-367af2a`
- `TEMP_RUNTIME_ROOT = C:\Users\steve\AppData\Local\Temp\MomentumHunter-INTEGRATION-ARGUS-CONTINUOUS-RESEARCH-EXPORT-002-367af2a`
- `PACKAGE_ROOT = C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\INTEGRATION\packages`

The explicit task directive supersedes the Roadmap's stale `001` task label for
this isolated implementation only. Canonical governance is not mutated by the
builder and remains Integration-Steward-owned. The blocked predecessor branch
`codex/ARGUS-CONTINUOUS-RESEARCH-EXPORT-001` at
`a06d4aecd67578cefe783b035ec1ea425090eef2` is read-only historical evidence
and is not reused, rebased, amended, or merged.

## Owned Paths

- `momentum_hunter/continuous_research_export.py`
- `tests/test_continuous_research_export_v2.py`
- `tools/run_continuous_research_export_002_proof.py`
- `tools/run_continuous_research_export_002_tests.py`
- `tools/package_continuous_research_export_002_review.py`
- `docs/argus-office/reports/architecture/ARGUS-CONTINUOUS-RESEARCH-EXPORT-002-*.md`

## Protected Paths

- `docs/argus-office/ROADMAP.md`
- `docs/argus-office/BRANCH_LEDGER.md`
- `docs/argus-office/TASK_LOG.md`
- `momentum_hunter/strategy_science_recorder/**` semantics and executable bytes
- existing Continuous runtime, producer, service, deployment, provider, and
  authentication paths
- Opening runtime and Observer paths
- `src/**` and all GUI paths
- strategy thresholds, scoring, readiness, TradePlan economics, Paper, Shadow,
  broker, account, position, order, and execution paths
- production services, schedulers, manifests, installed runtimes, generated
  opening evidence, and the 2026-09-02 evidence corpus

## Capabilities And Gates

- `ALLOWED_CAPABILITIES = offline deterministic export construction; isolated
  write-once publication; direct canonical V2 parser/custody compatibility;
  synthetic crash/restart/two-clock proof; approved-environment tests; sanitized
  package creation and fresh extraction verification`
- `PROHIBITED_CAPABILITIES = provider/authentication contact; live-market
  canary; production attachment; service/scheduler mutation; Science reader;
  always-on capture; Paper/Shadow/broker/account/position/order/execution;
  shared contract mutation; historical Class-B upgrade`
- `PACKAGE_GATE = SECOND_EYE_ZIP_REQUIRED`
- `SECOND_EYE_GATE = REQUIRED_BEFORE_INTEGRATION`
- `MERGE_GATE = SERIALIZED_INTEGRATION_STEWARD_ONLY`
- `SHARED_RUNTIME_MUTATION_AUTHORIZED = NO`
- `SERVICE_MUTATION_AUTHORIZED = NO`
- `SCHEDULER_MUTATION_AUTHORIZED = NO`
- `CROSS_LANE_DEPENDENCY = accepted ResearchExportEnvelopeV2 parser and Science
  custody at canonical 367af2a; read-only consumption only`
- `SAFE_TO_IMPLEMENT_IN_PARALLEL = NO / serialized cross-lane contract task`

## Admission Proof

- Production checkout branch: `master`
- Production/canonical HEAD, local master, tracking master, remote master:
  `367af2a33a34c76558eb60b65008df88414815f1`
- `MASTER_CLEAN = YES`
- `MASTER_LOCAL_ORIGIN_SYNC = YES`
- `LANE_WORKTREE_CLEAN = YES` at branch creation
- `OWNED_PATHS_DECLARED = YES`
- `PROTECTED_PATHS_DECLARED = YES`
- Development on production checkout: `NO`
- Builder merge authority: `NO`
