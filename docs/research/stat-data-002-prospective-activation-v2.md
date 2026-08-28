# STAT-DATA-002 Prospective Activation Inventory

## KEEP

| Existing authority | Treatment |
| --- | --- |
| `opportunity_denominator.py` cycle, opportunity, attachment, market-path, broker-execution, and data-quality records | Keep as the provider-neutral immutable base contract. |
| `OpportunityDenominatorStore` | Keep as the authoritative write-once cycle/opportunity/outcome store. |
| `continuous_denominator.py` | Keep as the sole adapter from Discovery + Hot Universe + Composition into the base contract. |
| Continuous discovery, readiness, composition, lifecycle, setup, TradePlan, and restart classes | Keep as the only natural decision-authoritative producers. |
| Existing outcome builders | Keep; STAT-DATA-002 adds no exit or fill semantics. |
| Research Maturity and workstation read models | Keep unchanged; no UI activation is part of this task. |

## REPAIR

| Gap | Repair |
| --- | --- |
| Sample status is inactive and activation metadata is not durably bound to each prospective member. | Add a write-once activation record and bind every membership/attempt/population record to its fingerprint. |
| Continuous adapter accepts only synthetic and isolated qualification modes. | Admit `PROSPECTIVE` only with an explicit active denominator policy and activation fingerprint. |
| Natural denominator results are held in qualification memory and summarized in writer evidence, not persisted as the statistical sample. | Add an explicit-root prospective store wrapping the existing authoritative stores. |
| Cycle opportunity identity intentionally includes cycle identity, so repeated cycle observations cannot alone define unique opportunity membership. | Add an immutable canonical membership index keyed by setup, member, or discovery-row authority while preserving every cycle attempt. |
| Existing summaries do not expose all required nested populations or pending outcomes. | Derive auditable counters from immutable membership, attempt, population, and outcome-link records. |

## REPLACE

Nothing. No existing statistical, outcome, maturity, or Continuous producer
authority is replaced.

## DEFER

- Exit-policy statistics not already represented by accepted market-path states.
- Broker fill/performance statistics without actual provider execution evidence.
- UI presentation of the new counters.
- Instrument execution eligibility.
- Continuous Paper, Shadow, or order authority.
- Historical backfill into the prospective sample.

## Nested Populations

The activation layer reports separate unique-member populations for discovery,
hot-universe admission, READY, accepted composition, TradePlan, no-plan,
strategy reject, data/system block, missed entry, successor setup, and
provider-bound/not-evaluated evidence. These are not interchangeable headline
denominators.

## Historical Boundary

Historical provider bars and backfill remain evidence references only. A member
is prospective only when its natural discovery/member/setup trigger was first
observed on or after the immutable activation timestamp and first eligible
session. Restart and replay preserve that floor.
