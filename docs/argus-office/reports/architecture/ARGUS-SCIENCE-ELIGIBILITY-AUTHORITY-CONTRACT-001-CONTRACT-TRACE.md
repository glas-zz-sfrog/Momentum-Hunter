# ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001 Contract Trace

## Disposition

`CIRCULAR_AUTHORITY_DEPENDENCY_PROVEN = YES`

The frozen blocker proof is preserved at SHA-256
`A68C6FED0EB56D3C371B4196A42CDD78EDD474B5053EC32788AD77C48837F0B0`.
The blocked producer branch and its two reports remain unchanged at
`a06d4aecd67578cefe783b035ec1ea425090eef2`.

## Legacy V1 construction order

The circular dependency was exact, not hypothetical:

1. `ResearchExportEnvelopeV1` schema `1.0.0`, offline profile
   `ARGUS_SCIENCE_OFFLINE_RESEARCH_EXPORT_V1`, accepts exact canonical UTF-8
   JSON bytes with one LF terminator.
2. The producer seals `DECISION_FACT` at T0. V1 requires
   `decision_event.outcome_eligibility_commitment_sha256`
   (`contract.py:916-992`). The raw producer content identity is
   `SHA256(exact raw envelope bytes)`.
3. Science receives discovery evidence later at T1. V1 custody constructs
   `outcome_eligibility` in `_eligibility_commitment()` and includes
   `committed_at = recorder_capture_time` (`custody.py:1082-1114`).
4. Science then canonicalizes the normalized observation payload and creates a
   custody receipt whose `committed_at` is the Science capture time and whose
   `payload_sha256` binds the exact custody payload (`custody.py:1938-2017`).
5. When the producer Decision arrives, `_validate_decision()` requires its T0
   field to equal the Science-created eligibility hash
   (`custody.py:1390-1511`).

Therefore, with `T1 > T0`, the producer had to predict a hash containing T1.
The frozen mechanical probe used identical START/discovery source bytes at
Science clocks `14:00:00Z` and `14:00:01Z`; it produced different eligibility
hashes. The same producer Decision was accepted by one custody instance and
rejected by the other.

## Hash and canonicalization rules

All three domains use SHA-256, but they deliberately hash different exact
bytes:

| Identity | Authority | Exact byte domain |
|---|---|---|
| Producer content hash | Producer | Exact canonical source-envelope bytes, including LF |
| Science custody receipt hash | Science custody | Exact canonical receipt object bytes, including LF |
| Science eligibility hash | Science custody | Exact canonical `science_eligibility` material, including LF, excluding only `commitment_payload_sha256` |

Canonical JSON is UTF-8, keys sorted, compact separators, no duplicate keys,
no semantic nulls, no floats/non-finite numbers, and exactly one trailing LF.
Equivalent reparsing/reserialization outside that rule is not an identity.

## Repaired construction order

The V2 construction order is:

1. Producer seals a V2 envelope/Decision at T0 without any Science receipt or
   eligibility field.
2. Science receives the immutable source bytes at T1 and rejects
   `T1 < producer effective_known_at` or `T1 < producer emitted_at`.
3. Science preserves the exact producer bytes and commits the normalized
   candidate-observation payload and receipt.
4. Only after the observation receipt exists, Science creates one
   `science-eligibility` record per first instrument observation.
5. The eligibility material binds the producer envelope hash, producer
   effective-known-at, exact observation custody payload hash, exact observation
   custody receipt hash, first observation identity, instrument fingerprint,
   frozen policy, and Science evaluation time.
6. A later Science custody Decision record may reference the Science eligibility
   ID/hash. Those derived fields are not present in the producer source bytes.
7. Outcome attachment remains later and binds the exact immutable Science
   decision bytes plus the Science eligibility hash; it cannot rewrite any
   discovery, receipt, eligibility, or decision record.

## Exact implementation surface

- V2 schema: `2.0.0`
- V2 source contract: `ResearchExportEnvelopeV2`
- V2 source contract version: `2.0.0-proposal`
- V2 profile: `ARGUS_SCIENCE_OFFLINE_RESEARCH_EXPORT_V2`
- Science eligibility profile: `ARGUS_SCIENCE_RECEIPT_ELIGIBILITY_V2`
- Science eligibility record version: `2.0.0`

V1 remains accepted with its original parser, fields, hashes, embedded legacy
eligibility, restart behavior, and exact sealed bytes. No persisted V1 record is
rewritten. Because V1 lacks a separate observation-receipt-bound eligibility
record, its repaired-linkage classification is:

`LEGACY_ELIGIBILITY_LINKAGE = UNKNOWN`

## Fail-closed rules

- V2 producer Decision containing a legacy eligibility hash or any Science
  receipt/eligibility field is rejected as an unknown field.
- Science receipt before producer known-at/seal time is rejected before
  candidate adoption.
- Wrong producer content hash, observation payload hash, or observation custody
  receipt hash invalidates Science eligibility.
- Later outcome/future-market material is rejected from initial observation and
  eligibility schemas.
- Wrong Science eligibility ID/hash invalidates the Science custody Decision or
  later Outcome attachment.

`CONTRACT_VERSION_ACTION = NEW_VERSION_REQUIRED`
