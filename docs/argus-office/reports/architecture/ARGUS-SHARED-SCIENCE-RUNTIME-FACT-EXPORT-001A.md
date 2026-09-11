# Shared runtime fact export 001A — V2 candidate

Status: IMPLEMENTED_PENDING_QUALIFICATION_AND_REVIEW; not merged, installed or active.

## Goal Charter and registration

The owner authorizes reconciliation of historical recorder requirements forward
to current canonical V2, then a minimum shared producer interface and offline
qualification. The operator outcome is exact owner facts crossing a one-way
export boundary without a producer depending on future Science authority.

| Field | Admission |
| --- | --- |
| LANE / TASK_ID | INTEGRATION_SHARED_CONTRACT / ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001A |
| PARENT_TASK | ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001 |
| BASE_CANONICAL_SHA | a5dfbccbb3a77a78bb80412d30f06e610ccecd43 |
| TASK_OPENING_TREE | d259e40c76a7607f324ae077b81f3e2ac0fae770 |
| BRANCH | codex/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001A-V2 |
| WORKTREE | C:/Users/steve/AppData/Local/MomentumHunter/worktrees/INTEGRATION-ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001A-V2 |
| EVIDENCE_ROOT | F:/ArgusQualification/Integration/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001A-20260910T104348Z |
| TEMP_RUNTIME_ROOT | EVIDENCE_ROOT/runtime; generated isolated test roots only |
| PACKAGE_ROOT | EVIDENCE_ROOT/packages |
| OWNED_PATHS | momentum_hunter/research_fact_export_v2.py; tests/test_research_fact_export_v2.py; tools/verify_shared_runtime_fact_export_001a.py; tools/package_shared_runtime_fact_export_001a.py; this report |
| PROTECTED_PATHS | All existing Git paths and all foreign worktrees/evidence; in particular continuous_research_export.py, strategy_science_recorder/**, strategy_science_source_reader.py, providers/auth/readiness, GUI, research/r4_closure_repair_003a/**, shared Roadmap/ledger/log |
| ALLOWED_CAPABILITIES | New scoped branch-only source/tests/tools/report; offline synthetic qualification; read-only sealed evidence; isolated package assembly; candidate commits |
| PROHIBITED_CAPABILITIES | Master mutation, merge/push, install/activation, service/scheduler, provider/auth/network acquisition, account/position/broker/order/Paper/Shadow/execution authority, historical evidence mutation |
| PACKAGE_GATE | Frozen candidate ZIP with exact source, dependencies, tests, evidence, manifest and detached checksum |
| SECOND_EYE_GATE | Fresh independent Astra after final-byte freeze; no author self-acceptance |
| MERGE_GATE | Not authorized by this task; separate Integration directive |
| SHARED_RUNTIME_MUTATION_AUTHORIZED | New dormant producer-interface source only; no existing runtime wiring |
| SERVICE_MUTATION_AUTHORIZED / SCHEDULER_MUTATION_AUTHORIZED | NO / NO |
| MASTER_CLEAN / MASTER_LOCAL_ORIGIN_SYNC | YES / YES at admission, including direct remote master |
| LANE_WORKTREE_CLEAN | YES before this task report |
| OWNED_PATHS_DECLARED / PROTECTED_PATHS_DECLARED | YES / YES |
| CROSS_LANE_DEPENDENCY | Existing immutable canonical V2 publisher/parser/custody/outcome contracts, read-only reuse |
| SAFE_TO_IMPLEMENT_IN_PARALLEL | YES within these exact owned paths; recheck if authority changes |

Authority attachments: parent 6d582871-a086-4d36-af91-870e58de8be6 and amendment
e887e900-196c-4784-9866-b8a21e080f9b under C:/Users/steve/.codex/attachments,
each named pasted-text.txt. The amendment expressly resolves the prior V1/V2
admission blocker; historical V1 is preserved, not relabeled or imported.

## Lane ownership proof

Canonical, local master, tracking master and direct remote master were all
a5dfbccbb3a77a78bb80412d30f06e610ccecd43; canonical tree matched the directive.
The older same-named branch at 1ed210b9075b208dca09fb69a1978139bec2ace6,
tree 75b21f62918f52d33eec8067bb10182d1525318e, remains clean and untouched.
No old-candidate implementation is imported.

- Engine worktree LANE-OPENING-ENGINE retains 1c1c3f4599d96cd95e5e9cdd5f2011c8add739d1,
  tree bbf8ea6ab1591ba5143a4cde85a63c72964d5e76, clean. Current owner directive
  ARGUS-ENGINE-READINESS-FAILURE-FORENSIC-001 (attachment c0ca3824-5c78-4284-851f-7ef6f5897971)
  allows only external forensic artifacts and no Git source changes. Its task
  session at 2026-09-10T10:24:00Z explicitly pauses auth-concurrency work.
  ENGINE_PATH_OVERLAP=NONE; no readiness diagnosis or repair belongs here.
- Science current task is R4-FRESH-ENTRY-CLOSURE-REPAIR-003A, not the stale
  persistent Reader branch. Its separate LANE-SCIENCE-R4-CLOSURE-REPAIR-003A
  worktree starts at the same canonical head/tree. Its external GOAL-CHARTER.md
  declares OWNED_GIT_PATHS=research/r4_closure_repair_003a/** only and protects
  every other Git path. SCIENCE_003A_PATH_OVERLAP=NONE. Foreign untracked files
  there are owned by Science and are neither copied nor changed here.
- GUI is paused, retaining clean head 9437d7e03cf09d92b03b9f5fdd55ca3a27fee7fd,
  tree 341ad607543a690347a070cb2f24a7fc4aa01508. Preserved candidate paths are
  src/MomentumHunter.Contracts/WorkstationContracts.cs,
  src/MomentumHunter.EngineBridge/PythonShadowReviewClient.cs and
  tests-dotnet/MomentumHunter.Presentation.Tests/PythonShadowReviewClientTests.cs.
  GUI_PATH_OVERLAP=NONE.

## Source authority and minimum slice

Historical design root:
C:/Users/steve/OneDrive/Documents/ArgusReviewBundles/LANE-SCIENCE/ARGUS-SCIENCE-ALWAYS-ON-RECORDER-CONTRACT-001-20260831-213529-9638763-CT.
Sidecar SHA256 f40207a300b0d5ea91992e4e7f03491e3de031714a8928d01118a8a9b9ec4434;
all 12 entries verified. Schema file SHA256
f8b739ef7738b5e64bfd86b52b0a3f7d3b50fd006cb60a66954c206d276a0a40.

Current authoritative code/docs are strategy_science_recorder/contract.py,
custody.py, canonical.py, outcomes.py; continuous_research_export.py;
the canonical 001/001A eligibility authority reports; and the Continuous Export
002 contract trace. The accepted Roadmap records V2 integration. Its leading
governance snapshot predates current Git; this task uses the explicitly required
current head and does not modify shared Roadmap state.

Add an owner-neutral V2-only facade with named family composition, explicit
version/owner/root admission, and complete ordered discovery-row accounting.
Compose (do not fork or override) ContinuousResearchExporterV2. Existing wire
serialization, hashes, sequence, atomic publication, restart and FINAL remain
the sole implementations. Preserve its fixed exporter profile as implementation
provenance; factual ownership remains in source owner/interface fields.

Producer owns supplied source facts, exact IDs and clocks. Publisher owns V2
wire bytes and publication. Science alone owns custody capture/receipts and
post-receipt eligibility. Existing OutcomeAttachmentV1 remains a separate later
Science linkage surface, not a producer event or callback. No natural runtime
owner is wired or activated by this candidate.

## MVP reconciliation

| MVP | Classification | Scope under V2 |
| --- | --- | --- |
| 01 session | SEMANTICALLY_RECONCILED_TO_V2 | Producer START separate from Science custody |
| 02 denominator | UNCHANGED_UNDER_V2 | All ordered rows and zero/partial/failed cycles |
| 03 identities | SEMANTICALLY_RECONCILED_TO_V2 | Preserve producer IDs; distinct custody/outcome IDs |
| 04 decisions | SEMANTICALLY_RECONCILED_TO_V2 | No producer Science-eligibility hash |
| 05 market/score | UNCHANGED_UNDER_V2 | Exact canonical owner facts and missingness |
| 06 catalyst | UNCHANGED_UNDER_V2 | Existing identity/time evidence only; no crawler |
| 07 plan/levels | UNCHANGED_UNDER_V2 | Actual owner-created plan only |
| 08 eligibility | SEMANTICALLY_RECONCILED_TO_V2 | Science after receipt; producer freezes START policy |
| 09 outcomes | SEMANTICALLY_RECONCILED_TO_V2 | Producer bars, separate existing Science outcome attachment |
| 10 failure | UNCHANGED_UNDER_V2 | Exact health/affected IDs and retained failed rows |
| 11 anti-hindsight | SEMANTICALLY_RECONCILED_TO_V2 | Distinct producer, custody and eligibility hash domains |
| 12 restart | UNCHANGED_UNDER_V2 | Reuse authoritative immutable published bytes and recovery |
| 13 closeout | SEMANTICALLY_RECONCILED_TO_V2 | Producer FINAL separate from Science corpus metrics |
| 14 doorway | SEMANTICALLY_RECONCILED_TO_V2 | Five canonical V2 variants; forbid new V1 emission |

MVP08 historical FIXED_HASH_BUCKET is SUPERSEDED_BY_V2 for this task: canonical
currently accepts only ALL_UNIQUE_INSTRUMENTS. Autonomous outcome acquisition,
scheduling and natural full-session coverage promotion are
NOT_IMPLEMENTABLE_WITHOUT_NEW_AUTHORITY; no such claim is made here.

| Historical record family | Classification | Canonical V2 route |
| --- | --- | --- |
| discovery-cycle | UNCHANGED_UNDER_V2 | DISCOVERY_CYCLE.discovery_cycle |
| candidate-observation | SEMANTICALLY_RECONCILED_TO_V2 | DISCOVERY_CYCLE.observations; Science adds custody and eligibility |
| decision-event | SEMANTICALLY_RECONCILED_TO_V2 | DECISION_FACT.decision_event; no producer eligibility hash |
| market-snapshot | UNCHANGED_UNDER_V2 | MARKET_FACT.market_snapshot |
| reference-plan | UNCHANGED_UNDER_V2 | Optional DECISION_FACT.reference_plan |
| provider-health-event | UNCHANGED_UNDER_V2 | PROVIDER_HEALTH.provider_health_event |
| outcome-observation | SEMANTICALLY_RECONCILED_TO_V2 | Existing separate Science OutcomeAttachmentV1 |

SESSION_MANIFEST supplies START/FINAL. No duplicate custody record catalog or
eighth producer event type is introduced. The existing Science-only
science-eligibility record remains separate and unchanged.

## Recovered V2 code/document alignment

| Authority | Canonical evidence and invariant |
| --- | --- |
| Producer | continuous_research_export.py _build_raw and _semantic_clocks: owner/session/stream/event IDs, source clocks and exact producer content only |
| Wire version | contract.py parse_export_envelope_v2: schema_version=2.0.0; source_contract=ResearchExportEnvelopeV2; source_contract_version=2.0.0-proposal; profile=ARGUS_SCIENCE_OFFLINE_RESEARCH_EXPORT_V2 |
| Serialization/hash | canonical_json_v1 / ARGUS_CANONICAL_JSON_V1; exact UTF-8 canonical bytes with LF; SHA-256; previous_record_sha256 targets prior raw source envelope; sequence is per-stream contiguous from one |
| Source identity | Publisher fingerprints event_type, session_id, source_event_id, source_owner_identity and stream_id; identity and payload hashes remain distinct |
| Custody/receipt | StrategyScienceRecorder creates normalized payloads, recorder_capture_time and exact receipt-chain hashes after source receipt; producer cannot inject them |
| Eligibility | _science_eligibility_record binds producer content, observation payload and receipt, policy/instrument/first observation and receipt-effective time; no producer eligibility prerequisite |
| Physical chronology | science_evaluated_at records first physical construction or exact staged recovery time, not borrowed T1 receipt time; its exclusion from semantic eligibility hash cannot change full record/receipt bytes |
| Outcome | Existing later OutcomeAttachmentV1 links exact decision, observation, eligibility, series and canonical bars; producer source bytes never receive reverse Science input |
| Legacy | parse_export_envelope_v1 remains distinct; no historical record is migrated, relabeled or written by the new facade |

These code paths match the accepted 001/001A authority-model reports and the
Continuous 002 contract trace. Factual source ownership is not changed by reusing
the existing publisher implementation profile. The candidate supplies no new
trust issuer: the caller is an already-authoritative offline producing owner,
and later runtime attachment/qualification requires separate authorization.

## Acceptance and evidence required

Require exact V2 parsing and direct Science custody without rewrite; V1/wrong
version/producer eligibility/missing or conflicting authority rejection; both
non-Continuous owners; denominator/count/order and repeated ticker/setup proof;
explicit missingness and immutable decision facts; no callbacks/provider/order
capability; declared root/path/reparse/hardlink isolation; duplicate/conflict and
composed restart/fault recovery; historical V1 readability and unchanged bytes;
Science T1/T2 ownership and canonical outcome compatibility. Import does nothing.

Use approved external Python 3.12.6 executable whose SHA256 is
737A7E3B71E3578F8432ACC7DD88C452E593622C544BC13DA4789D69C63DA5AE.
No environment changes. Run scoped final-byte tests, owner/Science/Reader/
Continuous regressions, bounded offline rehearsal, compile/import, protected
diff, credential scan and final applicable repository suite. Preserve failures;
never reroll unrelated auth defects into green. Full-suite success cannot be
assumed from narrow tests. Freeze source then obtain fresh independent Astra
and exact package review. Docs-only closeout does not require redundant full runs.

Root checks are filesystem admission controls under a trusted isolated operator
workspace, not an OS sandbox against malicious concurrent filesystem changes.
Offline fixture compatibility is not provider truth, activation or natural
coverage. Preserve all historical unknown chronology/identity as Tier 3; never
synthesize it into prospective authority. Tier-1 source/authority conflicts stop
the affected candidate; only narrow authorized correction is allowed.

Goal Steward framing: /root/runtime_fact_current_boundary advisory architecture
brief; independent final review must use a fresh agent. Open owner decisions:
none after 001A; implementation and acceptance gates remain to be proven.
Rollback is nonadoption and retention of the isolated branch/evidence. No master
reset, historical overwrite, deployment rollback or data deletion is required.

## Qualification record and scope accounting

The implementation consists of one new family-composition facade and 22 new
tests. It introduces no wire record schemas: all five V2 envelope variants and
six producer-owned historical families reuse current canonical validation. The
seventh historical family, outcome-observation, is exercised through unchanged
Science OutcomeAttachmentV1. All 14 MVP capabilities are reconciled above;
this is not a claim to have built 14 new subsystems or an always-on recorder.

Initial Builder run 001 is retained: 22 tests, five errors and one platform skip.
The errors were new-test inventory reads of Windows-locked `.writer.lock` bytes,
including cascading cleanup. Tests were corrected within their owned file to
hash semantic persisted files without reading the active lock; the alias test
uses an unlocked metadata file, and actual Windows junction creation covers
reparse rejection when symlink creation lacks privilege. Builder run 002 and
the parent's approved-environment final focused run both pass 22 tests with
zero failures/errors/skips. The failed temporary tree and both hardlink names
remain preserved. Packaging copies their bytes as regular files, records the
original alias relationship, and refuses unaccounted external aliases.

The approved-environment owner compatibility run passes 130 tests, covering
the existing exporter, all seven recorder modules, and Reader V2. The synthetic
offline rehearsal passes both distinct non-Continuous producer identities,
exact restart/readback, direct unchanged Science custody, all seven historical
families, seven outcome horizon semantics, and a separate early-close truncation
case. Only the supplied synthetic +5M bar provides PRESENT value evidence;
other horizon/path values remain explicitly UNAVAILABLE. Original producer and
Science decision bytes are unchanged after outcomes. Source fixture versions,
all supplied facts and generated custody bytes are retained in external evidence.

The full applicable suite is complete Python unittest discovery, matching the
accepted Continuous Export 002 dependency-closure qualification. Native/.NET
tests are not run: no C#, native manifest, native runtime, project/package file,
or dependency changed. This is a documented applicability boundary, not a
claim that a native suite passed. Final run counts and package/reviewer identities
are recorded in the immutable external closeout rather than creating a
self-referential commit hash inside this report.

Tier 2 operational limitation: static root alias checks are not a hostile-actor
filesystem sandbox. An alias introduced after initialization blocks further
operations, including checkpoint-writing close, and retains the writer lock
until separately authorized operator resolution; this behavior is tested.
No ambiguous-root repair or production cleanup occurs here. Tier 3 limitation:
synthetic contract coverage is not natural source coverage or provider truth.
No finding grants runtime attachment, capture scheduling, account or execution
authority. Required final full-suite and fresh review results remain gates until
their evidence receipts exist.
