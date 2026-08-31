# ARGUS-STAT-DATA-002E Accepted Lineage Integration

## Classification

- Status: `COMPLETE / CANONICAL_INTEGRATED / RESEARCH_ONLY`
- Pre-integration canonical: `23ee162373654e1db91af4c19f75bbc7887e3174`
- Source branch: `codex/ARGUS-STAT-DATA-002D`
- Reviewed executable head: `039d4e0f71c082d07d0a774d4c2d3a9dc20888b9`
- Final source head: `481a37c796e20195fb6780db73588402d91b9414`
- Accepted ZIP SHA-256: `5702F113BC8E2EB9BBCD1A3E5DDD53C33E2C3F2F4B52CF56A816380AE4C5B991`

## Head Binding And Ancestry

The only commit after the reviewed executable head is `481a37c`, which changes
only `docs/argus-office/ROADMAP.md` and the 002D release report. No executable,
test, tool, or runtime byte changed after independent review.

Canonical `23ee162` is the exact merge base and direct ancestor of the complete
13-commit serial STAT-DATA-002 through 002D lineage. The integration used
`git merge --ff-only` with zero conflicts, no cherry-pick, rebase, squash,
amendment, merge commit, or unrelated commit.

## Incoming Scope

- 4 STAT-DATA Product runtime modules.
- 6 test modules.
- 1 research-only canary/forensic tool.
- 12 governance/research documents.
- 0 GUI, Opening runtime, service, scheduler, Paper/Shadow, broker, account,
  position, or order paths.

## Verification

- Compileall: `PASS`.
- Focused and adjacent STAT/opening tests: `146/146 PASS`.
- Full approved-environment discovery: `2869/2869 PASS`, one expected skip.
- Reviewed-head Product runtime equivalence: `PASS`.
- Reviewed-head test equivalence: `PASS`.
- Reviewed-head tool equivalence: `PASS`.
- Git diff checks: `PASS`.
- Incoming-file secret scan: `PASS`, 23 files, zero findings.
- Capability scan: `PASS`, zero risky execution call sites.
- Protected-path review: `PASS`.
- Automation manifest, Continuous deployment manifest, opening channel, and
  active opening release hashes: unchanged.
- Automation, Continuous Runtime, and Continuous Writer services remained
  Running/Automatic and were not restarted.
- Active Opening release remains `OPENING-RUNTIME-1C49F7F328503BF8FECF`.
- Continuous remains `RESEARCH_ONLY`; order transmission remains `UNAVAILABLE`;
  Paper and Shadow enabled-job counts remain zero.

The first attempted full-discovery command used an unsupported `-t .` argument
for this repository's non-package `tests` directory and exited before loading
tests. The corrected repository-supported `unittest discover -s tests` command
produced the authoritative complete result above.

## Preserved Semantics

Prospective membership remains immutable; historical backfill remains outside
prospective membership; anti-hindsight, duplicate suppression, nested
populations, and restart idempotency remain proven. Statistical-observation
eligibility remains distinct from execution eligibility. Unknown instruments
remain execution-ineligible, and `NO_PLAN` is not reinterpreted as a READY
strategy rejection.

## Operational Boundary

This was source integration only. No deployment, provider call, service restart,
schedule change, Opening change, GUI change, Paper/Shadow activation, account,
position, broker, or order authority was used. The accepted evidence and
second-eye ZIP remain immutable. Three-lane governance was not established.
