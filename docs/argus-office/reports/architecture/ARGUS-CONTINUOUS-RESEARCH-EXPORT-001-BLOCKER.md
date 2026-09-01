# ARGUS-CONTINUOUS-RESEARCH-EXPORT-001 Blocker Report

## Disposition

`TASK_STATUS = BLOCKED_SCIENCE_CONTRACT_CHANGE_REQUIRED`

Phase 1 contract reconciliation reached the directive's mandatory stop gate.
No implementation candidate is accepted, no second-eye ZIP is created, and no
merge, deployment, provider contact, service, scheduler, or activation is
authorized.

## Exact contradiction

The accepted architecture says:

- the producing side freezes outcome eligibility prospectively;
- `candidate-observation` carries frozen outcome eligibility;
- the interface is one-way with no Science-to-producer callback.

Canonical Science currently says:

1. The external observation schema is closed without `outcome_eligibility`
   (`contract.py`, observation profile).
2. Custody explicitly rejects a source observation containing
   `outcome_eligibility` (`custody.py:1019`).
3. Custody generates the commitment itself, including
   `committed_at = recorder_capture_time`
   (`custody.py:1092-1093`).
4. Every producer `DECISION_FACT` must contain
   `outcome_eligibility_commitment_sha256`
   (`contract.py:933,977`).
5. Custody rejects the decision unless that source hash equals the earlier
   Science-generated hash (`custody.py:1228-1230`).
6. `OutcomeAttachmentV1` must bind the same commitment through the frozen
   decision (`custody.py:1944-1950`).

The future Science receipt/capture time is neither a Continuous fact nor known
when a sealed producer publication is created. Satisfying the current contract
would require either:

- producer prediction/control of a Science-owned receipt clock;
- a reverse Science-to-producer handshake after discovery custody; or
- Science-side construction/rewriting of a producer decision envelope.

All three violate the task's authority and one-way-publication rules.

## Mechanical reproduction

The blocker probe used the same exact START and discovery source-envelope bytes
with two valid Science recorder clocks:

| Science capture clock | Generated eligibility commitment |
|---|---|
| `2026-09-01T14:00:00Z` | `0ec91af35a34b3e2f61edb94def90612a5f6394caa2c12f68dd72f23ceaf79c6` |
| `2026-09-01T14:00:01Z` | `85610fd076730cb4bd0275fd5e10c73c166afe9309d3491de254d953c8c6b0eb` |

The same producer decision bound to the first hash was accepted by recorder A
and rejected by recorder B with:

`Decision eligibility hash does not bind its observation.`

Evidence:

- `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\INTEGRATION\ARGUS-CONTINUOUS-RESEARCH-EXPORT-001-04f6f83\contract-blocker-proof.json`
- proof SHA-256:
  `a68c6fed0eb56d3c371b4196a42cdd78edd474b5053ec32788ad77c48837f0b0`
- reproduction script:
  `reproduction/prove_contract_blocker.py` under the same task evidence root.

## What was proven before stop

A diagnostic discovery-only draft demonstrated that current canonical accepts:

- producer-issued START and FINAL;
- exact canonical `ResearchExportEnvelopeV1` bytes;
- deterministic per-stream sequence and prior-raw-byte hashes;
- exact frozen discovery source-byte binding;
- owner-wrapped session/cycle/observation identities;
- immutable manifest/checksum structure;
- duplicate-safe replay into Science custody.

That draft omitted the existing decision/outcome semantic families and therefore
does not close the task objective. Its partial artifacts are diagnostic only,
were not packaged, and are not an integration candidate.

## Smallest required new review gate

A new serialized Science contract task must choose and independently review one
authority model. The accepted architecture points to the smallest coherent
choice:

1. the producer exports the frozen eligibility commitment with the observation;
2. Science validates and custodies that producer commitment without replacing
   its semantic hash;
3. Science records its separate receipt time only in custody metadata;
4. decisions and outcomes bind the producer commitment hash;
5. eligibility policy, instrument identity, first observation, and committed-at
   chronology remain strictly validated before any later market path;
6. no callback, provider authority, or execution authority is introduced.

The alternative—Science-owned semantic commitment—requires a redesigned
two-phase interface and is not the accepted one-way architecture.

## Required agent report

- Branch: `codex/ARGUS-CONTINUOUS-RESEARCH-EXPORT-001`
- Scope: contract reconciliation and blocker proof only
- Files changed: this blocker report and the field-authority map
- Tests/checks run: exact two-clock commitment probe; diagnostic focused draft
  tests were discarded with the unaccepted implementation
- Evidence for changed behavior: no behavior change; blocker reproduced
- Protected areas reviewed: Science contract/custody, Continuous evidence,
  trading/execution/provider/service/scheduler boundaries
- Push/merge status: task branch report only; no merge
- Risks: Science reader remains blocked; prospective capture remains unauthorized
- Manual QA: not applicable
- Open questions: approve a separate Science eligibility-authority repair task
- Recommendation: repair and independently review the contract, integrate that
  repair serially, then restart this producer task from the new canonical
