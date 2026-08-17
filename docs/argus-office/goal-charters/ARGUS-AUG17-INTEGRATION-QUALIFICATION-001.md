# Goal Charter: AUG17 Integration Qualification

## Goal

Build one coherent candidate from the completed research, continuous-runtime,
writer-security, and Schwab authorization-recovery branches, then prove it
offline and against the live market without changing the frozen August 17
production experiment.

## Scope

- Integrate only final verified branch heads on an isolated worktree.
- Resolve integration conflicts without duplicating branch lineages.
- Run combined focused and full Python verification.
- Exercise live Finviz discovery, Schwab quote/candle readiness, continuous
  composition, denominator production, writer persistence, and restart recovery
  in a disposable read-only sidecar.
- Preserve failed qualification generations and start a new generation after a
  repair.
- Observe the frozen SETUP-002 Pass 2 read-only after its scheduled 15:05 CT run.
- Adjudicate the remaining CONT-STORAGE-001 scope.

## Non-Goals

- No merge to `master` in this task.
- No installed service, manifest, scheduler, job, production data, Paper,
  Shadow, account, position, broker, order, scoring, risk, or UI mutation.
- No strategy-profitability or continuous-Paper claim.
- No retrospective strategy decision or fabricated successor setup.

## Acceptance Evidence

- Canonical `master` and `origin/master` remain clean and equal to `ea056155`.
- Source implementation files match their final verified branch heads.
- Combined focused tests, full discovery, compileall, diff, secret, capability,
  and protected-path checks pass.
- A live sidecar completes real three-page Finviz and real Schwab qualification,
  produces immutable writer evidence, and survives a checkpoint restart.
- Per-symbol provider/readiness failures remain localized and explicit.
- Zero broker orders and zero production mutations occur.
- The original 15:05 SETUP-002 Pass 2 remains pinned to `ea056155` and is
  preserved before final classification.

## Current Result

The combined candidate, live Generation 2 sidecar, and extended soak pass.
Generation 1 is preserved as a harness-boundary failure and was repaired
without weakening the checkpoint policy. Frozen Pass 2 completed terminally on
the protected production identity. A final dependency-boundary defect was
repaired through the writer facade; focused and complete regressions pass.
Classification: `AUG17_INTEGRATION_CANDIDATE_MERGE_QUALIFIED`.

## Goal Steward Review

- [x] The objective is behavioral and measurable.
- [x] Canonical and operational nonmutation boundaries are explicit.
- [x] Live engineering qualification is separated from strategy evidence.
- [x] Storage completion requires an explicit disposition.
- [x] Frozen Pass 2 and final post-Pass-2 verification are terminal.
