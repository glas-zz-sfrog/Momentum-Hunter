# ARGUS-CONTINUOUS-RESEARCH-EXPORT-001 Field-Authority Map

## Disposition

`SCIENCE_CONTRACT_CHANGE_REQUIRED = YES`

The canonical `ResearchExportEnvelopeV1` discovery, START, FINAL, hash-chain,
sequence, gap, and immutable-publication surfaces can be produced without a
consumer change. The required `DECISION_FACT` / outcome path cannot.

The accepted architecture assigns prospective outcome eligibility to the
producing side. Canonical Science instead prohibits source eligibility on a
candidate observation, generates the commitment inside custody using a
Science-private capture clock, then requires the producer's later decision to
contain that generated hash. A sealed one-way producer publication cannot know
that future consumer-owned value. A discovery-only draft was therefore rejected
as completion evidence and no implementation candidate was frozen or packaged.

No canonical Science file was changed. The exact incompatibility must receive a
new serialized review gate before producer implementation resumes.

## Mandatory blocking field

| Science required field | Current authority | Exact conflict | Classification |
|---|---|---|---|
| observation `outcome_eligibility` | Accepted design: producing owner | `contract.py` closes the observation schema without this field; `custody.py` explicitly rejects source injection | `CONTRACT_CHANGE_REQUIRED` |
| custody `outcome_eligibility.commitment_payload_sha256` | Canonical Science custody | Generated from `committed_at = recorder_capture_time` plus observation/instrument/policy material | `CONTRACT_CHANGE_REQUIRED` |
| decision `outcome_eligibility_commitment_sha256` | Required in producer `DECISION_FACT` | Must equal the Science-generated commitment hash, which is unknowable when the producer seals its one-way publication | `CONTRACT_CHANGE_REQUIRED` |
| outcome `eligibility_commitment_sha256` | Required in producer `OutcomeAttachmentV1` | Must equal the same consumer-generated hash and bind the decision | `CONTRACT_CHANGE_REQUIRED` |

Mechanical proof used identical START and discovery source bytes with two valid
Science capture clocks one second apart. The generated commitment hashes were
different. A decision bound to clock A was accepted by custody A and rejected by
custody B with `Decision eligibility hash does not bind its observation.` The
proof is stored outside Git at
`ArgusReviewBundles/INTEGRATION/ARGUS-CONTINUOUS-RESEARCH-EXPORT-001-04f6f83/contract-blocker-proof.json`
(SHA-256 `a68c6fed0eb56d3c371b4196a42cdd78edd474b5053ec32788ad77c48837f0b0`).

## Authoritative source inventory

| Source | Existing authority | Relevant exact fields | Admission |
|---|---|---|---|
| `broad_discovery.DiscoverySnapshot` v1/v2 frozen JSON | Continuous discovery owner | `snapshotId`, `fingerprint`, `requestedAt`, `receivedAt`, `queryFingerprint`, `rows[]`, row identity/fingerprint/order, exact source values, bounded-prefix/gap facts | `AVAILABLE`; validated through canonical `DiscoverySnapshot.from_dict()` and bound as exact raw bytes |
| STAT-DATA-002 activation/configuration/terminal evidence | Research-only Continuous/STAT-DATA owner | activation/configuration identity, session date, source Git/config fingerprint, explicit no-execution posture, terminal completion fact | `AVAILABLE` as source for a separately frozen `ContinuousResearchSessionAuthorityV1`; files containing unrelated operational fields are not published |
| Candidate lifecycle ledger | Continuous lifecycle owner | opportunity/setup identities and event chronology | `AVAILABLE_WHEN_EXPLICITLY_SELECTED`; not required for discovery-only qualification and never inferred from symbol |
| Continuous TradePlan producer store | Continuous producer owner | setup, plan, cutoff, known-at, plan payload/fingerprint | `AVAILABLE_WHEN_EXACT_PARENT_CHAIN_PRESENT`; not present in the selected frozen qualification subset |
| Continuous provider/source evidence | Continuous provider adapter | provider event/receipt timestamps and evidence fingerprints | `AVAILABLE_WHEN_SELECTED`; discovery snapshot already carries its exact requested/received clocks |
| Canonical candle evidence | Canonical market-evidence owner | source event/receipt versions and canonical bar content | `AVAILABLE_WHEN_EXACT_SERIES_AND_PARENT_LINKS_PRESENT`; not used to create an outcome in this qualification |
| Outcome evidence | Outcome-producing owner | exact decision, observation, series, horizon, bar IDs and hashes | `MISSING_IN_SELECTED_SUBSET`; exporter must refuse a proven `OutcomeAttachmentV1` rather than join by symbol/time |

The selected replay source is the preserved, sanitized
`ARGUS-STAT-DATA-002D-PROSPECTIVE-CANARY-20260831-039D4E0` evidence. It is read
only after the original task is closed and is copied into a new frozen subset.
No provider is contacted.

## Envelope field mapping

| Science required field | Continuous authority | Exact source record / field | Known-at / identity authority | Status |
|---|---|---|---|---|
| `schema_version` | Shared export contract | fixed `1.0.0` | Integration-owned contract version | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `offline_reference_profile` | Shared export contract | fixed `ARGUS_SCIENCE_OFFLINE_RESEARCH_EXPORT_V1` | Canonical Science profile | `AVAILABLE` |
| `canonicalization_version` | Shared export contract | fixed `ARGUS_CANONICAL_JSON_V1` | Canonical Science helper | `AVAILABLE` |
| `hash_algorithm` | Shared export contract | fixed `SHA-256` | Canonical Science contract | `AVAILABLE` |
| `hash_unit` | Shared export contract | exact canonical UTF-8 JSON bytes including LF | Producer serializer validated by Science parser | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `previous_record_hash_target` | Shared export contract | exact immediately prior raw envelope bytes | Producer publication stream | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `source_sequence_scope` | Shared export contract | per publication session and stream, contiguous from one | Producer publication stream | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `event_type` | Continuous export mapping | explicit START, discovery, health/gap, decision, market, or FINAL classification | Producer owns mapping; unsupported classes fail closed | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `stream_id` | Continuous export mapping | fixed versioned family stream selected before serialization | Producer publication contract | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `session_id` | Continuous session authority | owner-wrapped `session_owner_id` in `ContinuousResearchSessionAuthorityV1` | Continuous export owner; never Science | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `source_owner_identity` | Continuous session authority | `source_owner_identity` | Continuous/STAT-DATA owner | `AVAILABLE` |
| `source_interface_identity` | Continuous session authority | `source_interface_identity` | Shared producer/export boundary | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `source_contract` | Shared export contract | fixed `ResearchExportEnvelopeV1` | Canonical Science contract | `AVAILABLE` |
| `source_contract_version` | Shared export contract | fixed `1.0.0-proposal` required by the accepted consumer | Canonical Science contract | `AVAILABLE` |
| `source_event_id` | Continuous source or export authority | snapshot ID for discovery; deterministic owner-issued ID for START/FINAL/gap | Existing source identity or producer owner wrapper key | `AVAILABLE` / `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `source_event_fingerprint_sha256` | Exact source-byte binding | `SHA256(raw_source_bytes)`; START/FINAL bind exact session-authority bytes | Exact bytes, not reparsed JSON | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `source_sequence` | Continuous publication authority | deterministic chronology/identity order within stream | Source clock plus stable source ID; ties fail closed | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `event_time` | Continuous source | discovery `requestedAt`; gap discovery `receivedAt`; START open; FINAL `closed_at`; other families use their exact semantic clock | Source owner clock | `AVAILABLE` |
| `effective_known_at` | Continuous source | discovery/gap `receivedAt`; family-specific provider known/receipt or decision cutoff | Source/provider owner, never exporter wall clock | `AVAILABLE` |
| `emitted_at` | Continuous source/publication authority | discovery/gap `receivedAt`; exact event time for START/FINAL | Existing source clock or explicit session authority | `AVAILABLE` / `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `previous_record_sha256` | Continuous publication authority | SHA-256 of exact previous envelope file bytes, or contract genesis | Producer stream | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `payload_sha256` | Continuous publication authority | SHA-256 of exact canonical payload bytes | Producer serializer; rechecked by Science | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `authority` | Shared safety boundary | fixed `RESEARCH_ONLY` | Contract | `AVAILABLE` |
| `execution_authority` | Shared safety boundary | fixed `NONE` | Contract | `AVAILABLE` |
| `payload` | Continuous source/export mapping | discovery/health/session mappings are compatible; decision/outcome eligibility binding is not | Producer owns ordinary values; commitment crosses the ownership boundary | `CONTRACT_CHANGE_REQUIRED` for decision/outcome |

The discovery-only draft proved that a future implementation can record current
raw envelope hash, byte length, relative path, source binding, sequence, and
previous hash in a producer manifest without changing the envelope. That draft
is diagnostic only and is not an accepted implementation.

## Discovery payload mapping

| Science field | Exact Continuous source | Mapping rule | Status |
|---|---|---|---|
| `discovery_cycle_id` | `snapshotId` | owner-wrapped `DISCOVERY_CYCLE_ID` | `AVAILABLE` |
| `cycle_state` | `status`, `coverageState`, `unseenRowCount` | `COMPLETE`, `ZERO_RESULT`, `PARTIAL`, or `FAILED`; bounded prefix with known unseen rows is `PARTIAL` | `AVAILABLE` |
| `query_or_policy_fingerprint_sha256` | `queryFingerprint` | exact lowercase hash | `AVAILABLE` |
| `discovery_time` | `requestedAt` | exact RFC3339 bytes, role `DISCOVERY_TIME` | `AVAILABLE` |
| `provider_received_at` | `receivedAt` | exact RFC3339 bytes, role `PROVIDER_RECEIVED_AT` | `AVAILABLE` |
| `returned_row_count` | `rows[]` | exact array length, reconciled to represented count | `AVAILABLE` |
| `row_order_complete` | frozen `rows[]` | PRESENT true only after validated whole-document parse | `AVAILABLE` |
| `observation_ids_in_source_order` | `rows[]` array order and `rowId` | owner-wrapped observation IDs in exact raw-array order | `AVAILABLE` |
| `provider_health_event_ids` | exporter-created explicit gap for bounded prefix | exact owner-wrapped gap ID, or empty | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| `zero_result` | validated row count/status | exact boolean | `AVAILABLE` |
| `completeness` | `coverageState` / `status` | exact source text as evidence value | `AVAILABLE` |
| observation `source_row_ordinal` | `rows[]` array position | zero-based export ordinal required by consumer; original `sourceRowIdentity` remains bound by raw source hash and `owner_member_id` | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| observation/source identity | `rowId`, `candidateIdentity`, `sourceRowIdentity` | owner-wrapped; rejected rows use their exact row ID as candidate-member identity, never symbol | `AVAILABLE` |
| row fingerprint | `rows[].fingerprint` | exact source row fingerprint | `AVAILABLE` |
| instrument symbol | `rows[].symbol` | PRESENT evidence value | `AVAILABLE` |
| asset type / venue / security ID | not present in discovery snapshot | explicit `NOT_CAPTURED`; never inferred from ticker | `PRODUCER_CAN_EMIT_AUTHORITATIVELY` |
| rank | `globalObservationOrdinal` or validated array rank | positive exact source order | `AVAILABLE` |
| candidate facts | `sourceValues` | only exact supported conversions: price decimal text, relative-volume decimal text, comma-stripped integer volume | `AVAILABLE` |
| materially evaluated | `disposition` | true after validated qualification disposition | `AVAILABLE` |
| rejection/gap reasons | `dispositionReasons[]` | versioned reason objects preserving exact codes | `AVAILABLE` |

## START, FINAL, gaps, and outcomes

START fields can be issued by a future exact canonical producer authority
document binding publication/session ID, market date/timezone/open/close,
bounded session kind, runtime activation, source root identity, source
namespace, and the frozen follow-up policy.

The future FINAL must be created only after every admitted source document has
validated, every deterministic stream has no tie/hole/reuse, every envelope has
been create-or-verified, and every explicit gap has been emitted. It must bind
exact pre-FINAL stream heads, counts, gaps/conflicts/pending records, source
root, close reason, and close time.

Bounded-prefix discovery with an authoritative positive `unseenRowCount`
produces one terminal `SOURCE_RETENTION_GAP` provider-health event. Its affected
record is the exact discovery cycle. No silent absence is treated as coverage.

The selected replay has no exact decision/observation/series/horizon/bar chain,
and the eligibility-authority conflict independently prevents an operative
decision/outcome producer. No outcome was produced. Symbol/time heuristic joins
remain forbidden.

## Sanitization and capability boundary

Only selected discovery snapshots plus the minimal session-authority document
are copied. Configuration, credentials, auth material, account data, balances,
positions, orders, broker capabilities, and operational production paths are
excluded. Key/value scans run before any envelope is committed, and the Science
parser independently rejects prohibited authority/capability fields.

No provider client, network call, account/broker/order authority, service,
scheduler, poller, source mutation, or production activation was added.
`READY_FOR_PROSPECTIVE_ALWAYS_ON_CAPTURE` remains `NO`.
