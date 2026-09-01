# ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-001 Source Inventory

## Admission result

`IMPLEMENTATION_GO = NO`

`BLOCKER = MISSING_AUTHORIZED_CROSS_LANE_EXPORT`

`CROSS_LANE_CONTRACT_CHANGE_REQUIRED = YES`

No current local source surface satisfies the combined immutable-byte,
supported-reader, market-session identity, START/FINAL finality, contiguous
source sequence, previous-raw-envelope hash, known-at, and separate-outcome
requirements of the accepted Strategy Science custody kernel. Science must not
fill those gaps by interpreting private producer internals or reconstructing
missing session facts.

This inventory was performed read-only from canonical
`04f6f8382e03906cbd174711a1d4df2d43a5cab4`. No provider was contacted and no
source, runtime, service, scheduler, or authentication state was changed.

## Source map

| Source | Authority | Format | Identity | Timestamp / known-at | Append / immutable characteristics | Safe for Science read | Gap / limitation |
|---|---|---|---|---|---|---|---|
| Installed Continuous production evidence records | Continuous Runtime and dedicated writer; `RESEARCH_ONLY`; no execution or order authority | Canonical write-once sharded JSON records plus ACK and generation index; observed profiles `production-continuous-evidence-record-v1` and `production-continuous-evidence-record-v2` | Runtime/configuration identity, intent identity, record identity/fingerprint, intent sequence and predecessor, topology fingerprint, ACK record hash | Intent `requested_at`; payload `knownAt` and evidence-known-at values where produced | Strong create-only/hash-addressed record storage, but the installed root remains active | **NO** | Public `read_evidence_snapshot()` validates the dormant topology and rejects the production topology. The runtime chain crosses market sessions and record documents contain no recorder-compatible session field, START/FINAL manifest, terminal stream reconciliation, or exact prior-raw-envelope byte hash. Natural composition records do not provide complete setup/plan identities. |
| Continuous Finviz/Schwab source-evidence snapshots | Provider adapter / Continuous producer | Per-observation JSON under runtime source-evidence namespaces | Discovery/request/admission fingerprints and provider/source identities | Request, provider, receipt, evaluation, and known-at fields vary by record | Producer-owned discrete files, but direct visibility has no separate terminal publication manifest | **NO** | No complete-session atomic export, no shared finality, no custody stream hash chain, and no operative `ResearchExportEnvelopeV1`. Safe only as frozen owner-side input to a future export task. |
| Canonical Schwab minute/daily candle evidence | Canonical provider-reconciliation owner | Versioned aggregate JSON partitions read through cutoff-aware canonical loaders | Instrument/minute identity, provider version, receipt/version identity | Candle time, first receipt, original first receipt, and as-of cutoff | Coherent atomic replacement; aggregates can gain later versions | **NO** | Suitable supporting market/outcome evidence only. It is not an append-only source-event stream and supplies no source-session START/FINAL or exact export envelope chain. |
| Prospective denominator store | Research-only denominator owner | Canonical write-once JSON activation, membership, attempt, population, receipt, historical-context, and outcome-link records | Activation, cycle, population, member, attempt, opportunity, and outcome-link identities | Contemporaneous observed/known-at fields are retained by the store contracts | Strong create-only per-record persistence | **NO** | Strong supporting denominator source, but not a complete discovery/decision/market/provider-health/session export and not a natural custody-envelope producer. |
| Candidate lifecycle ledger | Continuous lifecycle owner | Canonical aggregate JSON ledger | Event sequence, event/predecessor, opportunity/setup, provider and runtime identities | Occurred, received, observed, and provider times | Logically append-only events inside an atomically replaced whole-file aggregate | **NO** | The physical source file changes. It has no stable per-event raw publication contract or recorder session terminal manifest. |
| Continuous TradePlan/no-plan and runtime-source-admission ledgers | Continuous producer | Canonical aggregate JSON stores | Plan/no-plan, source, lifecycle, material, request, and result fingerprints | Decision cutoff and evidence-known-at values where recorded | Atomically replaced aggregates | **NO** | Contextual owner evidence only; not immutable per-event export envelopes, no complete cross-source session/finality contract. |
| Continuous attempt-event ledger | Continuous runtime | Append-oriented JSONL | Runtime/configuration, attempt sequence, request, stage, and event identity | Observed time, request cutoff, and evidence-known-at | Append-oriented; an incomplete trailing line can be externally visible | **NO** | Runtime-internal surface with partial-tail risk and no market-session terminal manifest or shared source export chain. |
| Legacy raw captures and accepted forensic/review packets | Capture/review owner; task-specific research authority | Frozen JSON/ZIP artifacts with manifests and checksums | Capture/session/provider/scanner or review-package identities | Task- and capture-specific timestamps | Frozen and SHA-bound after closeout | **NO** | Useful sanitized replay material for an owner-side export, but too coarse or differently shaped; lacks the full continuous decision, plan/no-plan, gap, stream, and finality contract. |
| Opening evidence | Opening Engine authority | Opening-specific immutable evidence and accepted review artifacts | Opening runtime/session/candidate identities | Opening-specific chronology | Separate lane and release boundary | **NO** | Not admitted under this Science task. A shared read/export contract would require separately serialized authority. |
| Natural `ResearchExportEnvelopeV1` / `OutcomeAttachmentV1` producer output | Proposed cross-lane owner export | Expected canonical UTF-8 JSON bytes with LF and exact SHA-256 chaining | Owner-wrapped session, event, observation, decision, plan, market, provider-health, and outcome identities | Exact event/effective-known-at/emitted-at clocks | Expected create-only terminal publication | **NO — NOT FOUND** | Canonical explicitly labels `ResearchExportEnvelopeV1` as a proposed shared interface and makes no natural-producer compatibility claim. Exact searches of accepted Continuous, prospective, second-eye, and Opening corpora found no operative producer output. |

## Installed-source observation

The installed deployment configuration identifies:

- evidence root: `C:\ProgramData\MomentumHunter\Continuous`;
- program: `continuous-opportunity-production`;
- active namespace observed: `continuous-evidence-v2-continuous-opportunity-production-1dcf3a01a57c`;
- configuration fingerprint: `1dcf3a01a57caf9b5668fd97cf508b17f1cc5c025fc477fc67f15874fc19cfbf`;
- runtime build hash: `a44e9f35cfdf804efc85bad9459b5102902d695b9d8db179885e65b31450ef45`.

A single bounded read-only observation at
`2026-09-01T15:05:11.4180931-05:00` found 967 record files (9 v1 and 958 v2),
969 ACK files, and 969 generation-index files. Record evidence types were 784
discovery, 75 readiness-deferred, 33 composition, 33 denominator, and 42 system
failure. Positive intent sequences covered 1 through 963 without a missing
integer, while no record document exposed a recorder-compatible session field
or final marker.

An earlier independent observation found 966 records. The increase occurred
without any task write and confirms the installed root is active rather than a
frozen replay boundary. The task did not continue polling it.

## Minimum safe reader boundary after owner export exists

Science can implement a mechanical reader only over a caller-supplied frozen
root already containing valid owner-produced `ResearchExportEnvelopeV1` and
`OutcomeAttachmentV1` bytes. That future reader must:

1. Validate a producer manifest binding every relative path, byte length,
   SHA-256, source-root identity, build/config/runtime activation, and terminal
   publication state.
2. Reject symlinks/reparse points, traversal, absolute paths, case collisions,
   temporary files, unknown files, and inventory mismatches.
3. Preserve the exact source bytes; filesystem enumeration and filesystem
   timestamps have no chronology authority.
4. Group by session and stream; order only by authoritative `source_sequence`;
   require sequence one onward and the exact previous-envelope byte hash.
5. Require START before events and reconcile FINAL counts, stream heads, gaps,
   conflicts, and pending records before custody finalization.
6. Keep outcome attachment streams separate from discovery/decision evidence.
7. Advance Science-owned immutable cursor receipts only after custody acceptance
   and custody verification.
8. Keep Science receipt time separate from source known-at and reconstruct
   cursor state by revalidating exact source bytes after restart.

Synthetic fixtures alone could test these mechanics, but cannot prove a real
Momentum Hunter source boundary or an honest replay of owner-produced evidence.

## Required serialized owner contract

Authorize a Continuous/Integration-owned task, recommended as
`ARGUS-CONTINUOUS-RESEARCH-EXPORT-001`, to adopt the existing recorder proposal
rather than create a competing schema.

Every `ResearchExportEnvelopeV1` must provide:

`schema_version`, `offline_reference_profile`, `canonicalization_version`,
`hash_algorithm`, `hash_unit`, `previous_record_hash_target`,
`source_sequence_scope`, `event_type`, `stream_id`, `session_id`,
`source_owner_identity`, `source_interface_identity`, `source_contract`,
`source_contract_version`, `source_event_id`,
`source_event_fingerprint_sha256`, `source_sequence`, `event_time`,
`effective_known_at`, `emitted_at`, `previous_record_sha256`, `payload_sha256`,
`authority`, `execution_authority`, and `payload`.

The owner export must emit the approved event families:

- `DISCOVERY_CYCLE`
- `DECISION_FACT`
- `MARKET_FACT`
- `PROVIDER_HEALTH`
- `SESSION_MANIFEST`

START must bind market date/timezone, session kind/open/close, source namespace,
source root, runtime activation, and the frozen outcome-followup policy. FINAL
must bind close reason/time, complete event-type counts, pending events,
gap/conflict counts, and every stream head `{stream_id,
last_source_sequence,last_source_envelope_sha256}`.

The producer must own, without Science inference, the mapping of discovery
order, candidate/setup/plan/no-plan identity, instrument and market-snapshot
identity, provider receipts, decision cutoffs and known-at references,
denominators, gaps, and finality. Outcomes must be separate
`OutcomeAttachmentV1` records binding the exact decision, observation,
instrument, series, horizon, and canonical bar bytes.

Publication must be atomic/create-only under a producer-owned export root with
a terminal inventory manifest. The first sanitized export should be derived by
the owner from accepted 002D evidence, then replayed entirely offline by
Science.

## Final source-admission classification

```text
SOURCE_INVENTORY_COMPLETE=YES
SAFE_FOR_SCIENCE_READ_SOURCE_COUNT=0
LOCAL_READ_ONLY_SOURCE_BOUNDARY_PROVEN=NO
IMPLEMENTATION_GO=NO
BLOCKER=MISSING_AUTHORIZED_CROSS_LANE_EXPORT
CROSS_LANE_CONTRACT_CHANGE_REQUIRED=YES
SCIENCE_PROVIDER_CLIENT_ADDED=NO
LIVE_PROVIDER_CONTACT_OCCURRED=NO
SOURCE_EVIDENCE_MUTATED=NO
CONTINUOUS_LANE_MUTATED=NO
OPENING_LANE_MUTATED=NO
GUI_LANE_MUTATED=NO
READY_FOR_OFFLINE_SOURCE_READER_REPLAY=NO
READY_FOR_PROSPECTIVE_ALWAYS_ON_CAPTURE=NO
```
