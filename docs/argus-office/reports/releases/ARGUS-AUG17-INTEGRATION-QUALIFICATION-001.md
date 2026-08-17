# AUG17 Integration Qualification Closeout

## Identity

- Protected canonical baseline: `ea056155182351be70bb03d23841aca55c6118ae`.
- Integration branch: `codex/ARGUS-AUG17-INTEGRATION-CANDIDATE-001`.
- Research stack head: `c1eacecbcad8eb7ba0c925300a335b8150469a8d`.
- Continuous/writer stack head: `870db1216d267c85460187c07590137937c807e0`.
- Schwab recovery head: `b1e05b7eb506777483c1bdad047d8bb12ff1c9c7`.
- Live-sidecar implementation: `012b555`.
- Final candidate HEAD: this closeout commit (recorded by Git after commit).
- Classification: `AUG17_INTEGRATION_CANDIDATE_MERGE_QUALIFIED`.

## Integrated Lineage

The research lineage contains SPECIALIST-CONTRACT-001, RESEARCH-DATA-001/002,
RESEARCH-GOV-001, STAT-DATA-001, REGIME-002, EXEC-QUALITY-001,
EVENT-SHOCK-001, TECH-STRUCTURE-002, and EXIT-RESEARCH-001 once through
`c1eacec`. The continuous lineage contains CONT-DISCOVERY-001/002,
CONT-UNIVERSE-001, CONT-COMPOSE-001, STAT-DATA-002, CONT-DAYPROOF-001,
CONT-RUNTIME-001, WRITER-TOPOLOGY-002, CONTINUOUS-WINDOWS-ISOLATION-001,
and WRITER-HARDENING-001 once through `870db12`.

Temporary parent `a5040e8` was not integrated. Its four denominator files were
byte-for-byte copies of the authoritative STAT-DATA-001 lineage, so skipping it
prevents a second source identity. Implementation comparison found 54 research
files byte-identical to `c1eacec`, 34 continuous/writer files byte-identical to
`870db12` after excluding those copies, and 15 Schwab files byte-identical to
`b1e05b7`.

No source conflict occurred. The only cherry-pick conflicts were the shared
Roadmap, changelog, and task log; both histories were retained and reconciled.

## Integration Repair

The initial 984-test combined gate exposed three failures with one root cause:
`FinvizProvider.discover_paginated` used the caller's historical evidence
timestamp as the live elapsed-time budget anchor. A sufficiently old evidence
timestamp therefore exhausted pagination before the second request.

The repair uses a monotonic process timer for request budgeting and leaves the
caller timestamp as evidence identity only. A regression proves that a
30-day-old evidence timestamp still completes two pages. The corrected focused
gate passed 985 tests.

## Offline Hard Chew

- Combined focused modules: 985/985 pass in 311.63 seconds.
- Full Python discovery: 2,604/2,604 pass in 584.852 seconds.
- Compileall: pass.
- `git diff --check`: pass.
- Protected-path review: pass.
- Broker/order capability scan: pass.
- Secret scan: pass; only known synthetic rejection fixtures matched shapes.
- Source conflict-marker and lineage checks: pass.

The worktree required an ignored `.venv` junction to the canonical dependency
environment for PowerShell-backed tests. It is not tracked and will be removed
at closeout.

## Live Qualification

### Generation 1

The first disposable generation used an ordinary Local AppData root. It failed
before any provider call because `RuntimeCheckpointStore` correctly permits
only Windows temporary roots. The failed generation was preserved. The
checkpoint boundary was not weakened.

### Generation 2

- Evidence root:
  `C:\Users\steve\AppData\Local\Temp\MomentumHunterQualification\AUG17-INTEGRATION-QUALIFICATION-001\generation-20260817-1237`.
- `LIVE_QUALIFICATION_START`: `2026-08-17T12:32:27.079038-05:00`.
- Completion: `2026-08-17T12:38:28.339742-05:00`.
- Duration: 360.656 seconds.
- Status: `PASS`.
- Summary fingerprint:
  `657ac840222e240acef63fa0762243b8755bd15b1ba212b8e3e84e54d102b66a`.

Observed results:

- Broad discovery cycles: 3.
- Finviz pages / represented rows: 9 / 180.
- Unique symbols: 62.
- Newly admitted midday symbols: 0; the bounded six-minute interval produced a
  stable source set, and no admission was fabricated.
- Candidate tier transitions: 189.
- Schwab refreshes / quote symbols: 3 / 9.
- Schwab one-minute / Daily rows: 80,268 / 3,207.
- Canonical ready symbols: SNDK.
- Composition / denominator cycles: 3 / 3.
- Incomplete or system-failed cycles: 0.
- Research-only TradePlans / successor setups: 0 / 0. No lifecycle evidence
  was invented merely to force either output.
- Provider recovery events: 0; no provider failure occurred.
- Evidence records / writer errors: 6 / 0.
- Runtime restart count: 1; checkpoint restore passed.
- Universe fingerprint before and after restart:
  `062850d9592a8b897c624d16b117c1741bcc6d66a7d81a95075850fc9a51570e`.
- Orders transmitted: 0.
- Production mutation: false.

CBRS and NXE each failed `TIME_NORMALIZED_RVOL_INSUFFICIENT_OR_UNSAFE` in all
three cycles. These six readiness failures remained symbol-local, were
preserved in checkpoint evidence, and did not invalidate SNDK or any denominator
cycle. Runtime health finished with no active degradation, backpressure, or
queued work.

### Extended Soak

A fresh 15-minute generation ran from `2026-08-17T12:46:56.340737-05:00` to
`2026-08-17T13:01:57.683450-05:00`. The initial launch without the explicit
`--execute-read-only` interlock failed closed before root creation or provider
contact; a new generation was then used.

The soak passed 8 discovery cycles, 24 Finviz pages, 480 represented rows, 69
unique symbols, 504 tier transitions, 8 Schwab refreshes, 24 quote symbols,
216,176 one-minute rows, 8,890 Daily rows, 10 composition cycles, 10 complete
denominator cycles, and 20 immutable writer records. AXTI, COHR, and SNDK
reached canonical readiness. Fourteen individual readiness attempts failed
closed; the final checkpoint preserved CBRS, NXE, and FIGR as
`TIME_NORMALIZED_RVOL_INSUFFICIENT_OR_UNSAFE`. There were zero provider,
system-cycle, writer, queue, order, or production-mutation failures.

The mid-run restart occurred after 10 evidence records. Its pre/post universe
fingerprint was identical at
`5863c5cdf17a3a9128f6abd1fcfe1fc5b26d2d322803722c6463e016218c1437`.
Every queue drained, no sidecar process remained, and the independent summary
SHA-256 matched its write-once checksum file at
`05632EC952C6749950EFA1E57092087A5F40B30A3EF64C0BD5A769600FA71623`.

## Storage Disposition

`CONT_STORAGE_REMAINDER_IDENTIFIED`.

Writer hardening proves process ownership, write-once sharded persistence,
restart recovery, and reparse-resistant physical commits. The live sidecar also
proves sustained authenticated intent/receipt writing. The remaining bounded
activation work is:

- install the writer under the already-proven dedicated LocalService principal;
- persist and index the complete composition/denominator business payloads,
  rather than only authenticated intent and payload fingerprints;
- define the production checkpoint/root ownership and read/index API used for
  deterministic restart and review;
- prove retention/index recovery without weakening immutable source records.

This remainder blocks research-only continuous activation. It does not create
an unresolved contradiction inside the merge candidate.

## Frozen Production Lane

Before and after live qualification, canonical `master` and `origin/master`
were clean and equal to `ea056155`. The Automation Service remained Running
and Automatic. The production manifest SHA-256 remained
`8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`.
The frozen Pass 2 remains enabled, dependent on Pass 1, scheduled for 15:05 CT,
and pinned to `ea056155`. No service, manifest, scheduler, production evidence,
Paper, Shadow, account, position, broker, order, or UI state was changed by the
integration candidate or sidecar.

The already-running canonical active monitor independently created 20 normal
report files during the sidecar window: 8 `active-monitor-*`, 6
`opportunity-alerts-*`, and 6 `opportunity-monitor-targets-*`. The sidecar did
not create or alter those files: its only canonical-root operations are Git
identity reads, its imports contain no active-monitor producer, and every
writable store is derived from the new disposable Temp generation root. Thus
`zero production mutation` is a sidecar capability/result claim, not a claim
that unrelated production monitoring was globally paused.

## Final Gate

- Frozen SETUP-002 Pass 2: completed at `2026-08-17T15:05:01.762608-05:00`
  with exit 0. MU and SKHY terminated `DATA_FAILURE` because canonical minute
  partitions were absent after the morning Schwab failure; no hypothetical
  trade was created. Output SHA-256:
  `854A59F6A0059E1995C73FBFDFFE1B29461087F4B7F57DF2BCEB629C3876A81E`.
- Its decision-packet SHA-256 remained
  `EB8D99626426F63664B23E44CB33B39098FFB079799A6142736A49185CA20C04`.
- The first post-Pass-2 2,608-test run exposed one static dependency-boundary
  failure: the qualification sidecar imported low-level writer IPC directly.
  Capability creation now routes through the evidence-writer facade without
  broadening the IPC importer allowlist.
- Focused IPC/writer/sidecar regression: 48/48 pass in 198.427 seconds.
- Corrected post-Pass-2 full Python discovery: 2,608/2,608 pass.
- Compileall and `git diff --check`: pass.
- Feature-branch backup: performed after this closeout commit.
- Merge to canonical: not performed by this qualification task.

No technical blocker remains to merge qualification. Research-only continuous
activation still requires the storage/deployment remainder above,
lifecycle/successor input wiring, a prospective activation identity, and
scheduler/service integration.
