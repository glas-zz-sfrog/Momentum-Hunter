# ARGUS-RESEARCH-GOV-001 Architecture

## Boundary

`momentum_hunter.research_governance` is a standalone, standard-library-only
research contract layer. It records what an experiment intended, what was
attempted, what evidence was inspected, and what conclusion was preserved. It
does not execute an experiment, evaluate a model, select a best variant,
contact a provider, inspect an account, place an order, or alter a trading
decision.

Every v1 experiment, result, and model-health record is fixed at:

- authority `RESEARCH_ONLY`;
- execution authority `EXECUTION_AUTHORITY_NONE`.

There is no production import, scheduler job, service hook, UI path, or default
production persistence root.

## Immutable Records

- `FeatureDefinition` binds exact inputs, transformation, horizon, price-basis
  requirement, evidence family, version, and fingerprint.
- `SampleIdentity` and `DatasetIdentity` bind exact source/policy identities and
  preserve data-basis, survivorship, security-identity, and point-in-time
  limitations. A historically robust claim requires every necessary state to
  be verified or controlled.
- `DataPartition` distinguishes `TRAIN`, `VALIDATION`, `TEST`, and `HOLDOUT` by
  exact boundaries and source fingerprints. Independent partitions cannot
  overlap.
- `ResearchExperiment` freezes question, hypothesis, research timing and
  intent, Git/policy/data/feature/metric/benchmark identities, criteria,
  partitions, holdout policy, search space, and minimum sample.
- `ExperimentAmendment` is additive and explicitly distinguishes pre-outcome
  from post-outcome knowledge. It cannot rewrite the experiment.
- `ExperimentVariant` preserves every evaluated, null, failed, invalid, or
  abandoned attempt. An unplanned search expansion must be visibly invalid.
- `HoldoutAccessReceipt` is a chronological fingerprint chain. Authorized
  final access permanently opens a holdout; early or unauthorized access
  permanently contaminates it.
- `ExperimentResult` attaches to an exact experiment and variant and preserves
  actual sample, variant, metric, and feature-set counts plus whether selection
  occurred. Undeclared metrics can only be exploratory secondary metrics.
- `ExperimentInvalidation` preserves failure without deleting history.
- `ModelHealthPolicy` freezes evidence window, minimum sample, benchmark,
  metrics, and failure semantics. `ModelHealthRecord` is evidence only; unit
  tests or synthetic examples cannot declare a model `HEALTHY`.

## Persistence

`ResearchRegistryStore` requires an explicit absolute caller root and adds the
versioned `experiment-registry-v1` directory. It has no production default.

Collections are separate for experiments, amendments, variants, results,
holdout receipts, invalidations, model-health policies, and model-health
records. Records use strict canonical JSON and embedded fingerprints.

- Exact duplicate bytes are idempotent.
- A conflicting logical identity fails closed.
- A temporary file is flushed and atomically hard-linked into its terminal
  write-once name, so an existing record is never overwritten.
- Malformed JSON, duplicate keys, noncanonical bytes, fingerprint tampering,
  unexpected paths, and leftover partial writes fail closed.
- A restarted reader validates every record and the complete cross-record
  graph before returning a snapshot.
- Missing evaluated results, deleted variants, understated attempt counts, and
  deleted holdout receipts invalidate the snapshot and therefore the summary.

## Summary

The pure summary reports experiment timing/intent counts, every variant status,
every result conclusion including negative and invalid conclusions, holdout
states, model-health states, and planned-versus-actual search counts. It has no
profitability ranking, promotion, model selection, or trading action.

## Static Compatibility

The module contains static, unactivated registration metadata and in-memory
experiment fixtures for:

- REGIME-002 at `99a25f84219377e9988e8284aa15a944e3936784`;
- EXEC-QUALITY-001 at `1b105e71d99d45a8ed8099ae4001bd9c6ba2242f`;
- EVENT-SHOCK-001 at `fe8ca09556fe8ea3dd81949e59ac26d8e3d86da4`.

STAT-DATA-001 compatibility is static and records inactive sample
`opportunity-denominator-research-v1` at zero sessions and zero opportunities.
No STAT-DATA runtime module is imported. RESEARCH-DATA-002 compatibility
preserves unresolved price basis/security identity, uncontrolled survivorship,
insufficient point-in-time universe capability, and no historically robust
claim.

## Remaining Gate

The feature is implemented and backed up only on its task branch. A later
deliberate integration may add these contracts to canonical source, but
production persistence, experiment registration, experiment execution,
model-health evaluation, scheduling, specialist authority, and any use in
trading remain separate future tasks.
