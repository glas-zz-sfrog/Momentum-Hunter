# Goal Charter: ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001

## Goal Statement

Implement and prove the smallest trustworthy, reusable Current-Edge Research
Ledger primitive that records exactly what research evidence and predictions
existed before an outcome was knowable, freezes those bytes and their identity,
and later records the admissible outcome in a separate immutable reveal packet
without changing the prediction-side evidence.

The lifecycle is exactly:

`OBSERVE -> FREEZE -> WAIT -> REVEAL -> COMPARE`

The governing proof is:

`PREDICT_FIRST_FREEZE_REVEAL_LATER = TRUE`

This is research-only, offline filesystem infrastructure. It is not a trading
feature, production observer, provider client, database, service, scheduler,
replay engine, model, or runtime decision path.

Required authority markers are immutable contract values:

`RESEARCH_ONLY = TRUE`

`PRODUCTION_DECISION_AUTHORITY = NONE`

`EXECUTION_AUTHORITY = NONE`

## Operator Outcome

Steven receives a deterministic offline demonstration and independently
reviewed evidence packet proving that a synthetic prediction was frozen before
synthetic future evidence and an outcome became available; survived restart
byte-for-byte; was referenced by a later reveal; resisted mutation, duplicate
conflict, chronology violation, tampering, corruption, and root escape; and has
no dependency capable of changing production behavior.

Completion establishes only that Argus can preserve prospective research
evidence truthfully. It does not establish prediction skill, alpha, market-data
coverage, model quality, data rights, production fitness, or authority to build
or activate a prospective observer.

## Starting Authority And Preconditions

The following preconditions are mandatory and must be reverified by Git
Steward before Builder work and again at closeout:

1. The accepted Strategy Science review branch and canonical integration resolve
   exactly to `848d20a6bd5a49e9bb8e179eaa374109756801b0`.
2. The byte-specific Strategy Science second-eye disposition remains
   `ACCEPTED_FOR_STEVEN_REVIEW`, with D01-D36 at 36/36 and AC01-AC20 at 20/20.
3. The accepted Goal Charter, main architecture packet, independent review,
   Roadmap, Task Log, and Branch Ledger remain internally consistent with an
   offline Current-Edge Ledger as the smallest separately authorized slice.
4. Canonical `master` and `origin/master` are synchronized at the accepted
   identity, the working tree is clean, and the task branch
   `codex/argus-current-edge-research-ledger-001` is created from that exact
   canonical state.
5. Current Roadmap authority remains unchanged: the general production freeze
   and Monday 2026-08-31 08:32 CT read-only checkpoint remain in force; the
   current prospective Momentum/Paper strategy remains the control; and this
   parallel research task does not reorder `Immediate Next` or `Next / Queue`.
6. Before any code edit, a read-only reuse inventory covers all ten directive
   areas: code/repository identity, strategy identity, configuration identity,
   runtime identity, evidence fingerprinting, immutable/write-once artifacts,
   opportunity/candidate identity, research governance, caller-defined storage
   roots, and tamper/restart validation.
7. Each reuse-inventory item is classified exactly as `REUSE_EXACTLY`,
   `REFERENCE_EXISTING_OWNER`, `EXTEND_MINIMALLY`, or `MISSING`, with source and
   test evidence. No name, file, or planning claim alone proves an owner.
8. Any competing authoritative owners, material canonical drift, or inability
   to establish deterministic immutable identity stops work rather than being
   normalized.

The Goal Steward observed the assigned branch at exact clean base `848d20a6`
before writing this charter. That observation does not replace the required Git
Steward preflight or the implementation-time reuse inventory.

If canonical has materially changed in conflict with the accepted architecture,
the terminal status is `BLOCKED_CANONICAL_DRIFT`. If two existing identity
owners conflict, the terminal status is `BLOCKED_IDENTITY_COLLISION`.

## Authorized Scope

The complete directive authorizes only:

- a minimal research-only module or equivalent isolated implementation for the
  two immutable packet contracts and their shared receipt/validation behavior;
- deterministic identity and canonical fingerprinting that reuse existing
  authoritative Argus owners where they exist;
- caller-supplied absolute research/test roots with deterministic contained
  paths and no default production location;
- offline freeze, idempotent duplicate, immutable conflict, later reveal,
  validation, read, restart, and tamper-detection operations;
- explicit point-in-time chronology and missingness validation;
- synthetic fixtures and one deterministic `TEST1` freeze/restart/reveal
  demonstration;
- focused offline tests, contract tests, serialization-stability tests,
  security tests, and bounded regression checks;
- documentation, review, and proof artifacts required by this charter;
- read-only repository inspection needed to prove reuse and production
  non-authority.

The implementation may own a research packet identity, receipt identity, and
caller-rooted artifact layout. It may not own or redefine an existing production
opportunity, candidate, strategy, configuration, code, runtime, evidence,
market-path, broker-outcome, account, order, or execution identity.

The Goal Steward subtask is narrower still: create only this Goal Charter. It
does not authorize the Goal Steward to edit code, tests, Roadmap, logs, or any
other artifact.

## Not Authorized

- No live market-data collection, provider call, Schwab call, Alpaca call,
  broker/account access, position request, or order request.
- No order creation, transmission, replacement, cancellation, execution, money
  movement, Paper, Shadow, or unattended live behavior.
- No production observation, production listener, production import hook,
  background process, service, scheduler, daemon, worker, queue, or runtime
  activation.
- No candidate generation, admission, scoring, ranking, readiness, TradePlan,
  Risk Governor, allocation, sizing, entry, stop, target, exit, or alert-policy
  change.
- No GUI/WPF work and no operator-control surface.
- No production database, schema, migration, configuration, secret, API key,
  credential, provider entitlement, or global machine dependency.
- No feature store, model registry, ML pipeline, machine-learning model,
  autonomous agent, graph/vector database, generalized data lake, Catalyst
  Radar, Time Machine, replay engine, event crawler, or prospective observer.
- No live or historical provider data acquisition, procurement, paid-service
  commitment, license acceptance, or claim that synthetic proof admits real
  evidence.
- No mutation of existing production evidence, historical evidence, packet,
  receipt, experiment, opportunity, candidate, market path, or broker outcome.
- No production path may import, call, write through, be configured by, or
  depend on this ledger. The ledger may record caller-supplied research evidence
  but cannot influence the supplying system.
- No activation, install, deployment, merge, or claim of production fitness
  follows automatically from passing this directive.

## Governing Invariants

1. Prediction evidence is frozen before outcome evidence becomes admissible.
2. Reveal is a new immutable object that references the prediction; it never
   updates, replaces, annotates, or normalizes the prediction bytes.
3. File creation time and modification time are never market chronology
   authority.
4. Every chronology claim comes from explicit normalized timestamps and
   evidence identities inside the contract.
5. A deterministic logical key detects conflicting content; a canonical content
   fingerprint binds semantic bytes; a receipt binds the exact stored bytes and
   terminal write result.
6. First write wins only in the literal immutable sense: identical bytes are
   idempotent, while different bytes for the same logical identity fail closed.
   There is no `LAST_WRITE_WINS` path.
7. Missingness is evidence. An unavailable value is never replaced with a
   plausible, current, reconstructed, or synthetic value without its explicit
   state.
8. All storage is below one caller-supplied absolute research/test root. The
   library has no default root and never discovers a root from production
   configuration, environment, registry, profile, working directory, or global
   machine state.
9. Restart opens the root by validating every relevant packet, receipt,
   fingerprint, logical-key mapping, reference, and chronology before returning
   an artifact. An invalid existing artifact prevents silent continuation.
10. Source-evidence locators are inert provenance values. Ledger validation does
    not dereference them, call a provider, or treat a path-like locator as a
    storage path.
11. Synthetic proof remains `SYNTHETIC` and cannot be relabeled as recorded,
    reconstructed, admitted, production, or historical evidence.
12. The simplest filesystem primitive is preferred. A database, service,
    observer, replay engine, model, or orchestration framework is a scope
    failure, not an optimization.

## Frozen Object Contracts

The implementation has exactly two principal immutable research objects.
Field aliases may map to an already authoritative owner only when the reuse
inventory documents the one-to-one mapping; semantics, requiredness, chronology,
authority, and identity below may not be weakened.

### Common Canonical Rules

- Canonical records use a single documented UTF-8 serialization with sorted
  object keys, deterministic array ordering where order is not semantic,
  duplicate-key rejection, finite numeric values only, and one terminal newline
  policy. Serialization output must be byte-stable across clean process restarts.
- Timestamps are timezone-aware UTC RFC 3339 instants with `Z`. Naive,
  malformed, ambiguous, silently corrected, or lossy timestamps are rejected.
- Contract, logical-key, content-fingerprint, and receipt algorithms are
  versioned. A change creates a new version and cannot reinterpret stored V1
  bytes.
- `canonical_fingerprint` is SHA-256 over the canonical semantic-content view,
  domain-separated by contract name and excluding only the self-describing
  `canonical_fingerprint` and `immutable_receipt_id` fields.
- The deterministic logical-key digest is separate from the content
  fingerprint. Storage paths are derived only from versioned contract tags and
  validated digest/path-safe identity components, never from a raw symbol,
  event label, locator, or caller-controlled relative path.
- `immutable_receipt_id` is deterministically derived from receipt contract,
  packet type, logical-key digest, and canonical fingerprint. A receipt also
  binds the SHA-256 of the complete stored packet bytes and the terminal write
  result. Validators recompute every layer.
- The first valid write to a logical key is exclusive and atomic-safe. A later
  byte-identical write returns the original packet and receipt as idempotent. A
  later nonidentical write to that key returns a deterministic immutable-conflict
  failure and changes nothing.
- A temporary, truncated, partial, or interrupted artifact is never accepted as
  the final object. Atomic replacement may not overwrite an existing immutable
  final path.

### A. `FrozenPredictionPacketV1`

The exact contract identity is
`argus-current-edge-frozen-prediction-packet-v1`; `packet_type` is
`FROZEN_PREDICTION_PACKET`.

| Field / semantic object | Frozen rule |
|---|---|
| `packet_schema_version` | Required exact contract identity above. |
| `packet_type` | Required exact value `FROZEN_PREDICTION_PACKET`. |
| `research_only` | Required Boolean `true`. |
| `production_decision_authority` | Required exact value `NONE`. |
| `execution_authority` | Required exact value `NONE`. |
| `research_protocol_id` | Required content-identified research protocol/experiment reference. |
| `research_opportunity_id` | Required unique research/opportunity identity. Reuse an authoritative opportunity owner when one exists; synthetic fixtures use an explicitly synthetic research identity and gain no production authority. |
| `symbol_entity_ref` | Required typed reference state. It contains the symbol/entity identity where applicable or an explicit `NOT_APPLICABLE`, `UNKNOWN`, or other permitted missingness state. |
| `event_ref` | Required typed reference state containing event identity and event type where applicable, otherwise explicit missingness. |
| `prediction_cutoff_at` | Required UTC instant representing the last admissible prediction-side decision time. |
| `evidence_availability_cutoff_at` | Required UTC instant; must be at or before `prediction_cutoff_at`. |
| `source_evidence_refs` | Required ordered, deduplicated collection of immutable evidence identities, fingerprints, availability times, source/provenance locators, and missingness/admission state. Empty is allowed only with an explicit reason. |
| `code_identity` | Required authoritative content identity. |
| `strategy_identity` | Required authoritative frozen strategy identity, even when the supplied harmless research observation is not a production decision. |
| `configuration_identity` | Required authoritative content identity for relevant configuration/assumption input. |
| `feature_observations` | Required typed collection of relevant values and states. Every value carries evidence/reference lineage or an explicit missingness state. Empty is explicit, never omitted by accident. |
| `research_predictions` | Required typed collection that may be empty. Supplied predictions declare object, value/distribution, horizon, units, source/model or rule identity, and evidence coverage. No trade authority follows. |
| `uncertainty` | Required typed collection that may be empty only with explicit `NOT_SUPPLIED`; it never defaults to confidence. |
| `abstention_rejection_state` | Required explicit `PREDICTED`, `ABSTAINED`, `REJECTED`, `WATCH`, or other versioned research-only state with reasons. The synthetic demonstration may use `WATCH`. |
| `missingness_ledger` | Required collection recording every relevant unavailable/unknown/not-applicable/reconstructed/synthetic input and reason. |
| `outcome_state` | Required exact value `UNRESOLVED`. No outcome value, label, return, outcome evidence, or future evidence field is permitted. |
| `created_at` | Required UTC artifact-creation instant. It is audit metadata, never market chronology or proof of evidence availability. |
| `canonical_fingerprint` | Required recomputable canonical semantic-content SHA-256. |
| `immutable_receipt_id` | Required deterministic receipt identity bound to this exact packet. |

The immutable prediction logical key is the versioned tuple
`(packet_schema_version, research_protocol_id, research_opportunity_id,
prediction_cutoff_at)`. If an existing owner supplies a stronger packet/sample
identity, the inventory may reference it in addition to this tuple but may not
remove a tuple field or permit two contents under one logical key.

Freeze rejects any packet when required identity is absent; a referenced
evidence item was available after `evidence_availability_cutoff_at`; an outcome,
label, return, future event, or other outcome-derived value is present; an
availability time cannot be established; chronology cannot be normalized; or a
mutable/unfingerprinted reference is required for integrity.

### B. `OutcomeRevealPacketV1`

The exact contract identity is
`argus-current-edge-outcome-reveal-packet-v1`; `packet_type` is
`OUTCOME_REVEAL_PACKET`.

| Field / semantic object | Frozen rule |
|---|---|
| `reveal_schema_version` | Required exact contract identity above. |
| `packet_type` | Required exact value `OUTCOME_REVEAL_PACKET`. |
| `research_only` | Required Boolean `true`. |
| `production_decision_authority` | Required exact value `NONE`. |
| `execution_authority` | Required exact value `NONE`. |
| `original_prediction_fingerprint` | Required exact canonical fingerprint of an already validated frozen prediction in the same caller root. |
| `original_prediction_receipt_id` | Required exact validated receipt identity of that prediction. |
| `research_protocol_id` | Required exact match to the prediction. |
| `research_opportunity_id` | Required exact match to the prediction's authoritative or explicitly synthetic identity. |
| `outcome_cutoff_at` | Required UTC instant through which outcome evidence is evaluated. It must be later than the prediction cutoff. |
| `outcome_resolved_at` | Required UTC instant when the outcome becomes resolved under the named semantic contract. It cannot precede or be indistinguishable from the prediction cutoff. |
| `outcome_evidence` | Required ordered, deduplicated collection of immutable evidence identity, fingerprint, availability time, value/state, and provenance. Empty is allowed only for a typed unresolved/censored outcome permitted by the semantic contract. |
| `outcome_provenance` | Required source, retrieval/availability, transformation, and admissibility lineage. |
| `outcome_semantic_id` | Required content-identified label/outcome definition. |
| `outcome_semantic_version` | Required immutable version; a changed definition creates a distinct reveal logical key. |
| `outcome_values` | Required typed outcome, censoring, ambiguity, or missingness values. It cannot restate or edit prediction-side features or predictions. |
| `created_at` | Required UTC artifact-creation instant; not chronology authority. |
| `canonical_fingerprint` | Required recomputable canonical semantic-content SHA-256. |
| `immutable_receipt_id` | Required deterministic receipt identity bound to this exact reveal. |

The immutable reveal logical key is the versioned tuple
`(reveal_schema_version, original_prediction_fingerprint,
outcome_semantic_id, outcome_semantic_version, outcome_cutoff_at)`.
Multiple outcome horizons therefore produce separately keyed reveal packets.
Reveal validation first revalidates the referenced prediction and receipt, then
requires the opportunity/protocol identity match and requires every outcome
evidence availability time to be strictly later than the prediction cutoff and
at or before the outcome cutoff. A reveal can never write the prediction path.

### Explicit Missingness Contract

Every field for which absence has meaning uses exactly one of these states:

`OBSERVED`, `MISSING`, `UNAVAILABLE`, `UNKNOWN`, `NOT_APPLICABLE`,
`RECONSTRUCTED`, or `SYNTHETIC`.

- `OBSERVED` requires a supplied value and evidence identity.
- `MISSING`, `UNAVAILABLE`, and `UNKNOWN` require a reason and cannot carry a
  fabricated value.
- `NOT_APPLICABLE` requires the contract reason the field does not apply.
- `RECONSTRUCTED` requires reconstruction method, source inputs, time of
  reconstruction, and explicit non-recorded status.
- `SYNTHETIC` requires fixture identity and can support only offline proof.
- No state may be inferred from `null`, zero, empty string, an omitted key, or a
  current value substituted for an unavailable point-in-time value.

## Storage And Restart Contract

1. Every public operation receives a caller-supplied absolute root. No default
   root exists.
2. The root is normalized and resolved once. Every derived parent and final path
   is checked to remain within that resolved root before creation and again
   before validation. Traversal components, alternate absolute paths, links or
   reparse points that escape the root, and raw caller-controlled filenames are
   rejected.
3. Deterministic paths are derived from contract version and validated logical-
   key digests. Symbols, event labels, source locators, and free text do not
   become path components.
4. Final immutable writes are exclusive. Temporary writes remain inside the
   root, are flushed as supported, validated, and promoted atomically without an
   overwrite path. Failure leaves no accepted final artifact.
5. Open/restart validation inventories the expected packet/receipt layout and
   validates canonical decoding, schema, logical key and path, fingerprints,
   exact-byte receipt binding, duplicate uniqueness, chronology, and reveal
   references before returning any object.
6. Unexpected, malformed, truncated, partial, conflicting, orphaned, tampered,
   or invalid existing artifacts produce a visible deterministic failure and
   prevent silent continuation for the affected root.
7. All directive demonstrations and proof artifacts are created beneath
   disposable synthetic/test roots. No production database, production config,
   production evidence root, user data root, or machine-global location is read
   or written.

## Temporal Integrity Contract

- Prediction-side evidence must prove `available_at <=
  evidence_availability_cutoff_at <= prediction_cutoff_at`.
- Outcome evidence must prove `prediction_cutoff_at < available_at <=
  outcome_cutoff_at`.
- `outcome_resolved_at` must be later than the prediction cutoff and consistent
  with the named outcome semantic. Equal-resolution ambiguity fails closed
  unless a source-proven ordering demonstrates predict-first chronology.
- File times, local clock inference, current provider state, later revisions,
  later normalizations, and future-aware reconstruction cannot repair missing
  chronology.
- Required times that are absent, naive, malformed, unsafe to normalize,
  contradictory, or too coarse to prove ordering cause deterministic rejection.
- `created_at` may be later than the market cutoff because serialization can lag;
  it cannot admit evidence that arrived during the lag.
- No silent timestamp correction or "probably close enough" tolerance is
  permitted.

## Required Deterministic Offline Demonstration

The final proof uses a disposable caller root and synthetic ticker `TEST1`:

1. At T0, create immutable synthetic evidence A, B, and C with availability at
   or before the frozen cutoff. Supply harmless research observation `WATCH`.
2. Freeze prediction P1 and capture its complete stored bytes, canonical
   fingerprint, logical-key mapping, and receipt.
3. End the process. Start a clean process against the same root and require full
   restart validation before P1 is returned.
4. At T1, make synthetic future evidence D and a synthetic market outcome
   admissible strictly after P1's cutoff.
5. Create outcome reveal O1 referencing P1's exact fingerprint and receipt.
6. Re-read P1 and prove its complete bytes and fingerprint are unchanged; prove
   O1 references exactly P1; prove D and the outcome occur only on the reveal
   side where appropriate.
7. Run all 18 hostile cases below against isolated subroots and record the exact
   deterministic rejection result and nonmutation proof.

The demonstration is insufficient if it runs in one process only, relies on
file times, uses a production or implicit root, silently repairs any artifact,
or proves only that a test expected an exception without verifying unchanged
bytes and visible terminal classification.

## Eighteen Required Hostile Cases

Every case must fail visibly and deterministically, leave prior valid bytes and
receipts unchanged, and be reproduced after restart where applicable.

| ID | Prohibited attempt | Required outcome |
|---|---|---|
| H01 | Future evidence inside prediction packet | Reject as future evidence at freeze; no packet committed. |
| H02 | Outcome timestamp before prediction cutoff | Reject as invalid chronology; no reveal committed. |
| H03 | Reveal attached to wrong prediction | Reject reference/fingerprint/identity mismatch; neither object changes. |
| H04 | Conflicting duplicate prediction | Reject immutable conflict; original prediction and receipt remain exact. |
| H05 | Conflicting duplicate reveal | Reject immutable conflict; original reveal and receipt remain exact. |
| H06 | Missing required strategy, code, or configuration identity | Reject incomplete identity; no artifact committed. |
| H07 | Prediction packet manually edited after freeze | Detect packet fingerprint or exact-byte receipt mismatch on read/restart and fail closed. |
| H08 | Receipt manually edited | Detect receipt identity/content/binding mismatch on read/restart and fail closed. |
| H09 | Truncated packet | Reject malformed/incomplete artifact and prevent silent continuation. |
| H10 | Partial/interrupted artifact | Never accept it as final; restart identifies or rejects the invalid residue deterministically. |
| H11 | Invalid hash | Reject fingerprint or receipt binding mismatch and prevent continuation. |
| H12 | Malformed timestamp | Reject without normalization or correction. |
| H13 | Duplicate logical identity with different contents | Reject immutable conflict even when an attacker supplies a different claimed packet ID or hash. |
| H14 | Path traversal | Reject before any path outside the root is opened or written. |
| H15 | Storage-root escape | Reject absolute-child, link/reparse, or resolved-containment escape; prove no outside file changes. |
| H16 | Restart with corrupted artifact already present | Root validation fails visibly before valid-looking continuation or new writes. |
| H17 | Attempted prediction mutation after reveal | Reject; P1 and O1 bytes, fingerprints, and receipts remain exact. |
| H18 | Unexpected outcome information supplied during freeze | Reject prohibited outcome/future field even if its timestamp is absent or disguised; no packet committed. |

## Acceptance Criteria

- [ ] **A01 - Canonical and authority preflight.** Git Steward proves all
  starting preconditions, exact base/branch ancestry, clean scope, current
  Roadmap reconciliation, and absence of `BLOCKED_CANONICAL_DRIFT`.
- [ ] **A02 - Reuse inventory before code.** All ten areas are evidence-backed
  and classified with one of the four permitted statuses. No duplicate owner or
  unresolved `BLOCKED_IDENTITY_COLLISION` remains.
- [ ] **A03 - Two contracts only.** `FrozenPredictionPacketV1` and
  `OutcomeRevealPacketV1` implement every required field, authority marker,
  missingness rule, chronology rule, fingerprint, logical key, and receipt
  binding above. Supporting receipt/index behavior does not become a third
  mutable evidence object.
- [ ] **A04 - Deterministic canonical identity.** Independent clean-process
  runs produce byte-identical canonical records, logical keys, fingerprints,
  paths, and receipts for identical inputs. Self-referential fields are excluded
  only as frozen above and are independently recomputed.
- [ ] **A05 - Prediction immutability.** First valid prediction succeeds;
  identical duplicate is idempotent; conflicting bytes under the same logical
  key fail closed; no overwrite/update/delete-through-API behavior exists.
- [ ] **A06 - Reveal immutability and reference.** First valid reveal succeeds;
  identical duplicate is idempotent; conflict fails closed; the reveal resolves
  the exact validated prediction reference and cannot write its path.
- [ ] **A07 - Freeze/reveal separation.** The complete P1 bytes and fingerprint
  remain unchanged after restart and after O1; no outcome or future evidence is
  accepted at freeze; later evidence resides only in the reveal where permitted.
- [ ] **A08 - Temporal integrity.** Explicit UTC contract times, not file times,
  prove prediction and reveal order. Missing, unsafe, future-aware, impossible,
  ambiguous, or wrong-reference chronology fails closed without correction.
- [ ] **A09 - Missingness integrity.** All seven states are implemented and
  tested. Null/zero/omission cannot silently substitute for a typed state, and
  reconstructed/synthetic values cannot masquerade as observed evidence.
- [ ] **A10 - Root isolation and atomic-safe storage.** Only a caller-supplied
  absolute disposable root is used; deterministic paths cannot traverse or
  escape; partial writes are never accepted; no production/global default or
  database dependency exists.
- [ ] **A11 - Tamper and restart validation.** Manual packet/receipt/hash edits,
  truncation, partial artifacts, orphan/conflict conditions, and corrupted-root
  restart all fail visibly before continuation. Valid restart returns exact P1.
- [ ] **A12 - Hostile matrix.** H01-H18 each have a focused deterministic test,
  exact terminal result, nonmutation assertion, and final pass evidence.
- [ ] **A13 - No-authority structural proof.** Static/import/call/dependency and
  scoped-diff evidence proves no ledger write/control path into scanners,
  candidate generation, scoring, ranking, TradePlan, risk, sizing, allocation,
  entries, exits, providers, brokers, accounts, orders, Paper, Shadow, services,
  schedulers, or GUI/WPF. Production does not import or depend on the ledger.
- [ ] **A14 - Protected-path freeze.** Every protected category reports exact
  `NO CHANGE`, with no production source/config/data/schema/runtime mutation.
- [ ] **A15 - Hard Chew verification.** Compile/import, focused unit, contract,
  serialization stability, identity, immutability, chronology, tamper, restart,
  path/root security, synthetic demonstration, bounded regression, secret,
  whitespace/conflict, and scoped-diff checks all pass. Failures are repaired
  narrowly and every required check is rerun.
- [ ] **A16 - Acceptance truths.** All 14 truth lines below are reported with
  exact required values and direct test/artifact evidence. `NOT_PROVEN` on any
  line blocks completion.
- [ ] **A17 - Independent review.** A reviewer who did not author the audited
  implementation reconstructs chronology, immutable identity, duplicate
  semantics, tamper behavior, root isolation, production non-authority, and
  protected-path scope from exact bytes and tests rather than accepting the
  author's summary. Discrepancies are repaired or remain open.
- [ ] **A18 - Complete review packet.** D01-D28 are all mapped to substantive
  evidence; branch/base/final identities, exact changed files, tests, risks,
  rollback, push/merge status, and smallest next recommendation are truthful.
- [ ] **A19 - Rollback isolation.** Demonstrated rollback requires only removal
  of branch-only unactivated code/test/docs and validated disposable synthetic
  roots. It requires no production repair, schema reversal, provider change,
  service action, config edit, evidence rewrite, or credential action.
- [ ] **A20 - Governance closeout.** Roadmap/Task Log/Branch Ledger are updated
  by their authorized owner from actual Git, test, review, and next-action
  evidence. Branch-only work is not called canonical or production complete.
  The general freeze and Monday checkpoint remain unchanged.

## Fourteen Acceptance Truths

The terminal review packet must report these exact lines. A line may be replaced
only by `NOT_PROVEN`; doing so prevents completion.

| ID | Required terminal truth | Minimum proof |
|---|---|---|
| T01 | `PREDICT_FIRST_FREEZE_REVEAL_LATER = TRUE` | P1 cutoff/evidence chronology, clean restart, later D/outcome availability, and O1 creation receipt. |
| T02 | `PREDICTION_MUTATED_AFTER_FREEZE = FALSE` | Pre/post-freeze exact bytes, fingerprint, and receipt equality. |
| T03 | `PREDICTION_MUTATED_AFTER_REVEAL = FALSE` | Pre/post-O1 exact P1 bytes, fingerprint, and receipt equality. |
| T04 | `CONFLICTING_DUPLICATE_ACCEPTED = FALSE` | H04, H05, and H13 rejection plus original-byte equality. |
| T05 | `FUTURE_EVIDENCE_ACCEPTED_AT_FREEZE = FALSE` | H01 and H18 deterministic rejection. |
| T06 | `INVALID_CHRONOLOGY_ACCEPTED = FALSE` | H02, H03, H12, and boundary/ambiguity cases reject. |
| T07 | `TAMPERING_UNDETECTED = FALSE` | H07-H11 and H16 fail restart/read validation. |
| T08 | `ROOT_ESCAPE_POSSIBLE = FALSE` | H14-H15 plus outside-root nonmutation evidence. |
| T09 | `PRODUCTION_WRITE_PATH = NONE` | Static dependency/capability scan and protected diff. |
| T10 | `PRODUCTION_DECISION_AUTHORITY = NONE` | Immutable contract marker and no consumer/control edge. |
| T11 | `EXECUTION_AUTHORITY = NONE` | Immutable contract marker and no broker/account/order capability or import. |
| T12 | `NEW_DATABASE_REQUIRED = FALSE` | Caller-rooted filesystem implementation and dependency/config diff. |
| T13 | `NEW_SERVICE_REQUIRED = FALSE` | No service/scheduler/daemon/background component or installed change. |
| T14 | `ROLLBACK_REQUIRES_PRODUCTION_REPAIR = FALSE` | Tested/documented isolated rollback and production-root nonmutation. |

## Deliverable-To-Evidence Map

The authoritative closeout report must contain a D01-D28 crosswalk pointing to
exact sections, files, tests, commands, and immutable proof identities. No item
may be `N/A`.

| ID | Directive deliverable | Acceptance evidence |
|---|---|---|
| D01 | Executive summary | Decision, scope, lifecycle proof, authority limits, trust conclusion, risks, and next action. |
| D02 | Branch/base/final commit identities | Git preflight/closeout with task branch, exact accepted base, final commit, master/origin identities, ancestry, and cleanliness. |
| D03 | Reuse inventory | All ten required owners, permitted classification, source/test evidence, conflict result, and no-duplication decision (A02). |
| D04 | Exact files changed | Name/status and diff-stat list separating implementation, tests, docs, and generated disposable evidence. |
| D05 | Contract/schema description | Exact two V1 contracts, field requiredness, missingness, authority, chronology, logical key, fingerprints, receipts, and validation. |
| D06 | Prediction packet example | Canonical redacted/synthetic P1 for `TEST1`, complete bytes/hash/receipt references, outcome unresolved, and no future evidence. |
| D07 | Reveal packet example | Canonical synthetic O1 referencing exact P1, later D/outcome evidence, semantic/version identity, hash, and receipt. |
| D08 | Fingerprint/identity rules | Domain separation, canonical projection, logical-key tuples, content/stored-byte hashes, receipt derivation, path derivation, and reuse-owner map. |
| D09 | Storage semantics | Caller absolute root, deterministic contained paths, exclusive atomic-safe write, no overwrite/default/database, and restart inventory. |
| D10 | Chronology rules | Explicit timestamp formulas, normalization, ambiguity handling, prediction/reveal validation, and file-time prohibition. |
| D11 | Missingness semantics | All seven states, value/reason requirements, reconstruction/synthetic restrictions, and no-substitution tests. |
| D12 | Immutability proof | First writes, pre/post byte/hash/receipt equality, absent mutation API, and H17. |
| D13 | Idempotency proof | Byte-identical duplicate P1/O1 returns original result without a new object or changed bytes. |
| D14 | Conflict rejection proof | H04, H05, and H13 exact failures and unchanged-original evidence. |
| D15 | Tamper proof | H07-H11 and corrupt-root validation results with exact failure classes. |
| D16 | Restart proof | Clean-process P1 validation, post-reveal P1 validation, and H16 fail-closed restart. |
| D17 | Root-isolation/path-security proof | H14-H15, containment checks, inert evidence locators, outside-root before/after inventory, and no global dependency. |
| D18 | Production non-authority proof | Dependency/import/call graph or equivalent scan, capability scan, immutable markers, and no production consumer/write/control path (A13). |
| D19 | Protected-path diff | Exact expected `NO CHANGE` table and Git diff against base (A14). |
| D20 | Focused tests | Named unit/contract/serialization/identity/immutability/chronology/tamper/restart/root and H01-H18 results. |
| D21 | Broader bounded tests | Relevant existing regression suites selected from reuse ownership and their exact counts/results. |
| D22 | Static/compile checks | Compile/import/static checks for all changed implementation/test paths and clean-process demonstration entrypoint. |
| D23 | Secret/conflict/whitespace checks | Scoped secret scan, merge-marker/conflict scan, Markdown checks, `git diff --check`, and any repository standard checks. |
| D24 | Independent second-eye disposition | Reviewer identity/role, frozen artifact hashes, independently reconstructed eight review domains, findings/resolutions, and final disposition (A17). |
| D25 | Rollback procedure | Exact isolated paths/actions, preconditions, validation, production nonmutation, and statement that destructive Git operations need separate authority. |
| D26 | Push/merge status | Actual commit/push/merge state; no activation/deployment implication and no branch-only `COMPLETE` claim. |
| D27 | Remaining risks | Real-data admission, evidence availability, identity/rights, filesystem threat residuals, crash semantics, platform variance, and scope limits. |
| D28 | Smallest next directive | Recommend at most separately bounded `ARGUS-CURRENT-EDGE-PROSPECTIVE-OBSERVER-001` only if all gates pass; explicitly state it is not authorized here. |

The authoritative implementation review entry point should be
`docs/argus-office/reports/architecture/ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001.md`.
The independent reviewer should own a separate identity-bound review artifact.
Implementation and test locations must be selected from the reuse inventory;
the Goal Charter does not pre-authorize a competing owner or production import.

## Protected Areas

This directive permits bounded inspection of protected areas to establish reuse
and non-authority. Expected modification status at closeout is exact:

| Protected category | Expected status |
|---|---|
| Strategy/scoring | `NO CHANGE` |
| Candidate generation/ranking/readiness | `NO CHANGE` |
| TradePlan | `NO CHANGE` |
| Risk/sizing/allocation | `NO CHANGE` |
| Entry/stop/target/exit policy | `NO CHANGE` |
| Brokerage/accounts/orders/execution | `NO CHANGE` |
| Market providers and live collection | `NO CHANGE` |
| Runtime production services/schedulers/installations | `NO CHANGE` |
| Paper | `NO CHANGE` |
| Shadow | `NO CHANGE` |
| GUI/WPF | `NO CHANGE` |
| Live configuration, secrets, and credentials | `NO CHANGE` |
| Production database/schema/migrations | `NO CHANGE` |
| Production and historical evidence artifacts | `NO CHANGE` |
| Replay identity/admission and historical capture | `NO CHANGE` |

The new isolated research module and its offline tests may implement only the
contract behaviors explicitly authorized above. Reuse of an existing pure
identity/fingerprint owner does not authorize modification of that owner or
make the ledger reachable from production. Any unexpected protected-path
mutation is a stop condition.

## Evidence And Hard Chew Requirements

### Artifact Evidence

- Freeze exact source state, dependency versions relevant to canonical bytes,
  contract versions, test fixtures, and caller-root identity.
- Preserve canonical P1 and O1 examples or sanitized byte manifests sufficient
  to reproduce all hashes without including secrets, licensed data, production
  evidence, or account information.
- Record packet, receipt, logical-key, stored-byte, and manifest SHA-256 values.
- Record before/after P1 bytes and hashes around restart and reveal.
- Record every H01-H18 terminal error/result and verify valid artifacts remain
  unchanged.
- Inventory files inside and immediately outside the disposable root before and
  after H14-H15 to prove containment.
- Record complete changed-file and dependency/capability surfaces against
  accepted base `848d20a6`.
- Keep generated proof roots disposable and isolated. Do not commit arbitrary
  generated data merely to make the packet appear complete.

### Required Checks

1. Compile/import all changed implementation and test modules in a clean
   process.
2. Run focused happy-path contract tests for first prediction write, exact
   duplicate, first reveal, exact duplicate, clean restart, and multi-horizon
   reveal identity if supported.
3. Run canonical serialization stability and deterministic identity tests
   across clean process restarts.
4. Run immutability, chronology, missingness, tamper, restart, and root/path
   tests, including every H01-H18 case.
5. Run the complete deterministic `TEST1` demonstration and independently
   recompute P1/O1/receipt hashes from stored bytes.
6. Run relevant broader bounded regressions selected from actual reused owners;
   state why each suite is sufficient and do not use a narrow green suite to
   excuse unrelated failures.
7. Scan the changed dependency/import/call surface for production reachability,
   provider/account/broker/order capabilities, default roots, environment/global
   dependencies, database/service/scheduler installation, and hidden mutation
   operations.
8. Run a protected-path diff, secret/credential scan, conflict-marker scan,
   whitespace check, `git diff --check`, and scoped self-review.
9. Repair findings narrowly, then rerun every affected check and the complete
   acceptance suite.
10. Freeze final source, test, packet, example, and review identities before the
    independent second eye.

A test is not accepted merely because it raises an exception. It must assert
the exact failure category, absence of a new committed artifact, and unchanged
bytes/fingerprints/receipts for all prior valid objects. Mocking a production
write path does not prove its absence; static structural proof is also required.

## Independent Second-Eye Gate

After implementation and author self-review, a reviewer who did not author the
audited implementation must independently:

1. reconstruct prediction chronology from P1's explicit evidence and cutoff
   fields without using file times;
2. reconstruct O1's later reveal chronology and exact P1 reference;
3. recompute logical keys, canonical fingerprints, stored-byte hashes, receipt
   identities, and deterministic paths from frozen bytes;
4. exercise identical and conflicting duplicate semantics for both object types;
5. tamper independently with packet, receipt, hash, truncated/partial artifact,
   and corrupt-root restart cases;
6. attempt traversal and resolved-root escape and verify outside-root
   nonmutation;
7. inspect imports, calls, dependencies, configuration, and diff to prove
   production non-authority; and
8. audit every protected category and T01-T14/D01-D28 crosswalk.

The reviewer must record exact artifact hashes, commands, test results, findings,
author responses, residual disagreement, and a final disposition. An author
summary, passing CI badge, or absence of comment is not independent approval.
Any changed implementation or proof byte after acceptance requires a scoped
identity refresh and reviewer adjudication.

## Rollback Contract

Rollback is possible because the slice is offline, unactivated, caller-rooted,
and has no production consumer:

1. stop all offline test/demo processes;
2. verify the exact absolute disposable roots are within the recorded synthetic
   test location and contain the expected manifest only;
3. remove only those disposable roots using a recoverable or explicitly bounded
   operation;
4. revert or remove only the branch-owned unactivated implementation, tests,
   fixtures, and documentation through a normal reviewable Git change; and
5. rerun protected-path and production-nonmutation checks.

Rollback must not require a database repair, migration rollback, service or
scheduler change, provider call, credential action, production configuration
edit, production evidence rewrite, market-path repair, broker/account/order
action, or runtime restart. Reset, rebase, branch deletion, force-push, or other
destructive/non-fast-forward Git action is not implied by this rollback and
requires separate Steven authority under repository policy.

## Stop Conditions

Stop and report `BLOCKED_NEEDS_STEVEN_REVIEW` rather than broadening scope when:

- deterministic immutable identity cannot be established;
- prediction-before-outcome chronology cannot be proven;
- an existing authoritative identity would have to be duplicated or two owners
  conflict (`BLOCKED_IDENTITY_COLLISION` where applicable);
- canonical materially drifted from the accepted architecture
  (`BLOCKED_CANONICAL_DRIFT` where applicable);
- a production code change, import hook, observer, runtime consumer, schema,
  database, provider, daemon, service, scheduler, or global dependency is needed;
- a live provider, broker, account, position, or order operation is needed;
- the work begins becoming the prospective observer, Time Machine, Catalyst
  Radar, replay engine, data lake, ML/model platform, agent system, or generalized
  research lab;
- rollback could affect production state or user data;
- a required timestamp, fingerprint, source identity, strategy/code/config
  identity, root boundary, or receipt cannot be proven without fabrication;
- any H01-H18 case is silently accepted, nondeterministic, or mutates prior
  valid evidence;
- any T01-T14 truth is `NOT_PROVEN`;
- a compile, test, tamper, restart, root-security, regression, secret, conflict,
  whitespace, scoped-diff, protected-path, or independent-review gate fails and
  cannot be repaired narrowly within the frozen outcome;
- unrelated files change unexpectedly, the task branch is wrong, or a
  destructive/non-fast-forward Git action becomes necessary; or
- accepted Strategy Science architecture, the production freeze, Monday
  checkpoint, or current prospective control would have to be weakened.

Do not solve a blocker through a convenient default, timestamp correction,
identity alias, fallback root, current-value substitution, mutable rewrite,
provider call, or new infrastructure.

## Completion Definition

This directive is done only when all of the following are simultaneously true:

1. Preconditions and the ten-item reuse inventory pass without collision or
   material drift.
2. The two V1 contracts and supporting receipt/storage behavior implement the
   frozen semantics without a production dependency.
3. The deterministic `TEST1` freeze/restart/reveal demonstration passes from a
   clean disposable root and reproduces exact identities and bytes.
4. H01-H18 all fail visibly and deterministically as required, with nonmutation
   proof.
5. T01-T14 all have their exact required values; none is `NOT_PROVEN`.
6. All compile, focused, contract, serialization, identity, immutability,
   chronology, missingness, tamper, restart, path/root, bounded regression,
   secret, conflict, whitespace, and diff checks pass after final repairs.
7. Protected paths and production behavior are byte/semantically unchanged as
   applicable; no observer, activation, provider, database, service, scheduler,
   model, GUI, Paper, Shadow, broker, account, or order capability exists.
8. D01-D28 are complete and traceable to exact files, tests, artifacts, hashes,
   and commands.
9. Independent second-eye review passes against the exact final bytes with no
   unresolved discrepancy.
10. Roadmap, Task Log, and Branch Ledger are truthfully reconciled by their
    authorized owner. Git status, final commit, push, and merge state are
    reported as observed. Branch-only work remains
    `IMPLEMENTED_PENDING_MERGE`, not canonical `COMPLETE`.
11. Rollback is isolated and requires no production repair.
12. The result is returned for Steven review before any prospective production
    observer, live capture, Time Machine work, or strategy influence begins.

Passing this completion definition grants no authority beyond the proved
offline research primitive.

## Expected Next Step — Not Authorized Here

If and only if this slice passes and Steven accepts it, the smallest plausible
next directive is separately bounded
`ARGUS-CURRENT-EDGE-PROSPECTIVE-OBSERVER-001`. Its possible purpose would be to
read existing production evidence without influencing production and freeze
genuine point-in-time research packets during real market operation.

That observer is not authorized here. Provider access, root selection,
installation, scheduling, runtime wiring, capture policy, production identity,
security review, and activation would each require explicit new framing and
proof. Historical replay and the Time Machine remain separately gated by data
admission and certification.

## Goal Steward Review

- [x] Mission and operator outcome are exact and research-only.
- [x] Overall authority and the narrower Goal Steward scope are separated.
- [x] No production observer or runtime path is authorized.
- [x] Both immutable object contracts, logical keys, fingerprints, receipts,
  chronology, missingness, and storage rules are frozen.
- [x] All 14 acceptance truths and all 18 hostile cases are explicitly mapped.
- [x] All 28 directive deliverables map to concrete acceptance evidence.
- [x] Protected paths, Hard Chew evidence, rollback, and stop conditions are
  explicit.
- [x] Independent review and Steven review precede any future observer.
- [x] Completion means proven rather than merely implemented.
