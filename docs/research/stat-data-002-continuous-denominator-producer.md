# STAT-DATA-002 Continuous Denominator Producer

Status: `IMPLEMENTED_PENDING_PARENT_RESEARCH_STACK_AND_AUGUST_17_RECONCILIATION`

## Ancestry

- Canonical frozen baseline: `ea056155182351be70bb03d23841aca55c6118ae`
- Continuous stack base: `6794e8a0f141895cd264c82fe2b83381492c2ab2`
- Continuous parents: `b86c503` -> `949e3c8` -> `4101d37` -> `6794e8a`
- Authoritative STAT-DATA-001 contract source: `cd95490661b54c73af162c8b9f651039006ad0c6`
- STAT-DATA-001 specialist parent: `e65cb70`
- Temporary integration parent: `a5040e837f36ba82989872024938bc80c0959a47`

The temporary integration parent copies the STAT-DATA-001 contract modules and
their tests byte-for-byte onto the exact continuous stack head. It does not
import the research Roadmap or activate the sample.

## Boundary

`momentum_hunter.continuous_denominator` is a pure adapter. Its inputs are an
immutable `DiscoverySnapshot`, the corresponding `HotUniverseResult`, and the
corresponding `ContinuousCompositionCycle`. Its outputs are the authoritative
STAT-DATA-001 `OpportunityCycleRecord` and `OpportunityRecord` set plus a
fingerprinted linkage receipt.

The module has no provider transport, network, account, broker, order,
scheduler, service, Engine Host, WPF, scoring, Risk Governor, allocation,
Paper, or Shadow capability. It accepts only `SYNTHETIC_TEST` while the sample
is inactive.

Sample identity remains `opportunity-denominator-research-v1` with status
`INACTIVE_NOT_ACTIVATED`. No production session or opportunity is created.

## Producer Policy

- Policy version: `continuous-denominator-producer-policy-v1`
- Profile: `continuous-opportunity-denominator-wiring-v1`
- Fingerprint: `b6e5c76734c3219212e8e74e437e6a49fa84ad494e991994631df11f8f4f258a`
- Cycle/session type: `CONTINUOUS_INTRADAY`
- Source-unit rule: discovery rows plus retained-member observations
- Discovery-failure rule: preserve partial rows and retained evaluations
- Authority: research only; execution authority none

## Mapping

| Upstream evidence | STAT-DATA disposition | Linkage treatment |
| --- | --- | --- |
| Qualified row with evaluated member | `NO_ACTION_RESEARCH_ONLY` unless blocked/bound | `QUALIFIED` |
| Rejected discovery row | `REJECTED_STRATEGY` | `REJECTED_FILTER` |
| Partial/failed discovery row | `BLOCKED_DATA` | `BLOCKED_DATA` |
| Provider-capacity-bound member | `NOT_EVALUATED_PROVIDER_BOUND` | exact member result |
| Readiness block or unsafe data | `BLOCKED_DATA` | exact blocker reasons |
| No lifecycle change | `NO_ACTION_RESEARCH_ONLY` | `NO_LIFECYCLE_CHANGE` |
| Missed entry | `NO_ACTION_RESEARCH_ONLY` | `MISSED_ENTRY_RECORDED` |
| New successor/plan | `NO_ACTION_RESEARCH_ONLY` with new setup/plan identity | exact composition disposition |
| Missing Universe member or Compose result | `SYSTEM_FAILURE` | explicit incomplete reason |

Every represented discovery row receives one immutable source-row disposition
and one authoritative STAT-DATA opportunity record because STAT-DATA-001's
cycle completeness contract requires every represented unit to resolve to an
opportunity reference. A tracked member absent from the current scanner pulse
receives a separate `RETAINED_FROM_PRIOR_DISCOVERY` observation without a
fabricated current row.

The linkage preserves discovery snapshot/query/pagination-policy fingerprints,
coverage scope/state, page and row coordinates, cross-page atomicity, Universe
policy/state fingerprints, Compose policy/cycle fingerprints, evidence cutoff,
setup identity, predecessor setup identity, and plan identity.

## Failure Semantics

A complete discovery pulse must be the newest exact Universe snapshot receipt.
A failed discovery pulse must match the Universe failure transition by timestamp
and reason. Partial rows remain visible as data-blocked observations; they are
not admitted as ordinary strategy evidence. Valid retained members may still be
evaluated in the same incomplete cycle.

Missing Universe or Compose linkage is a `SYSTEM_FAILURE`. Partial discovery
alone is a `DATA_CONTRACT_FAILURE`. Either makes the STAT-DATA cycle incomplete.
Provider-bound members are denominator members and are neither rejects,
no-trades, nor data failures.

## Reconciliation

The producer enforces:

```text
discoveryRawRows = discoveryParsedRows = discoveryRepresentedRows
discoveryRepresentedRows = discoveryQualified + discoveryRejected
discoveryRepresentedRows = denominatorSourceRowDispositions
compositionPresented = number of composition member results
denominatorOpportunityRecords = number of STAT-DATA opportunity references
linked source-row/member opportunity identities = authoritative opportunity set
```

A cycle is complete only when every represented row, retained member, and
required composition result is linked and the upstream source did not fail.
Cross-page traversal completeness never upgrades Finviz's
`NOT_GUARANTEED` atomicity.

## Persistence And Restart

`ContinuousDenominatorStore` delegates authoritative cycle/opportunity writes
to `OpportunityDenominatorStore`, then writes one terminal linkage receipt.
Exact replay is byte-idempotent. Conflicting content, duplicate identity,
tampering, or missing authoritative cycle/opportunity evidence fails closed.
A cycle written without its linkage is nonterminal and can be completed by an
exact replay after restart.

## Fixture Results

- 20 rows / 2 qualified: 20 linked records, 18 rejects, one waiting, one
  no-change, complete.
- 100 rows / 5 pages / 7 qualified: all 100 page/row coordinates linked;
  cross-page atomicity remains not guaranteed.
- Page-4 midday BBB: page 4 / ordinal 65 retained through plan lineage with no
  opening or 08:35 parent.
- Scanner disappearance CCC: no current row; retained member and current
  composition result preserved.
- 30-for-10: 30 opportunities, 10 readiness slots, 20 explicit
  `NOT_EVALUATED_PROVIDER_BOUND` records.
- Discovery failure plus retained members: 20 partial rows plus two retained
  evaluations preserved in an incomplete data-contract-failure cycle.
- Gapped readiness: explicit `BLOCKED_DATA`, never strategy reject/no-trade.
- Missed then successor: predecessor remains immutable; successor has distinct
  setup, plan, opportunity, and cycle identities.
- Partial pagination: incomplete with exact coverage/failure evidence.
- Partial Compose: incomplete `SYSTEM_FAILURE` with the missing member explicit.
- Zero qualified: valid complete cycle, zero Universe admissions, all source
  rejects retained.

## Verification

- Focused STAT-DATA-002: 30 passed.
- Parent/adjacent bounded stack: 257 passed.
- Full Python discovery: 2,202 passed across all 176 modules in four terminal
  batches (722, 477, 559, 444).
- Python `compileall`: passed.

No specialist attachments, market outcomes, MFE/MAE, hypothetical fills,
profitability metrics, activation record, runtime consumer, or production
persistence path is added by this task.
