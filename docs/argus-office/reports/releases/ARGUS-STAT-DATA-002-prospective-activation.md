# ARGUS-STAT-DATA-002 Prospective Activation

## Status

`LIVE_CANARY_FAILED / SECOND_EYE_REVIEW_REQUIRED / RESEARCH_ONLY`

## Branch

- Branch: `codex/ARGUS-STAT-DATA-002`
- Base: `23ee162373654e1db91af4c19f75bbc7887e3174`
- Implementation: `ebf1dbfd93a71e838a0ef4d6f90675b43d82d9e6`
- Push: complete
- Merge: unauthorized and not performed

## Scope

The task activates the existing opportunity and Continuous denominator
contracts through a write-once prospective activation. It adds immutable
membership, attempt, population, historical-context, outcome-link, and terminal
cycle-receipt records without changing discovery, readiness, scoring, ranking,
TradePlan, execution, provider, or UI semantics.

## Files Changed

- Product contracts: `continuous_denominator.py`,
  `continuous_live_qualification.py`, and new `prospective_denominator.py`.
- Verification: prospective denominator, canary, packet, and one normalized
  legacy PowerShell-output assertion test.
- Tooling: `run_stat_data_002_canary.py`.
- Governance: Goal Charter, research inventory, this report, and Roadmap.

## Observation Identity

Membership uses the accepted canonical identity hierarchy:

1. setup identity when a setup exists;
2. hot-universe member identity when no setup exists;
3. discovery-row identity when neither setup nor member exists.

Every cycle remains an attempt. Exact replay is idempotent, repeated equivalent
member/setup observations do not inflate unique membership, and a canonical
successor setup creates a new member.

## Offline Evidence

- Focused denominator/canary/legacy assertion: `85/85 OK`.
- Continuous/Producer adjacent regression: `100/100 OK`.
- Self-contained packet rehearsal: `1/1 OK`, including pre-ZIP and extracted-ZIP focused reruns.
- Full approved-environment discovery: `2,846/2,846 OK`, one expected Windows skip.
- Approved environment fingerprint: `791197DEDD392BD3D5FA0D6FB051F395562E336ABF995FC9FBD633FAC28760C8`.
- Compileall: pass.
- Diff check: pass.

Two earlier full runs exposed one unrelated PowerShell error-message assertion
that depended on console line wrapping. The exact test passed five isolated
runs; its assertion was narrowed to whitespace normalization without changing
installer behavior. The final complete run passed on the settled bytes.

## Protected Areas

`continuous_denominator.py` and the accepted natural live-qualification path
were changed only to bind an explicit active policy and persistence root. The
new prospective module has no provider, broker, account, position, order,
service, scheduler, or UI imports. Unknown instruments remain statistical-only
and execution-blocked. Paper, Shadow, and all order authority remain unavailable.

## Installed-State Proof

- Canonical local/origin remained `23ee162373654e1db91af4c19f75bbc7887e3174` and clean.
- Automation, Continuous Runtime, and Continuous Writer services remained Running/Automatic.
- Automation manifest SHA-256 remained `AFC55EC289E46E02DF96C2FC0B4DD501DEEC763FC94B82DBB2065B25F942700B`.
- Continuous deployment manifest SHA-256 remained `FC2810BAA3730EDFB7679026A70F305992EC772A381E733819B54FFFD29B73EB`.
- Installed mode remained `RESEARCH_ONLY`; order capability remained `UNAVAILABLE`.

## Terminal Canary Evidence

The corrected one-time scheduler fired at `2026-08-28 08:32 CT` (`13:32Z`). An
initial launcher invocation omitted the task root from `PYTHONPATH` and stopped
at import before creating evidence or contacting a provider. The corrected
same-occurrence invocation created the write-once activation at
`2026-08-28T08:33:57.369476-05:00`, then failed before provider contact while
reloading that record:

`ProspectiveDenominatorError: Activation population definitions drifted.`

The persisted JSON correctly contains all 11 frozen population names, but JSON
reload represents the collection as a list while `POPULATIONS` is a tuple and
strict validation compares the two directly. The failure occurred before the
provider-call try/catch, so no `terminal-result.json` or denominator root was
created. The exact verification traceback is preserved as
`verification-command.log`; no repair or rerun was attempted.

The mandatory failure packet is:

- ZIP: `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-STAT-DATA-002-PROSPECTIVE-CANARY-20260828-D5C2CA5-SECOND-EYE.zip`
- SHA-256: `951F49D219E9842D286E10F09C5C28C51B267A5FD584929A58630E617E27508B`
- Files: `233`
- Manifest entries: `232`
- Secret scan: `PASS`
- Manifest verification: `PASS`
- Pre-ZIP focused verification: `84/84 PASS`
- Extracted-ZIP focused verification: `84/84 PASS`

## Current Counts

The failed activation produced no prospective market observation:

- natural prospective observations: `0`;
- unique prospective members: `0`;
- historical-context-only records: `0`;
- outcome-complete members: `0`;
- outcome-pending members: `0`.

## Risk And Next Gate

Natural statistical capture remains unaccepted. The failure packet must receive
independent second-eye review before any narrowly scoped repair or rerun is
authorized. No merge or downstream work is authorized before that review.

## Manual QA

None. This task has no visual surface.

## Open Questions

- Does independent review confirm the tuple/list serialization boundary as the
  sole first missing transition?
- Should a later repair also move activation reload inside terminal failure
  accounting so every pre-provider failure receives `terminal-result.json`?

## Recommendation

Freeze the failed attempt and sanitized packet exactly as produced, retire the
one-time scheduler, and stop for independent second-eye review. Do not repair,
rerun, merge, deploy, or begin downstream work.

## Terminal Classifications

```text
TERMINAL_CANARY_RESULT = FAIL
PROVIDER_CONTACT_OCCURRED = NO
NATURAL_PROSPECTIVE_OBSERVATIONS = 0
UNIQUE_PROSPECTIVE_MEMBERS = 0
OUTCOME_COMPLETE_MEMBERS = 0
OUTCOME_PENDING_MEMBERS = 0
SECOND_EYE_ZIP_REQUIRED = YES
SECOND_EYE_ZIP_CREATED = YES
SANITIZATION = PASS
MANIFEST_VERIFICATION = PASS
PRE_ZIP_VERIFICATION = PASS
EXTRACTED_ZIP_VERIFICATION = PASS
MERGE_AUTHORIZED = NO
DOWNSTREAM_WORK_STARTED = NO
READY_FOR_SECOND_EYE_REVIEW = YES
```
