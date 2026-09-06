# Modern Recovery F3/F4 Repair

Status: IMPLEMENTED_PENDING_MERGE / QUALIFICATION_AND_SECOND_EYE_REQUIRED.
Branch: codex/ARGUS-ENGINE-MODERN-OPERATIONAL-RECOVERY-F3-F4-REPAIR-001.
Rejected parent: 8904b3ffd8acc85ca72c14fdfb17b2cbc284da06.
Protected canonical: 2bceeeadd06f5ed85943942f1c0f81b7094620f7.

## Authorized Contract

The explicit write-capacity exhaustion steering amendment supersedes the
original conflicting restart-at-4096 / subsequent-changed-save requirements.
4096 is temporary safety containment, not a permanently justified capacity.
Readable recovery is not active restart success.

F3 distinguishes only exact native regular-file staging names from committed
snapshot authority. No residue deletion, content-based promotion, newest-file
selection, unknown-file exemption, or relaxed prepared-journal validation.
An absent committed state is not reconstructed from staging bytes.

F4 preserves full bounded validation through 4096 retained CHECKPOINT snapshots.
The store and publication boundary reject a new 4097 snapshot before persistence.
Prepared oversized historical journals require explicit reconciliation, not
truncation or adoption. Runtime startup at capacity is blocked before active
reconstruction; a valid restart from 4095 may commit 4096 but must then stop with
BLOCKED_CHECKPOINT_HISTORY_CAPACITY_EXHAUSTED. Subsequent state-changing work is
blocked. Inspection of the valid committed chain remains available.

The bounded non-Astra pre-freeze review found an in-lock store capacity exception
that bypassed the runtime's failure/lease cleanup. The review and original tree
are preserved. The repair also catches that authoritative save-time exception;
direct-publisher and prepared-journal last-slot interleavings must end failed,
nonaccepting, explicitly capacity-exhausted, and without a logical lease. A
session-eligibility update also rechecks capacity before returning. These are
in-scope failure-state repairs, not authority for concurrent runtime owners.

The count is contiguous retained snapshot history per epoch/publication, not
queue depth, payload rows, byte size, or records supplied in one save. No limit
increase, compaction, epoch rotation, history deletion, or silent write skipping.

## Preserved Boundaries

P1 immutable fill custody and quantity caps, P2 runtime/profile/config/epoch
binding, queue/JSON validation, snapshot TOCTOU, native Continuous admission,
Opening coexistence, exact Producer identity, and obligation gates are required
regressions. Risk, sizing, allocation, stop/target economics and approved quantity
source are unchanged. No provider/broker calls or credentials, GUI, Science,
service/scheduler, Paper/live, merge or deployment authority.

## Evidence

Task-owned evidence:
`C:/Users/steve/OneDrive/Documents/ArgusReviewBundles/LANE-OPENING-ENGINE/evidence/ARGUS-ENGINE-MODERN-OPERATIONAL-RECOVERY-F3-F4-REPAIR-001-IMPLEMENTATION`.

The exact directive/amendment, previous rejection, source inventories, bounded
non-Astra review, full discovery, compileall, secret/protected-state checks, and
packaged/extracted tests are independently reported there. This document alone
does not claim their PASS. A new immutable second-eye packet is allowed only
after implementation qualification. Prior failed evidence is preserved.

CHECKPOINT_HISTORY_MANAGEMENT_IMPLEMENTED = NO.
CHECKPOINT_HISTORY_MANAGEMENT_REQUIRED_BEFORE_PAPER = YES.
CONTINUED_OPERATION_AT_CAPACITY = NO.
CHECKPOINT_CAPACITY_HORIZON = UNKNOWN from representative modern observations.
Existing accelerated/same-timestamp test histories cannot establish a natural
checkpoints-per-hour rate; no artificial horizon is inferred from test speed.
NATIVE_CONTINUOUS_RISK_PRODUCER_WIRING = NOT_IMPLEMENTED.
NATIVE_CONTINUOUS_RISK_PRODUCER_REQUIRED = YES_BEFORE_ACTIVATION.
CSHARP_REBIND_REQUIRED = YES.
READY_FOR_PAPER = NO.
READY_FOR_CANONICAL_INTEGRATION = NO_PENDING_SECOND_EYE.

The 524KB impact investigation remains held until independent recovery acceptance.
Shared Roadmap/Branch Ledger/Task Log remain Integration-Steward owned.
