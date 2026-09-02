# ARGUS-SCIENCE-SEQUENTIAL-REPLAY-CONTRACT-001

## Status and authority

`TASK_STATUS = IMPLEMENTED_PENDING_MERGE_DESIGN_ONLY`

This document defines the Strategy Science Lab sequential anti-hindsight replay
contract. It is design only. It creates no replay engine, exporter, reader,
fixture package, provider client, service, scheduler, strategy authority, Paper
authority, Shadow authority, broker authority, or execution authority.

The keywords `MUST`, `MUST NOT`, `REQUIRED`, and `PROHIBITED` are normative.
Names written in capitals describe semantic requirements, not proposed wire
fields, method signatures, queue operations, cursor formats, or filesystem
layouts.

## Evidence basis and interpretation precedence

The authoritative source inventory is
`docs/research/ARGUS-SCIENCE-REPLAY-SEED-INVENTORY-001.md` at branch
`codex/ARGUS-SCIENCE-REPLAY-SEED-INVENTORY-001`, commit
`7658deeaffa1d08b23f0dc1cee53299c577cd00e`, Git blob
`e4a0091c83ef4dc91c0534d0982d441ffd6dee23`. It was consumed read-only and
was not imported into or modified by this task.

No existing corpus is Class A. Evidence interpretation uses this precedence:

1. Frozen prospective source bytes and their verified manifests.
2. Accepted independent adjudication of those bytes.
3. Accepted corrected forensic tooling that leaves the bytes unchanged.
4. Historical analyzer output, retained as history but not promoted over a
   later accepted correction.

For 001D specifically, governing truth is
`001D_FROZEN_PROSPECTIVE_BYTES + ACCEPTED_001E_FORENSIC_REANALYSIS +
ACCEPTED_INDEPENDENT_001E_ADJUDICATION`. The original zero-completed-bar and
zero-TradePlan analyzer conclusions remain immutable historical false
negatives. Replay MUST NOT alter the original bytes to make them agree with the
accepted interpretation.

## Dataset classes

| Class | Meaning | Permitted replay claim |
| --- | --- | --- |
| `A` | `TRUSTED_AND_EXACTLY_REPLAYABLE` | Eligible for Levels 0-3 after its seal independently passes every Class-A gate. |
| `B` | `TRUSTED_PROSPECTIVE_BUT_REPLAY_INPUT_INCOMPLETE` | Eligible only for supported, explicitly bounded Levels 0-2 assertions. Exact equivalence is prohibited. |
| `C` | `FORENSIC_NEGATIVE_FIXTURE_ONLY` | Eligible only to prove rejection, fail-closed behavior, or explicitly separated counterfactual mechanics. |
| `D` | `UNTRUSTED_NOT_ELIGIBLE_FOR_REPLAY_QUALIFICATION` | Not eligible for replay qualification or strategy statistics. |

Class is a property of a sealed evidence version, not a mutable label. A Class
B corpus MUST NOT later become Class A through reconstruction, external lookup,
filesystem-time inference, report prose, or today's policy knowledge.

## Reference-corpus contracts

### Minimal Class-B reference

Identity:
`2026-08-31_NATURAL_OPENING_ZERO_CANDIDATE_CAPTURE`

Permitted use:

- parser and fixture mechanics;
- virtual-clock mechanics over the facts whose availability is proven;
- fail-closed handling of absent evidence;
- deterministic reproduction of the persisted bounded zero-candidate result
  as an artifact result.

The corpus MUST NOT be described as a causal end-to-end market replay. It lacks
raw provider rows, producer-owned START/FINAL, a market stream, discovery-cycle
ordering, and cross-source chronology. Those facts MUST remain unavailable.

### Rich Class-B reference

Identity:
`ARGUS-CONTINUOUS-PRODUCER-001D-FORENSIC-CANARY-20260827-REGULAR-FBA8781`

The accepted bounded expectations are:

- 7 discovery cycles and 467 hot-universe transitions;
- 21 Schwab backfill attempts and 12 terminal-complete symbol records;
- 42 readiness attempts and 8 successful assessments;
- ready symbols `BMNR`, `CRM`, `NVDA`, and `MSTR`;
- 8 committed compositions and 17 Producer records;
- 259 completed-bar events, 259 exact canonical matches, 0 unmatched, 0
  premature, and 0 prospective-floor violations;
- 4 unique natural research TradePlans and 5 serialized occurrences;
- restart continuity with 0 duplicate Producer IDs after restore;
- atomic failure nonmutation and idempotent duplicate replay.

Levels 0-2 may reproduce those exact supported claims. They MUST preserve the
original analyzer false negatives as historical artifacts while using the
accepted 001E interpretation as the expected semantic result. They MUST NOT
claim complete session replay, exact live-to-replay equivalence, authoritative
instrument classification, separate outcome attachment, or Science receipt
chronology.

### Denominator Class-B reference

Identity:
`ARGUS-STAT-DATA-002D-PROSPECTIVE-CANARY-20260831-039D4E0`

The accepted bounded expectations are:

- 208 prospective attempts/observations;
- 52 duplicate membership attempts;
- 156 unique membership IDs;
- READY set `PBR`, `SLB`, `TSLA`;
- composition/no-plan set `CRWD`, `GME`, `MRNA`, `PBR`, `SLB`, `TSLA`;
- zero TradePlans and zero prospective-floor violations;
- unresolved authoritative instrument identity;
- passing checkpoint restore with an unchanged universe fingerprint.

Levels 0-2 may test population, activation-floor, duplicate-suppression,
membership/state-transition, and restart behavior. Exact instrument identity
MUST remain unknown. Missing session/export finality MUST remain unavailable.

### Negative Class-C reference

Identity: `2026-09-01_OBSERVER_OVERBINDING_CAPTURE`

Its immutable historical result is
`COMPLETE_FAIL_CLOSED_OBSERVER_POLICY_OVERBINDING`. Replay MUST retain:

`HISTORICAL_SYSTEM_DISPOSITION = COMPLETE_FAIL_CLOSED_OBSERVER_POLICY_OVERBINDING`

If a future experiment applies today's repaired policy, it MUST emit a
separate `CURRENT_POLICY_COUNTERFACTUAL_DISPOSITION`. That counterfactual MUST
bind its policy identity and analysis time, MUST NOT replace the historical
result, and MUST NOT be counted as prospective live evidence.

## Abstract evidence model

This model defines required semantics, not an exporter or reader API.

Every replay-visible fact MUST be bound to:

- exact source bytes or an exact source-byte hash;
- source owner and source-interface identity;
- source event identity and, where applicable, instrument identity;
- a provenance-supported effective availability instant;
- its source stream and authoritative source ordering;
- all predecessor/dependency identities needed to interpret it;
- authority and execution-authority classification;
- schema, contract, configuration, and runtime identities needed for meaning.

If any required binding is absent, contradictory, non-unique, or not
verifiable, the fact is `UNKNOWN_OR_UNPROVEN`, not known.

## Virtual market clock contract

Let `T` be the virtual market time. `T` MUST be monotonic and MUST never move
backward within a replay run.

A fact may become visible at `T` only when all of the following are proven:

1. Its effective known-at instant is at or before `T`.
2. Every required predecessor and dependency is already known.
3. Its source sequence and previous-envelope binding validate where required.
4. Required cross-source ordering relative to already exposed facts is proven.
5. Its bytes, identity, schema, and authority pass the same semantic ingress
   validation used for live Science input.

The reveal predicate is therefore:

```text
REVEAL(fact, T) =
    AVAILABILITY_PROVEN(fact)
    AND EFFECTIVE_KNOWN_AT(fact) <= T
    AND DEPENDENCIES_KNOWN(fact, T)
    AND SOURCE_ORDER_VALID(fact)
    AND CROSS_SOURCE_ORDER_VALID_WHERE_REQUIRED(fact)
    AND SAME_INGRESS_VALIDATION_PASSED(fact)
```

An absent or ambiguous term makes `REVEAL` false. It does not permit a guessed
time or order.

The clock MAY advance faster than wall time, including replaying a six-hour
session in seconds. Acceleration changes only the wait between virtual events.
It MUST NOT change:

- virtual event order;
- known-at order;
- decision order;
- source/dependency order;
- decision inputs or deterministic outputs.

For any supported acceleration factors `a` and `b`:

```text
SEMANTIC_TRACE(corpus, a) = SEMANTIC_TRACE(corpus, b)
DETERMINISTIC_OUTPUT_HASH(corpus, a) = DETERMINISTIC_OUTPUT_HASH(corpus, b)
```

Filesystem timestamps, replay-machine wall time, current market data,
retrospective external lookup, later outcomes, report prose, and current policy
knowledge have zero availability authority.

## Knowledge frontier

At each virtual instant `T`, the laboratory MUST maintain three disjoint sets:

```text
KNOWN_FACTS_AT_T
WITHHELD_FUTURE_FACTS_AT_T
UNKNOWN_OR_UNPROVEN_FACTS_AT_T
```

Their meanings are:

- `KNOWN`: provenance proves availability at or before `T` and all validation
  dependencies pass.
- `WITHHELD`: valid evidence exists but its proven availability is after `T`.
- `UNKNOWN`: evidence is missing, invalid, contradictory, lacks authoritative
  availability/order, or is outside the sealed corpus.

The externally reportable availability classifications are exact:

```text
WITHHELD_FUTURE_FACT => NOT_YET_AVAILABLE
UNKNOWN_OR_UNPROVEN_FACT => INSUFFICIENT_REPLAY_EVIDENCE
```

`NOT_YET_AVAILABLE` MUST NOT be used for a fact whose future availability is
itself unproven; that case remains `INSUFFICIENT_REPLAY_EVIDENCE`.

The sets MUST be pairwise disjoint. A fact may move from WITHHELD to KNOWN only
when `T` reaches its proven availability and all dependencies pass. UNKNOWN may
move to KNOWN only when already-sealed evidence proves the missing requirement;
reconstruction or live lookup is prohibited.

For every decision, the laboratory MUST emit or retain a machine-verifiable
frontier receipt binding virtual time, known identities, withheld identities,
unknown requirements, and the exact decision-input identities. The invariant
is:

```text
DECISION_INPUT_SET ⊆ KNOWN_FACTS_AT_T
DECISION_INPUT_SET ∩ WITHHELD_FUTURE_FACTS_AT_T = ∅
DECISION_INPUT_SET ∩ UNKNOWN_OR_UNPROVEN_FACTS_AT_T = ∅
FUTURE_FACT_ACCESS = ZERO
```

Any violation is a replay failure, not a warning.

## Missing-evidence fail-closed policy

Replay MUST NOT synthesize START, FINAL, session boundaries, producer known-at,
provider finality, cross-source order, source-envelope chains, predecessor
hashes, instrument identity, Science receipt chronology, plan identity, market
facts, outcome chronology, or gap closure.

| Missing or invalid requirement | Required result |
| --- | --- |
| Parser/schema/hash/identity requirement | Reject the affected object; Level 0 fails if the corpus cannot be safely bounded. |
| Known-at or dependency proof | Keep the fact UNKNOWN and return `INSUFFICIENT_REPLAY_EVIDENCE` for any dependent assertion. |
| Source sequence or predecessor binding | Stop the affected stream before the gap; never skip or reorder around it. |
| Cross-source ordering required by a decision | Do not execute that decision assertion. |
| START or session boundary | No exact session claim and no Level-3 admission. |
| FINAL, stream head, count, gap, or conflict proof | No exact completion/finality claim and no Level-3 admission. |
| Exact instrument identity where required | Keep eligibility/authority dependent on that identity unavailable or blocked. |
| Plan identity/bytes or required market fact | Do not synthesize a plan or market observation. |
| Science custody/eligibility binding | Do not admit the decision to Science equivalence. |
| Outcome availability/binding | Keep outcome withheld or unknown; never attach it to discovery evidence. |

The terminal bounded status for an unsupported assertion is:

`REPLAY_STATUS = INSUFFICIENT_REPLAY_EVIDENCE`

A Class-B corpus may pass supported mechanics while carrying that status for
unsupported claims. It MUST always have
`EXACT_REPLAY_EQUIVALENCE = NOT_ELIGIBLE`, never `PASS`.

## Replay qualification levels

### `LEVEL_0 = PARSER_AND_FIXTURE_MECHANICS`

Proves exact corpus loading, bounded schema validation, hash validation, and
fail-closed rejection of malformed, unknown, duplicate-conflicting, or
out-of-scope evidence. It makes no chronology or decision-equivalence claim.

### `LEVEL_1 = CHRONOLOGY_AND_FUTURE_FACT_ISOLATION`

Requires Level 0. Proves monotonic virtual time, knowledge-frontier accounting,
future-fact inaccessibility, dependency/order enforcement, and identical
semantic traces across acceleration factors.

### `LEVEL_2 = CLASS_B_BOUNDED_REPRODUCTION`

Requires Levels 0-1. Reproduces only claims explicitly supported by the sealed
Class-B corpus. Every unsupported claim remains unavailable, every limitation
is emitted, and no fact is invented. Level 2 MUST report the exact assertion
set attempted, passed, failed, and unavailable.

### `LEVEL_3 = CLASS_A_LIVE_TO_REPLAY_EXACT_EQUIVALENCE`

Requires a future corpus sealed as Class A by the capture-time gate. It proves
anti-hindsight replay in a fresh provider-disconnected laboratory and exact
equality of all deterministic ingress, decisions, outputs, custody bindings,
eligibility bindings, and outcome bindings.

### `LEVEL_4 = SEALED_HISTORICAL_COUNTERFACTUAL_CAMPAIGNS`

Requires the replay implementation and same semantic ingress to have passed
Level 3 first. It permits accelerated historical experiments only from sealed,
admitted evidence. Every result MUST be labeled `HISTORICAL_SEALED_REPLAY` and
bind the counterfactual policy/configuration separately from historical truth.

Continuous Paper qualification MUST NOT rely only on Levels 0-2. Level 4 does
not transform historical evidence into prospective evidence.

## Deterministic equivalence contract

For a future Class-A session, exact equality is required wherever the live
contract is deterministic. The comparison set MUST include:

- exact replay-ingress bytes, source event IDs, source hashes, source-envelope
  hashes, sequence positions, and predecessor hashes;
- discovery-cycle identity, candidate membership, opportunity/setup identity,
  eligibility, READY/BLOCKED/REJECTED/MISSED, and composition/no-plan;
- deterministic features and scores with their configuration identities;
- TradePlan identity and exact bytes, including entry, stop, T1, and T2 when
  contractually present;
- lifecycle transition identities and failure classifications;
- Science custody, eligibility, and decision bindings;
- separate outcome identities, bytes, availability, and decision bindings.

Comparison MUST prefer exact byte identity or contract-defined identity hashes.
It MUST NOT reserialize source bytes merely to make them compare equal. The
future deterministic-output hash contract MUST define a canonical ordered
projection and domain separation before capture. Its required invariant is:

```text
LIVE_DETERMINISTIC_OUTPUT_HASH = REPLAY_DETERMINISTIC_OUTPUT_HASH
```

One missing, extra, reordered, or byte-different deterministic object fails
equivalence unless the difference was preregistered as nondeterministic.

Every nondeterministic field MUST have a preregistered ledger entry containing:

```text
NONDETERMINISTIC_FIELD
WHY_NONDETERMINISTIC
ALLOWED_COMPARISON
BOUND
```

The bound MUST be machine-testable and MUST have zero effect on semantic
identity, ordering, known-at, decision input, decision output, authority, or
statistics. Replay-machine wall time and local path are examples that may be
excluded if preregistered. Random behavior is prohibited unless the live seed,
algorithm, version, and draw order were captured and replayed exactly. There is
no unexplained fuzzy equality.

## Golden prospective session contract

`GOLDEN_PROSPECTIVE_SESSION_001` is the first intended Class-A corpus. Its
contract MUST be approved before capture and MUST freeze:

- semantic ingress contract and version;
- runtime/configuration/policy identities;
- market date, timezone, session kind and boundaries;
- expected source owners, streams, ordering relations, and identity rules;
- deterministic-output projection and nondeterminism ledger;
- gap/conflict policy, restart policy, and outcome-followup policy;
- authority restrictions, including no implied execution authority.

### START

Before the first session event, the producer MUST create and seal an immutable
START that binds market date/timezone, session boundaries, source namespace and
root identity, runtime activation, configurations, contracts, expected streams,
outcome policy, and prior state required for restart. A late or reconstructed
START fails Class-A admission.

### During capture

The capture MUST preserve exact raw exported envelope bytes; source IDs and
hashes; producer known-at evidence; exact instrument identity where required;
discovery boundaries; duplicate suppressions; candidate and lifecycle states;
READY/BLOCKED/REJECTED/MISSED; composition/no-plan; exact TradePlan bytes and
levels; provider health; required market facts; and restart/recovery evidence.

Every stream MUST begin at its declared first sequence and maintain a complete
previous-raw-envelope SHA-256 chain. Cross-source ordering semantics MUST be
producer-owned and sufficient to reproduce every decision dependency. Science
receipt time MUST remain distinct from source effective-known-at and emitted
time. Custody, eligibility, and decision bindings MUST be immutable and
verifiable.

### FINAL

After the session event boundary, the producer MUST create and seal an
immutable FINAL binding close reason/time, exact per-type counts, stream heads,
pending records, explicit gaps/conflicts, restart state, and the outcome-followup
policy. FINAL MUST reconcile START and every declared stream. A late or
reconstructed FINAL fails Class-A admission.

### Outcomes

Later outcomes MUST be separate append-only attachments. Each attachment MUST
bind its decision/observation, instrument, series, horizon, exact market bytes,
and proven availability. It MUST NOT alter discovery-time bytes, known-at,
classification, plan, eligibility, or decision facts.

### Terminal sealing

The sealed root MUST contain a terminal inventory of every permitted path,
length, exact SHA-256, semantic role, and ownership classification, plus an
immutable root inventory hash. Unexpected, missing, mutable, or ambiguous files
fail sealing. No missing field may be filled after capture by inference.

## Class-A capture-time gate

The sealing validator MUST establish every gate below from bytes that existed
in the capture/export/custody process at the required time:

```text
START_SEALED = YES
FINAL_SEALED = YES

RAW_EXPORT_ENVELOPES_PRESERVED = YES
SOURCE_IDS_COMPLETE = YES
SOURCE_HASHES_COMPLETE = YES
KNOWN_AT_COMPLETE = YES

PER_STREAM_SEQUENCE_COMPLETE = YES
PREVIOUS_RAW_ENVELOPE_CHAIN_COMPLETE = YES
CROSS_SOURCE_ORDER_PROVEN = YES

INSTRUMENT_IDENTITY_COMPLETE_WHERE_REQUIRED = YES

SCIENCE_RECEIPT_CHRONOLOGY_COMPLETE = YES
SCIENCE_ELIGIBILITY_COMPLETE = YES

OUTCOME_ATTACHMENTS_SEPARATE = YES
OUTCOME_SEPARATION_PROVEN = YES
FUTURE_FACTS_WITHHOLDABLE = YES

UNEXPLAINED_GAPS = 0
UNRESOLVED_CONFLICTS = 0

INVENTED_FACTS_REQUIRED = NO

TERMINAL_INVENTORY_COMPLETE = YES
ROOT_INVENTORY_HASH_VERIFIED = YES
```

The validator MUST fail on an unknown value; absence is not equivalent to
`YES` or zero. Only an all-pass result may emit `DATASET_CLASS = A`. The gate
MUST preserve a receipt binding the exact sealed root, validator version,
contract versions, every check result, and the resulting class. That receipt
may describe the sealed corpus but MUST NOT rewrite it.

Class is monotonic with respect to missing capture-time proof:

```text
MISSING_CAPTURE_TIME_PROOF => CLASS_A_FOREVER_INELIGIBLE_FOR_THAT_CORPUS_VERSION
```

Creating a later, separately captured and fully proven corpus is allowed;
upgrading the incomplete version is not.

## Level-3 live → seal → replay experiment

The future experiment MUST:

1. Preregister the Golden Session contract, deterministic projection, and
   nondeterminism ledger.
2. Run the normal prospective session through the canonical live ingress.
3. Preserve exact live inputs, custody/eligibility/decision outputs, failures,
   and later separate outcomes.
4. Close the session and seal the corpus through the Class-A gate.
5. Create a fresh laboratory with no prior run state.
6. Prove live provider access is unavailable to replay.
7. Feed only sealed evidence through the same semantic ingress contract.
8. Advance the virtual clock sequentially and enforce the knowledge frontier.
9. Withhold later facts and outcomes until their proven availability.
10. Compare every deterministic input/output identity and hash.
11. Emit complete mismatch, unavailable, nondeterminism, and frontier receipts.

The final classifications are:

```text
LIVE_CAPTURE_VALID = YES / NO
CLASS_A_SEAL_VALID = YES / NO
REPLAY_ANTI_HINDSIGHT = PASS / FAIL
DETERMINISTIC_OUTPUT_EQUIVALENCE = PASS / FAIL
REPLAY_EQUIVALENCE = PASS / FAIL
```

`REPLAY_EQUIVALENCE = PASS` is permitted only when the first two values are
`YES` and both replay checks are `PASS`. A missing prerequisite or a run not
performed yields `FAIL`, not presumed success.

## Same semantic ingress requirement

Live capture and replay may differ only at the physical source:

```text
LIVE PHYSICAL SOURCE ----\
                          > SAME SEMANTIC INGRESS
SEALED REPLAY SOURCE ----/        |
                                  v
                         CUSTODY + CHRONOLOGY
                                  |
                                  v
                        ELIGIBILITY + DECISIONS
                                  |
                                  v
                         OUTPUTS + OUTCOMES
```

Replay MUST use the same parsing, source hashing, custody, chronology,
eligibility authority, decision binding, and fail-closed validation as live
Science. A sealed source may replace the live physical source; it may not
replace or bypass the semantic ingress contract.

## Exporter / reader boundary

`FINAL_REPLAY_SOURCE_API =
BLOCKED_PENDING_ACCEPTED_CONTINUOUS_EXPORTER_AND_SCIENCE_SOURCE_READER`

This design requires the eventual accepted boundary to provide, abstractly:

- exact immutable source bytes and owner identities;
- authoritative known-at and ordering semantics;
- complete stream sequence and previous-byte linkage;
- START/FINAL session proof and terminal inventory;
- gap/conflict/restart/finality semantics;
- separate outcome attachments;
- Science receipt, custody, and eligibility bindings;
- a provider-disconnected sealed-source mode using the same semantics.

This document intentionally defines no final field names, reader methods,
queue behavior, cursor implementation, or publication layout. Those remain
blocked until the Continuous exporter and Science source reader are accepted
and canonically integrated.

## Historical campaign policy

Every Level-4 observation, decision, plan, and outcome MUST carry evidence
class `HISTORICAL_SEALED_REPLAY`. It MUST NOT be labeled or counted as
`PROSPECTIVE_LIVE` or `LIVE_REPLAY_REPRODUCTION`.

Strategy statistics MUST preserve separate counts and denominators for at
least:

- prospective live;
- live-to-replay reproduction;
- historical sealed replay;
- Class-B bounded mechanics;
- Class-C negative/counterfactual fixtures.

A replay trade MUST NOT inflate the count of prospective trades. Historical
system disposition and current-policy counterfactual disposition MUST remain
separate records with separate policy identities.

## Future conformance suite

No tests are implemented by this design task. A future implementation MUST at
minimum prove:

1. Malformed bytes, hashes, identities, schemas, and paths fail Level 0.
2. A future-dated fact cannot be read through any public or internal decision
   interface before virtual time reaches its proven availability.
3. Unknown known-at, missing dependencies, sequence gaps, predecessor mismatch,
   and ambiguous cross-source order fail closed.
4. Outcomes remain physically and semantically inaccessible until their
   attachment availability.
5. Multiple acceleration factors produce identical semantic traces and hashes.
6. Minimal Opening reproduces only its supported zero-candidate artifact result
   and reports every missing causal input.
7. 002D reproduces the accepted attempt, duplicate, membership, population,
   READY, no-plan, zero-plan, floor, and restart facts without inventing
   instrument identity.
8. 001D reproduces the accepted 001E counts, completed-bar matches, natural
   plans, restart, atomicity, and duplicate behavior while preserving the
   historical false-negative analyzer output.
9. September 1 retains the historical fail-closed disposition under historical
   policy; any current-policy result is separately labeled counterfactual.
10. Every Class-B corpus is mechanically unable to emit exact equivalence PASS.
11. A Golden Session with any missing Class-A gate is rejected permanently for
    that corpus version.
12. A fully sealed Class-A session passes provider-disconnected Level 3 only
    when deterministic live and replay hashes match exactly.

## Protected-boundary disposition

This task changes documentation only. It does not change canonical, Continuous
Producer/exporter, Science recorder/runtime/source reader, Opening, Observer,
GUI, providers/authentication, services, schedulers, Paper, Shadow,
broker/account, positions, orders, or execution authority. It creates no replay
package and requires no second-eye ZIP.

## Required return

```text
TASK_STATUS = IMPLEMENTED_PENDING_MERGE_DESIGN_ONLY

REPLAY_DATASET_CLASSES_DEFINED = YES
VIRTUAL_CLOCK_CONTRACT_DEFINED = YES
KNOWLEDGE_FRONTIER_DEFINED = YES
FUTURE_FACT_ISOLATION_DEFINED = YES

MISSING_EVIDENCE_FAIL_CLOSED_DEFINED = YES

MINIMAL_CLASS_B_SCOPE_DEFINED = YES
RICH_CLASS_B_SCOPE_DEFINED = YES
DENOMINATOR_CLASS_B_SCOPE_DEFINED = YES
CLASS_C_NEGATIVE_SCOPE_DEFINED = YES

001D_FALSE_NEGATIVE_HISTORY_PRESERVED = YES
001E_ACCEPTED_INTERPRETATION_USED = YES

REPLAY_QUALIFICATION_LEVELS_DEFINED = YES
DETERMINISTIC_EQUIVALENCE_CONTRACT_DEFINED = YES

GOLDEN_SESSION_CONTRACT_DEFINED = YES
CLASS_A_CAPTURE_GATE_DEFINED = YES
LIVE_TO_REPLAY_LEVEL3_CONTRACT_DEFINED = YES

SAME_SEMANTIC_INGRESS_REQUIRED = YES

FINAL_READER_API_INVENTED = NO
REPLAY_IMPLEMENTATION_STARTED = NO

BLOCKED_PENDING_EXPORTER_READER_INTERFACE = YES

CANONICAL_CHANGED = NO
CONTINUOUS_CHANGED = NO
SCIENCE_RUNTIME_CHANGED = NO
OPENING_CHANGED = NO
GUI_CHANGED = NO

PROVIDER_CONTACT_OCCURRED = NO
SERVICE_CHANGED = NO
SCHEDULER_CHANGED = NO
EXECUTION_AUTHORITY_CHANGED = NO

SECOND_EYE_ZIP_REQUIRED = NO

READY_FOR_REPLAY_IMPLEMENTATION = NO
READY_TO_CAPTURE_GOLDEN_SESSION = NO
```

Both readiness values remain `NO` until the same accepted Continuous exporter
and Science source-reader ingress semantics are qualified and canonically
integrated.

## Agent report

- Branch: `codex/ARGUS-SCIENCE-SEQUENTIAL-REPLAY-CONTRACT-001` from canonical
  `ee698d12be8baeef22ddb22b9d797116c95e38e4`.
- Scope: design-only Science replay and Golden Session contract.
- Files changed: this contract only.
- Tests/checks: source-inventory identity, branch/canonical admission,
  requirement trace, documentation lint, secret scan, protected-path review,
  and post-commit remote-ref verification.
- Evidence for changed behavior: none; behavior is unchanged.
- Protected areas reviewed: all protected runtime, provider, service,
  scheduler, trading, and cross-lane boundaries remained outside mutation
  scope.
- Push/merge status: task branch only; no merge.
- Risks: future work could accidentally treat Class-B success as equivalence,
  bypass the common ingress, infer missing facts, or commingle historical and
  prospective statistics. This contract explicitly prohibits each failure.
- Manual QA: none; nonvisual documentation.
- Open questions: final exporter/reader API and publication mechanics remain
  intentionally blocked.
- Recommendation: accept the contract before designing implementation details;
  then finish and qualify the owner exporter and Science reader before any
  replay implementation or Golden Session capture.
