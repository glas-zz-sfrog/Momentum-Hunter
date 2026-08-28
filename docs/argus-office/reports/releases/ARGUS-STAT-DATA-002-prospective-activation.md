# ARGUS-STAT-DATA-002 Prospective Activation

## Status

`IMPLEMENTED_PENDING_LIVE_CANARY / RESEARCH_ONLY`

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

## Current Counts

No live activation exists yet:

- natural prospective observations: `0`;
- unique prospective members: `0`;
- historical-context-only records: `0`;
- outcome-complete members: `0`;
- outcome-pending members: `0`.

## Risk And Next Gate

Offline behavior is proven, but natural statistical capture is not accepted
until a bounded regular-session real-provider canary creates at least one member
before outcome, preserves restart/idempotency, packages every terminal result,
and passes independent second-eye review. No merge or downstream work is
authorized before that review.

## Manual QA

None. This task has no visual surface.

## Open Questions

- Will the next regular-session market produce at least one natural prospective
  member during the bounded canary?
- Will enough time elapse for a natural outcome attachment? If not, the packet
  must preserve that limitation without fabricating one.

## Recommendation

Freeze and push the branch, run the next eligible regular-session canary, emit
the mandatory sanitized self-contained ZIP for any terminal outcome, then stop
for independent review.
