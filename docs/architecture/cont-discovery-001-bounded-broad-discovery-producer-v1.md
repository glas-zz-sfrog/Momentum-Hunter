# CONT-DISCOVERY-001 - Bounded Broad Discovery Producer v1

Classification: `IMPLEMENTED_PENDING_AUGUST_17_RECONCILIATION`

## Purpose

`CONT-DISCOVERY-001` turns one verified Finviz screener response into one
immutable `DiscoverySnapshot`. It answers what exact bounded provider response
was observed, what happened to every represented row, and which rows qualified
under the current Momentum filter policy.

It is not a scheduler, a continuous runtime, a hot-universe manager, a setup
generator, a Paper component, or an execution component.

## Contract

`momentum_hunter.broad_discovery` exposes these versioned immutable contracts:

- `DiscoverySnapshot` v1: source, source/query/policy identities, central-time
  observation clocks, coverage and pagination limits, every row, all counts,
  status, and a tamper-detecting fingerprint.
- `DiscoveryRow` v1: source ordinal and identity, normalized source values,
  parsed canonical values, row fingerprint, exact disposition, rejection
  reasons, and a candidate identity when qualified.
- `DiscoveryQueryIdentity` v1: source query, current criteria, sort order,
  one-response page bound, and the qualification-policy identity.

The canonical JSON serialization is deterministic. `snapshotId`, row IDs,
candidate identities, and fingerprints derive from canonical content. Parsing a
tampered serialized snapshot fails validation.

## Coverage Truth

This producer labels current Finviz output as:

- `coverageScope = BOUNDED_PROVIDER_RESPONSE`
- `paginationState = SINGLE_RESPONSE_UNPAGINATED`
- `pagesRequested = 1`
- `pagesReceived = 1`
- `unseenRowCount = UNKNOWN`

The snapshot is complete only within the single provider response actually
observed. It never claims market-wide coverage and never invents unseen rows.

## Reconciliation

For every valid snapshot:

```text
rawRowCount = parsedRowCount = representedRowCount
representedRowCount = qualifiedCount + rejectedCount
```

Each parsed row has exactly one disposition:

- `QUALIFIED`
- `REJECTED_FILTER`, with every applicable stable threshold reason

Valid zero-candidate and header-only responses use
`COMPLETE_WITHIN_REQUESTED_BOUND`. Structural schema/value failures and DATA-008
semantic plausibility failures raise the existing provider errors before a
snapshot is produced; they cannot be represented as a valid zero-candidate
observation.

## Finviz Compatibility Boundary

`FinvizProvider.discover()` owns one pulse: acquisition, existing schema and
required-value validation, existing semantic plausibility evaluation, then
snapshot construction. `FinvizProvider.scan()` returns the legacy qualifying
candidate list reconstructed from that same snapshot path.

The shared `candidate_rejection_reasons` and `filter_discovery_candidates`
functions provide the one authoritative current filter semantic used by both
the provider semantic diagnostic layer and the snapshot producer. This does not
alter scoring, ranking, Finviz request filters, or opening-capture behavior.

## Boundaries Kept Intentionally Empty

There is no repeated cadence, persistent state, candidate retention, hot
universe, setup/TradePlan/risk/allocation code, broker access, Paper activity,
service activation, manifest mutation, or UI integration. A future
`CONT-UNIVERSE-001` may consume consecutive snapshots, while a future
`STAT-DATA-002` can consume the complete bounded denominator without rescanning
or guessing.
