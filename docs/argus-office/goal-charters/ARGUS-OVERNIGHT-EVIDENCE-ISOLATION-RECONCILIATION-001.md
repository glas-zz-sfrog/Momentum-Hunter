# ARGUS-OVERNIGHT-EVIDENCE-ISOLATION-RECONCILIATION-001

## Goal

Adjudicate the existing `ARGUS-OVERNIGHT-DATA-FIDELITY-001` observations
provider by provider, checkpoint by checkpoint, and claim by claim under the
canonical long-running-campaign provenance model.

## Immutable Boundary

- Preserve `GLOBAL_PRODUCTION_NONMUTATION = FAILED` permanently.
- Do not alter, regenerate, replace, delete, or backdate any historical file.
- Make no provider, account, position, broker, order, OAuth, service,
  scheduler, manifest, or runtime call/change.
- Create only a new audit overlay, verifier/tests, and governance records.
- Change no Momentum Hunter product/runtime code.

## Acceptance

1. Recompute the 51-file historical tree as
   `5F52C966F5724A940C0B855ED1DC73AD6F60DFA1629FCA7F3CC6F93141573ED6`.
2. Verify the original manifest, all 15 checkpoint hashes, and evidence
   fingerprints.
3. Preserve frozen source `a75422605e67575d267d7d2980519878ec3a5a26`
   and mark its reconstructed source manifest as post-hoc corroboration only.
4. Overlay every authorized production change and shared dependency against
   every checkpoint.
5. Classify each material claim exactly as `VALIDATED`,
   `VALID_WITH_PROVENANCE_LIMITATION`, `UNPROVEN`, or `INVALIDATED`.
6. State the smallest remaining experiment without launching it.
7. Prove no historical, production, provider, credential, account, broker,
   order, service, scheduler, manifest, or runtime mutation occurred.

## Final Classification

`OVERNIGHT_EVIDENCE_RECONCILED` only when all acceptance checks pass.
