# Sep09 Automation Recovery Candidate

Branch-only implementation from canonical `2bceeeadd06f5ed85943942f1c0f81b7094620f7`.
The accepted Engine `2ec3445` has identical Automation source, so its unrelated
changes are deliberately excluded. Canonical and installed state are not changed.

## Contract

Automation receipts are execution-suppression authority, not disposable cache.
COMPLETED additionally admits dependencies; RUNNING is intent, not proof of a
successful child launch. Host state is cached; heartbeat, service instance and
human-readable reason are diagnostic. Loaded-module hashes describe runtime
identity, not history. The external authority report enumerates every legacy field.

New state metadata: `state_version` is a monotonic generation identity;
`recovery_floor_at` permanently quarantines ambiguous schedules at/before that
instant. No completion receipt is invented for an unknown identity. New receipts
bind the job definition (except the independent enable/disable switch); legacy
receipts remain explicitly without that stronger definition hash.

The storage protocol validates full serialized bytes, writes exclusive temporary
files, flushes and fsyncs, validates readback, retains prior admitted state, writes
immutable RUNNING/terminal claims, retains the new generation, promotes the
checksummed admission head, and finally replaces current state atomically.
Windows file fsync is supported; directory fsync is used only on platforms that
support ordinary directory descriptors. This is not a claim of power-failure
immunity for defective storage hardware or a malicious administrator.

Five good generations are retained after successful promotion. Job claims are
not heartbeat backups: historical execution authority is never pruned with the
checkpoint ring. The admission head binds required claims so missing later
history cannot silently become an older parseable state. Corrupt generations are
retired only after exact-byte custody and successful promotion. Missing/invalid
admission head or admitted claims fail closed.

Recovery reconciles all surviving admitted terminal/RUNNING evidence, not only
the newest JSON. Unknown intervals set a prospective floor. Competing ticks hold
the same OS-backed path lease through child execution, and persistence uses a
current-byte compare-and-swap under that lease. Existing Paper interrupted-intent
behavior is regression-tested, not activated or broadened.

The read-only guardian reuses the existing manifest parser but never constructs
a supervisor, invokes an executor, or constructs a provider/broker client.
Its status includes independent parse/schema/retention checks, exact Sep09
Opening schedule, canonical/config identity, heartbeat age, and authority gates.
It never repairs, saves state, starts a service, or invokes capture.

## Incident And Scope Limits

Today's exact 36,072 zero bytes remain at production with SHA-256
`BCB2B49F3B8919347B47671CBD6740710640E913212D0F66F20438872278FF8D`.
`RECOVERY_SOURCE = NONE_ADMISSIBLE` is unchanged. Both old and new supervisors
fail before job evaluation on this source alone. New code additionally preserves
exact corrupt bytes and reports the explicit cause. No production recovery was
performed.

`prepare_quarantined_epoch` can prepare a new disposable proposal preserving
opaque legacy bytes and UNKNOWN history, with zero fabricated receipts. It is
not automatic recovery and carries no production-adoption authority. Integration
must explicitly accept that prospective-only boundary and bind its exact source,
manifest, cutoff, single-owner/quiescence, release and rollback evidence.

The actual Automation manifest/parser has no Continuous job kind. Continuous is
owned by the separately installed Runtime/Writer services. Storage tests using a
Continuous-shaped receipt are domain-neutral history tests, NOT live Continuous
scheduling/recovery proof. The literal `CONTINUOUS_JOB_PRESENT` guardian gate
remains RED until the task owner resolves this criterion, without adding a job.

Opening fallback is `MANUAL_REVIEW_REQUIRED`: downstream write-once artifacts
do not prove no concurrent provider work or no previous completed invocation.
No fallback is launched or scheduled. The exact path and missing gates are in
the external fallback note.

Changing the supervisor affects the approved Opening execution identity. This
candidate is not compatible by assertion with the currently approved release;
Integration must separately qualify/promote the exact compatible identity before
restarting production. Candidate adoption is not tonight's Engine authority.

## Qualification And Handoff

The task-owned external evidence root contains the exact old/new failure replay,
18-case corruption/fault matrix, restart/soak and Sep09 schedule simulations,
approved-environment focused/full results, read-only production guardian output,
source inventories, independent Astra review, and adoption/fallback documents.
Final status is determined from those terminal results, never this source note.
Shared Roadmap/branch ledger/task log remain Integration-owned and unmodified.

No merge, deployment, provider contact, service restart, schedule change, strategy
change, or Paper/live authority is authorized by this candidate or an Astra review.
