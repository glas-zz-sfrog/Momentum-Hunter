# Modern Recovery Integrity Repair

Status: IMPLEMENTED_PENDING_MERGE / INDEPENDENT_SECOND_EYE_REQUIRED.

Task branch: codex/ARGUS-ENGINE-MODERN-OPERATIONAL-RECOVERY-INTEGRITY-REPAIR-001.
Rejected implementation parent: 850782a9480205cf462c4681ce8ff2472e95c17b.
Protected canonical: 2bceeeadd06f5ed85943942f1c0f81b7094620f7.

## Bounded Change

P1 recovery now validates native immutable first/follow-on Shadow fill receipts
against original admission authorization, exact aggregate state, and preserved
snapshot ancestry. Remaining quantity cannot override cumulative receipt truth.
Partial completion retains the original order, position, opened-at and first-fill
bytes. Exact repeated observations do not add quantity. A committed receipt ahead
of its position cache requires explicit receipt-backed recovery; ordinary load
does not normalize evidence. Missing or contradictory custody fails closed.
The shared modern first-fill lineage also validates the original quantity cap.

P2 checkpoint stores require the independently selected native configuration.
Stable logical runtime/profile, contract/schema, epoch/config/source and snapshot
identities remain authoritative at creation, persistence and recovery. Queued
work carries exact runtime/profile binding and must occupy its matching required
container. Duplicate JSON keys and stale references that omit preserved archives
are rejected. A new process instance after restart is legitimate and is not
mistaken for a new logical runtime.

No risk, sizing, allocation, stop/target or Opening fill formula changes are
included. No native Continuous risk-producer wiring, provider contact, Paper/live
execution authority, deployment, scheduler/service, GUI or Science change is
authorized. The existing native risk-producer wiring remains NOT_IMPLEMENTED and
is still required before activation. C# consumers require later contract rebind;
this task does not implement or authorize it.

## Proof And Custody

Exact pre/post independent reproductions, adversarial tests, the non-Astra review
and its parent adjudication, scoped/adjacent/full-suite results, source inventories,
protected-state comparisons and package reruns are preserved separately under:

`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-OPENING-ENGINE\evidence\ARGUS-ENGINE-MODERN-OPERATIONAL-RECOVERY-INTEGRITY-REPAIR-001`

REPAIR-QUALIFICATION.json and FINAL-REPORT.json carry terminal measured results;
the immutable second-eye package supplies the exact tested source tree, patch,
manifest and self-contained verifier. This branch report alone is not a test PASS
or independent acceptance. The rejected 850782a ZIP and review remain historical
and unchanged. The original non-Astra advisory REJECT is not rewritten as an
ACCEPT of the corrected candidate.

Cross-defect tests compose actual native checkpoint and position recovery gates
under one synthetic epoch. They do not claim a live risk/position orchestrator.
Local history checks do not claim resistance to destruction or coherent rollback
of every independent copy of a protected root; deployment ownership remains a
separate unchanged boundary.

## Gate

Fresh complete suite PASS and packaged-source/extracted-package PASS are required
before branch closeout. Any unexpected full-suite failure, including WRITER_SLOW,
stops the task without an isolated replacement rerun or writer-budget change.
Normal branch push and review packaging do not authorize merge or activation.
READY_FOR_CANONICAL_INTEGRATION = NO_PENDING_SECOND_EYE.
READY_FOR_PAPER = NO.
