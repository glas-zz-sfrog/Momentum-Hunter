# ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001A Authority Model

## Before: rejected chronology

```text
T0 producer seals immutable V2 discovery bytes
 │
 ▼
T1 Science commits candidate-observation payload + receipt
 │  observation.recorder_capture_time = T1
 │
 ├── process crashes; no eligibility exists
 │
 ▼
T2 Science recovers and first constructs eligibility
 │
 └── rejected record claims:
       science_evaluated_at = T1                 WRONG NAME/MEANING
       eligibility.recorder_capture_time = T1   WRONG PHYSICAL CHRONOLOGY
```

The semantic receipt clock is valid, but it was reused as though it were the
actual later eligibility-evaluation and record-creation clock.

## After: truthful two-layer chronology

```text
T0 producer seals immutable V2 discovery bytes
 │
 ▼
T1 Science observation receipt becomes effective
 │  science_receipt_effective_at = T1
 │  frozen producer bytes + observation payload/receipt + START policy
 │  define the prospective semantic eligibility inputs
 │
 ├── process may crash; no later market state is admitted
 │
 ▼
T2 Science first constructs eligibility during recovery
 │  science_evaluated_at = T2
 │  eligibility.recorder_capture_time = T2
 │
 ▼
later outcome attaches by exact decision/observation/series/horizon identity
```

For a clean path, T1 and T2 may be equal. If an eligibility payload was already
staged before interruption, its exact staged `science_evaluated_at` and outer
record capture time are reused so restart cannot create conflicting sealed
bytes.

## Hash domains

The three authority hashes remain separate:

1. Producer content hash covers immutable producer envelope bytes. It is
   independent of all Science clocks.
2. Science custody receipt hash covers the exact accepted observation payload,
   receipt-chain predecessor, record identity, and receipt metadata.
3. Science semantic eligibility hash covers producer identity/content,
   producer known-at, exact observation payload hash, exact observation custody
   receipt hash, instrument and first-observation identity, START-frozen policy,
   and `science_receipt_effective_at`.

`science_evaluated_at` is deliberately excluded from the semantic eligibility
hash. Physical recovery latency cannot redefine which prospective sample was
eligible. The full eligibility record bytes and its Science custody receipt
still bind `science_evaluated_at`, so physical chronology remains immutable and
tamper-evident without becoming a selection input.

Changing the receipt-effective time changes the semantic eligibility hash.
Changing only physical materialization time does not. Validation additionally
requires:

```text
producer_effective_known_at <= science_receipt_effective_at
science_receipt_effective_at <= science_evaluated_at
science_evaluated_at == eligibility.recorder_capture_time
```

## Anti-hindsight boundary

Recovery at T2 reads only the already preserved producer envelope, exact
observation payload and receipt, the producer known-at value, and the
START-frozen outcome policy. It does not query or admit later bars, returns,
outcomes, decisions, revisions, providers, or current market state. T2 is
physical chronology evidence only.

`RECOVERY_TIME_CHANGES_AVAILABLE_MARKET_FACTS = NO`

## Record-family declaration

`RECORD_FAMILIES` is the exported declaration of persisted normalized record
families. Because V2 persists `science-eligibility`, that family is now listed
explicitly. This is declaration cleanup, not a new record type or V3 contract.
