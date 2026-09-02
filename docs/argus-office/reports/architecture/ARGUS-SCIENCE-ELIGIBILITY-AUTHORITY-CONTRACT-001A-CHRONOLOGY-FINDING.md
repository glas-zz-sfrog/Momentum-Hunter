# ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001A Chronology Finding

## Rejected candidate

- Rejected review head: `663fad740df56e0ff4bc2f8308a508d4b107b589`
- Disposition: `FAIL_NARROW_REPAIR_REQUIRED`
- Rejected packet SHA-256:
  `ED2808C401423D9EC09C2A0D3D846190F0F92AD3DBAAB3AAED61739968F72B87`

The rejected head and packet remain immutable review evidence. This descendant
does not amend, rebase, rewrite, merge, or reclassify them.

## Exact mechanical reproduction

`reproduce_rejected_chronology.py` interrupts the rejected candidate by wrapping
`_science_eligibility_record` itself. The interruption therefore occurs only
after the candidate-observation payload and receipt are readable and before any
Science eligibility payload exists. It does not use the generic
`after_receipt` injection, which fires on the earlier discovery-cycle record.

The deterministic proof records:

```text
T1 = 2026-09-01T14:00:00Z
candidate-observation payload committed = YES
candidate-observation receipt committed = YES
science-eligibility payload exists = NO

T2 = 2026-09-01T15:00:00Z
first eligibility construction occurs during recovery = YES
rejected science_evaluated_at = T1
rejected eligibility recorder_capture_time = T1
```

The rejected implementation obtains both eligibility clocks from
`observation.recorder_capture_time`. That value is the frozen Science
receipt-effective clock, not the later physical eligibility derivation clock.
The result is internally hash-valid but historically false about when the
eligibility record was first evaluated and materialized.

The external `rejected-chronology-finding.json` is Git-bound to the rejected
head and reports `PASS` only when that exact defect is reproduced while raw
producer bytes remain unchanged and final custody verification still succeeds.

## Narrow repair criterion

The accepted V2 direction remains:

```text
producer-sealed facts
        ↓
Science observation receipt-effective state
        ↓
Science eligibility semantic derivation
        ↓
later outcome linkage
```

Only the chronology labels and persistence behavior at the observation-receipt
to eligibility gap are repaired. No producer field, market input, outcome
input, product decision, runtime, provider, service, scheduler, or execution
authority is added.
