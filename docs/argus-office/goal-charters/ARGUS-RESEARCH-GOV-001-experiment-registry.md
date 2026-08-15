# ARGUS-RESEARCH-GOV-001 Goal Charter

## Goal

Build a deterministic, immutable, research-only experiment registry that
records hypotheses, feature and data identities, partition boundaries,
benchmarks, success and failure criteria, attempted variants, amendments,
holdout access, results, invalidations, and model-health evidence without
evaluating a model or influencing Momentum Hunter trading behavior.

## Operator Value

Momentum Hunter must make hindsight-driven tuning visible. A failed experiment,
an ugly variant, an early-opened holdout, a changed benchmark, and a result
found after many attempts must remain easier to find than to hide. The registry
must prove what was intended before an outcome was inspected.

## Reconciled Preflight

- Canonical checkout, local `master`, and `origin/master` are clean and
  synchronized at `ea056155182351be70bb03d23841aca55c6118ae`.
- Installed automation manifest SHA-256 is
  `8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`.
- `opening-capture-20260817`, `paper-engineering-20260817`,
  `successor-setup-pass1-20260817`, and
  `successor-setup-pass2-20260817` are all exact-head pinned to `ea056155`
  with the intended opening -> Paper and opening -> Pass 1 -> Pass 2
  dependencies.
- Current backed-up research heads are: SPECIALIST-CONTRACT `e65cb70`,
  REGIME-002 `99a25f8`, EXEC-QUALITY-001 `1b105e7`, EVENT-SHOCK-001
  `fe8ca09`, STAT-DATA-001 `cd95490`, RESEARCH-DATA-001 `d03301c`, and
  RESEARCH-DATA-002 `12e6a05`.
- This branch is based directly on canonical `ea056155`; no sibling research
  implementation is an ancestor or runtime dependency.

## Scope

- Add one standalone `momentum_hunter.research_governance` module with versioned
  immutable records for experiment preregistration, feature definitions, data
  partitions, amendments, variants, results, holdout access, invalidation,
  model-health policy/evidence, and read-only summaries.
- Preserve every directive-required field. Feature definitions include exact
  inputs, transformation, time horizon, price-basis requirement, and evidence
  family. Experiments include question, hypothesis, research domain, code and
  policy identity, data/sample identity, benchmark, success/failure criteria,
  TRAIN/VALIDATION/TEST/HOLDOUT partitions, holdout and parameter-search
  policies, authority, status, and fingerprint. Amendments, variants, results,
  invalidations, and model-health records preserve their complete identities,
  chronology, evidence, status, and fingerprints.
- Require exact Git, policy, sample, dataset, source, feature, benchmark,
  metric, time-boundary, search-space, and authority identities.
- Distinguish prospective, retrospective exploratory, and retrospective
  confirmatory research plus exploratory versus confirmatory intent.
- Preserve planned and actual variant, metric, and feature-set counts; never
  choose or promote a best model.
- Add deterministic atomic write-once persistence rooted only at a caller-
  supplied path. Exact duplicates are idempotent; conflicts, tampering,
  malformed records, partial files, identity drift, and impossible chronology
  fail closed.
- Add static registration fixtures for the exact current REGIME-002,
  EXEC-QUALITY-001, and EVENT-SHOCK-001 identities without importing sibling
  specialist modules. Add static STAT-DATA compatibility metadata and current
  RESEARCH-DATA limitation states.
- Support the complete parameter-search vocabulary:
  `SINGLE_PREREGISTERED_VARIANT`, `SMALL_BOUNDED_COMPARISON`, `GRID_SEARCH`,
  `RANDOM_SEARCH`, `MODEL_SELECTION`, `EXPLORATORY`, and
  `OTHER_VERSIONED_METHOD`.
- Preserve `dataBasisStatus`, `survivorshipStatus`,
  `securityIdentityStatus`, and `pointInTimeUniverseStatus`; unresolved states
  prohibit any historically robust claim.
- Update branch-local architecture, release, Roadmap, branch, task, changelog,
  and risk evidence only after implementation proof.

## Non-Goals

- No experiment execution, statistical model, parameter optimizer, strategy
  selector, specialist combination, arbiter, profitability ranking, threshold
  tuning, automatic model-health evaluation, or health-based enforcement.
- No scanning, candidate admission, score, rank, TradePlan, Risk Governor,
  allocation, Paper, Shadow, SETUP-002, specialist policy, broker/order,
  provider/network, production evidence, UI, service, scheduler, Engine Host,
  installed runtime, credential, database, or generated-data change.
- No production persistence, registry activation, experiment scheduling,
  historical backfill, real/production outcome evaluation, merge, install, or
  Aug. 17 repin. Synthetic result construction and contract validation are
  required in temporary test roots and grant no research conclusion about the
  actual strategy.

## Acceptance Evidence

- Contract version 1 records are immutable, canonically serialized, and
  fingerprint validated with exact cross-record identity checks.
- Preregistered fields cannot change. Amendments remain separate and identify
  pre-outcome versus post-outcome knowledge; no amendment rewrites history.
- Every registered variant remains in the ledger, including invalid, failed,
  null, and abandoned variants. Search-space expansion is explicit.
- TRAIN, VALIDATION, TEST, and HOLDOUT partitions are distinct and validated;
  independent partitions cannot overlap when independence is required.
- Holdout receipts permanently record access count and chronology. Early access
  contaminates the holdout; a later record cannot reseal it. Exact states are
  `SEALED`, `OPENED_FOR_FINAL_EVALUATION`,
  `CONTAMINATED_BY_EARLY_ACCESS`, and `NOT_APPLICABLE`; every receipt preserves
  authorization state and prior access count. Legitimate authorized final
  access permanently opens rather than contaminates the holdout.
- Results reference the exact experiment and variant, use preregistered primary
  metric identities, keep undeclared metrics exploratory, enforce minimum
  sample conclusions, and never mutate the experiment.
- Experiment invalidation is a separate immutable record with reason, time,
  and evidence fingerprint; it never deletes or rewrites the experiment.
- Model-health records support `NOT_EVALUATED`, `HEALTHY`, `DEGRADING`,
  `UNRELIABLE`, and `INSUFFICIENT_RECENT_EVIDENCE`, but always retain
  `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`. A separately fingerprinted
  health policy freezes evidence window, minimum sample, benchmark, metrics,
  and failure thresholds; changing any policy field changes its fingerprint.
  Unit tests cannot label a current specialist `HEALTHY`; static examples are
  `NOT_EVALUATED` or `INSUFFICIENT_RECENT_EVIDENCE` only.
- Temporary-root persistence proves atomic write-once behavior, duplicate
  idempotency, restart loading, conflict rejection, partial-file rejection,
  tamper detection, and complete negative-result summaries.
- The complete directive Section 37 negative matrix is covered, including
  preregistration/order violations, search-space drift, deleted variants or
  holdout receipts, chronology/partition errors, post-outcome amendment
  mislabeling, metric/benchmark/criterion drift, feature/data/policy/code
  identity drift, wrong cross-record attachment, duplicate/conflicting/
  malformed/partial writes, omitted negative results, false research-mode or
  sample-size claims, unsupported health claims, execution authority, and
  provider/network/order capability introduction.
- Pure summaries report experiment design counts, variant valid/invalid counts,
  every conclusion including negative/null/abandoned states, holdout states,
  and model-health states. They expose multiple-comparison counts but contain
  no profitability ranking, best-model selector, or automatic promotion.
- Static specialist fixtures match the current branch heads, versions, and
  policy fingerprints. STAT-DATA remains an inactive referenced sample, not an
  imported evidence store.
- Focused, persistence, negative-matrix, specialist-fixture, STAT-DATA
  compatibility, SETUP-002 nonmutation, compileall, full Python discovery,
  diff, secret, capability, runtime-import, and protected-path checks pass.
- Canonical `master`, installed manifest hash, and all four Aug. 17 job pins
  remain unchanged.

## Classification

`IMPLEMENTED_PENDING_MERGE`

The authorized closeout is one focused feature commit and an ordinary
non-force feature-branch push. Merge, installation, activation, scheduling,
experiment evaluation, and Aug. 17 repinning are explicitly prohibited.
