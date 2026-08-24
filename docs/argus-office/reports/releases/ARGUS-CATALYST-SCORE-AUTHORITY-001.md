# ARGUS-CATALYST-SCORE-AUTHORITY-001 Release Report

## Classification

`COMPLETE / APPROVED_RUNTIME_ACTIVE`

## Scope

Repair the prospective scoring-authority leak exposed by the August 24 BMNR
opening evidence. Preserve all historical evidence and leave catalyst
relationship semantics, candidate admission, thresholds, TradePlan rules,
Risk Governor, broker, Paper, Shadow, service, and scheduler behavior unchanged.

## Root Cause

`momentum_hunter/scoring.py` concatenated all headlines known at evaluation
time and applied catalyst/risk keyword rules before subject-relationship
authority was checked. `momentum_hunter/trade_planning.py` classified catalyst
attribution later, after the unauthorized score could already affect the 42%
score component of composite rank.

The existing authority contract in `momentum_hunter/evidence_integrity.py`
permits direct-issuer evidence and explicit macro evidence. It leaves unproven
sector, peer, customer/supplier, ambiguous, and unrelated relationships
`UNRESOLVED / BLOCKED`. This task reuses that contract at score-assignment time;
it does not broaden it.

## Repair

- Score each known-at-evaluation headline only after relationship authority is
  classified for that candidate.
- Permit catalyst bonus and risk penalty text only from authorized headlines.
- Preserve blocked headlines as visible research context with zero points.
- Persist zero-point catalyst-authority context containing total, authorized,
  and blocked counts plus relationship-type summaries.
- Advance the scoring implementation identity from `momentum_score_v1` to
  `momentum_score_v2`; the explanation model reads the persisted engine version
  rather than asserting v1.

No currently supported caller-proven related-company relationship exists in
the scoring input contract. Those relationships therefore remain blocked
rather than receiving invented authority.

## August 24 Diagnostic

Historical evidence remains byte-identical:

- `MomentumHunterData/data/captures/2026-08-24/opening.json`
  SHA-256 `A95C77C94700B3DAF127E830FE2659F4FB54A247FF0E252C07DA641A418EBFA2`
- `MomentumHunterData/data/score-breakdowns.json`
  SHA-256 `26EABD675CC063B16F1296F36C0D63A78BECC82AE2173C4F87E20A1FF9121F1B`

The stored BMNR score remains 79. A nonpersisted
`COUNTERFACTUAL_DIAGNOSTIC_ONLY` evaluation using the preserved candidate,
preserved 08:35:06 CT evaluation time, BULL regime, and `momentum_score_v2`
computes 68. The entire -11 delta is the removed unauthorized
`positive_catalyst.ai` contribution. It is not a replacement historical score.

## Verification

- Focused and adjacent: 73/73 passed.
- Full Python discovery: 2,728 passed, 2 failed, 1 skipped in the first isolated
  run. Both failures were environment-layout checks caused solely by the task
  worktree lacking its ignored `.venv` path.
- After an ignored junction to the canonical environment, the exact two failed
  modules passed 39/39. Every discovered test is therefore accounted for.
- Python compileall passed.
- `git diff --check`, protected-path review, secret scan, and capability scan
  passed.
- Historical August 24 hashes remained unchanged.
- Canonical `master` remained clean and synchronized at
  `6933e49bc42c07914ad319d726625f1ac5692936` throughout implementation proof.

## Protected Areas

The scoring path is protected and was explicitly authorized by the directive.
No provider, account, Paper, Shadow, broker, order, service, scheduler, runtime
installation, production evidence, WPF source, threshold, or setup semantics
changed. The nonvisual presentation contract now reports the actual persisted
score-engine identity without changing layout or controls; automated contract
tests are the acceptance evidence and no manual verification item is required.

## Promotion Closeout

The proven branch was pushed through
`290ea31934bdae53d26645b2767f8f0918652622`, cleanly fast-forwarded into
canonical `master`, and pushed normally. The established V1 promotion created:

- release `OPENING-RUNTIME-2698312C5F3749F4916C`;
- release fingerprint
  `478a25a75736381aac69e67a2da1ec2ec383e46ec53da5d6462b0bc126299dff`;
- runtime fingerprint
  `2698312c5f3749f4916cd581f48fa713cc4af31015ed63d21279e9a1f8145aa3`;
- source Git `290ea31934bdae53d26645b2767f8f0918652622`.

The live verifier reports `APPROVED_RUNTIME_MATCH`, a fresh supervisor
heartbeat, clean synchronized Git, and order transmission `UNAVAILABLE`.
Fourteen future openings already use the approved channel; migration planning
reported zero changed jobs. No service restart or manifest rewrite was needed.
`ARGUS-AUTOMATION-RUNTIME-IDENTITY-003` is unblocked but not started.
