# ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001A Contract Trace

## Scope and version disposition

This task corrects the not-yet-canonical V2 candidate in place. It does not
create V3. V1 parsing, embedded legacy eligibility records, sealed bytes, and
compatibility behavior remain unchanged.

## Exact repaired construction order

1. `StrategyScienceRecorder.accept()` parses the immutable V2 producer
   envelope and freezes the source-level Science capture clock.
2. `_normalize_export()` constructs discovery-cycle and candidate-observation
   records. The observation retains the receipt-effective
   `recorder_capture_time` and producer `effective_known_at`.
3. `_persist_record()` durably creates the observation payload and its exact
   custody receipt.
4. Only after that receipt verifies, `_science_eligibility_record()` derives
   the Science-owned eligibility record.
5. `_science_eligibility_evaluated_at()` uses the current Science clock for the
   first derivation. If an exact eligibility payload is already staged, it
   reuses that payload's evaluation/capture clock for idempotency.
6. The eligibility payload and receipt commit before the producer source
   checkpoint advances.

## Field authority

| Field | Authority | Meaning | Semantic eligibility hash |
|---|---|---|---|
| `producer_content_sha256` | Producer bytes observed by Science | Exact immutable producer envelope | Included |
| `producer_effective_known_at` | Producer | Latest producer-known fact cutoff | Included |
| `producer_observation_payload_sha256` | Science custody | Exact normalized observation bytes | Included |
| `science_custody_receipt_sha256` | Science custody | Exact observation receipt-chain identity | Included |
| `science_receipt_effective_at` | Science custody | Frozen receipt-effective semantic clock | Included |
| `science_evaluated_at` | Science custody | Actual first eligibility construction/evaluation clock | Excluded |
| eligibility `recorder_capture_time` | Science custody | Physical eligibility record creation clock; must equal `science_evaluated_at` | Outer record only |
| `commitment_payload_sha256` | Science | Semantic eligibility identity | Self-hash excluded |

`science_eligibility_sha256()` hashes canonical JSON after removing
`commitment_payload_sha256` and `science_evaluated_at`. Excluding the physical
clock is intentional: identical frozen T1 inputs must retain identical semantic
eligibility even if recovery first materializes the record at T2.

The full payload bytes still contain both clocks. The record receipt hashes the
full payload, so physical chronology has its own immutable custody identity.

## Record-specific crash boundaries

The repaired V2 test surface names exact boundaries instead of relying on the
first generic record hit:

- `after_source`
- `after_discovery_cycle_payload`
- `after_discovery_cycle_receipt`
- `after_candidate_observation_payload`
- `after_candidate_observation_receipt`
- `after_science_eligibility_payload`
- `after_science_eligibility_receipt`

The critical `after_candidate_observation_receipt` boundary proves the exact
T1 receipt → T2 eligibility gap. The `after_science_eligibility_payload` path
proves reuse of the staged T1 evaluation time. The
`after_science_eligibility_receipt` path proves recovery includes the already
accepted eligibility in the still-missing producer source checkpoint rather
than duplicating or orphaning it.

## Fail-closed invariants

- A receipt-effective clock before producer known-at fails.
- An eligibility evaluation clock before receipt-effective time fails.
- Evaluation time differing from outer record creation time fails.
- Wrong producer, observation payload, or custody receipt hashes fail.
- A staged eligibility with inconsistent logical identity or clock fails.
- Later market/outcome fields remain prohibited during initial eligibility.
- One instrument cannot acquire duplicate or conflicting eligibility.
- Producer bytes and hashes never change during Science recovery.

## Product and runtime boundary

No Continuous exporter, Science source reader, GUI, Opening Engine, provider,
authentication, service, scheduler, discovery, scoring, readiness, TradePlan,
risk, Paper, Shadow, broker, account, position, order, or execution-authority
path is changed or contacted.
