# ARGUS-CONTINUOUS-RESEARCH-EXPORT-002 Contract Trace

## Boundary

`ContinuousResearchExporterV2` is an offline-only Continuous-owned publisher for
the exact canonical `ResearchExportEnvelopeV2` / `2.0.0-proposal` parser. It
constructs canonical raw bytes and immediately submits those same bytes to
`parse_export_envelope_v2`. Direct compatibility proof passes the unchanged
`StrategyScienceRecorder.accept(...)` surface the publisher bytes without an
adapter or rewrite.

The source direction is one way:

```text
Producer-known facts at T0
  -> immutable canonical V2 bytes
  -> atomic published namespace
  -> later Science custody at T1
  -> Science eligibility/materialization at T1 or recovery T2
```

No source envelope contains or predicts Science receipt time, receipt hash,
eligibility identity, eligibility hash, eligibility commitment, Science
materialization time, later outcome, future return, or later decision state.

## Field Authority

| Material | Owner | Publication rule |
| --- | --- | --- |
| Session identity and START payload | Continuous Producer | Must be complete and published first; late reconstruction is rejected. |
| Source event identity, stream, sequence, prior raw hash | Continuous Publisher | Deterministic from producer identity and durable per-stream head. |
| Event/effective/emitted clocks | Continuous Producer | Derived from the canonical event semantic fields; publication cannot rewrite them. |
| Discovery, decision, market, health payload | Continuous Producer | Canonical V2 parser must accept the exact payload. |
| Science receipt and eligibility | Strategy Science | Absent from Producer bytes; created only after custody. |
| FINAL counts and stream heads | Continuous Publisher | Derived from verified immutable publications rather than caller assertions. |
| Delivery ordinal | Continuous Publisher | Operational delivery ordering only; never claimed as universal source chronology. |
| Cross-source decision dependency | Continuous Producer | Referenced observation/evidence identity must already be producer-published. Unknown ordering remains unknown. |

## Publication And Restart

Only complete files under `published/` are visible. Canonical bytes are first
written and fsynced under `staging/`, then hard-linked atomically into the public
namespace. A mutable checkpoint is diagnostic only. Restart scans and revalidates
every public V2 envelope, restores contiguous per-stream sequence and the exact
prior raw-envelope hash, finishes at most one valid staged publication, and
fails closed on gaps, reordering, hash mismatch, duplicate event identity,
unrecognized objects, malformed bytes, or ambiguous staging.

Conflicting reuse of one source event identity records only the accepted and
conflicting hashes and prevents complete FINAL qualification. Published raw
bytes are never modified.

## START And FINAL

START is validated with the canonical full manifest validator and must be the
first visible publication. FINAL is built internally only when terminal truth is
explicit, pending/gap/conflict counts are zero, `closed_at` does not precede any
producer fact, and the frozen finalization cutoff has elapsed. Its event counts
and stream heads are recomputed from immutable publications. Otherwise the
exporter retains `INCOMPLETE_NO_FINAL` in its durable checkpoint and exposes no
false FINAL.

## Outcome Disposition

`OutcomeAttachmentV1` remains the accepted separate later Science-linked append
surface. Its payload requires a Science eligibility commitment and canonical
custody-linked decision/bar identities, so it is not a Producer-only T0
`ResearchExportEnvelopeV2` publication and is not implemented or back-propagated
by this task. No contract change is required for the T0 exporter, and no outcome
is retrofitted into historical evidence.

## Historical And Capability Boundaries

The exporter has no historical-corpus reader, START/FINAL reconstruction,
retrofit, upgrade, runtime attachment, provider client, authentication, service,
scheduler, Science reader, Paper, Shadow, broker, account, position, order, or
execution surface. Opening 2026-08-31, STAT-DATA-002D, Continuous 001D/001E,
and Observer 2026-09-01 retain their prior evidence classes unchanged.
