# AUTOMATION-RUNTIME-IDENTITY-002 Boundary Completeness

## Classification

`BOUNDARY_SAFE_BUT_OVERBROAD / ENVIRONMENT_BOUNDARY_OVERBROAD /
COMPLETE`

No production runtime-identity semantics, installed service, manifest, job,
schedule, provider, strategy, account, Paper, Shadow, broker, or order behavior
changed. The production V1 boundary remains authoritative.

Implementation/audit commit
`87f2ebf8d3a35260d32ad5f68e39fc3d9e186af5` was pushed and strictly
fast-forwarded into canonical. Post-merge canonical surface remained
`ee3888b57d4f283074c37e231a2c27419387f519fc0a77bad9f7421b5dfd389d`,
and the active release remained `APPROVED_RUNTIME_MATCH`.

## Production Identity

- Canonical and `origin/master` at task start:
  `d5d37cad84970bf8779eb1839568ad1eba5fdaa8`.
- Approved release: `OPENING-RUNTIME-B7F9069A246ED2D99BC8`.
- Release source Git:
  `6e3bf54ad156ecdd82a8d5f105285f83714958c0`.
- Approved runtime fingerprint:
  `b7f9069a246ed2d99bc86396fbc5914a0e541adf8bb766258e01cd0f1e5a85df`.
- Surface fingerprint:
  `ee3888b57d4f283074c37e231a2c27419387f519fc0a77bad9f7421b5dfd389d`.
- Configuration fingerprint:
  `133fc9a11d8dfe67db3331deec91ddbfd3082171f20d074eddf89ecd9453fac6`.
- Environment fingerprint:
  `aaf6baa92bc25dac06a3fca9f7d26aac045b44336a6d0d60de09ce77c1b8900e`.
- Live status at 03:04 CT on August 22: `APPROVED_RUNTIME_MATCH`, clean
  canonical worktree, current Git `d5d37ca`, fresh supervisor heartbeat.

The isolated task worktree materialized many tracked Python files with CRLF
line endings and therefore has a different byte fingerprint. It was never used
as production identity evidence. Canonical read-only status and relative
disposable before/after mutations are the authority for this audit.

## Current Inclusion Boundary

| Boundary | Type | Recursive/additions | Finding |
| --- | --- | --- | --- |
| `momentum_hunter/**/*.py` | code | yes | 208 files; every add/delete/rename/modify changes identity |
| `tools/capture_job.py` | runner | exact file | direct opening entry point |
| `tools/run_capture_job.ps1` | launcher | exact file | retry/deadline/terminal behavior |
| `requirements.txt` | dependency declaration | exact file | all declaration changes bind |
| five project-config fields | configuration | object fields | meaningful changes bind; unknown fields fail closed |
| service manifest runtime paths/poll/release fields | configuration | explicit fields | paths and outer-loop settings bind |
| Python/PowerShell/service host | environment | bytes and version where applicable | incompatible or changed executables bind |
| installed Python distributions | environment | complete inventory | relevant and unused packages both bind |
| platform/machine/Windows/timezone | environment | explicit fields | material host drift binds |
| loaded supervisor/gate/service host | process | exact SHA-256 | stale loaded bytes cannot pass a new release |

OAuth tokens, credentials, account values, mutable provider state, and
per-date schedule entries are excluded from release material. Schedule and
latest-start admission remain independently validated by the manifest.

## Actual Dependency Map

```text
MomentumHunterAutomation service executable
  -> loaded automation_supervisor.py
  -> manifest resolver and opening schedule admission
  -> approved opening-runtime gate
  -> tools/run_capture_job.ps1
  -> tools/capture_job.py
  -> provider transport / Finviz parser
  -> schema and semantic plausibility
  -> candidate models / qualification / scoring / rank
  -> candle readiness / same-session TradePlan / reports
  -> storage / terminal receipt
```

Static analysis finds 208 package modules total, 94 reachable package modules,
114 excluded package modules, and 97 files in the proposed closure after the
three explicit files are included. Third-party roots are `bs4`, `requests`,
and `websocket`. Twelve subprocess call sites exist; they are fixed runner,
Git/process control, environment probe, Engine Host, certificate/setup, or
proof-tool calls already inside the broad V1 surface. No module-name
configuration, plugin discovery, filesystem module scan, or dynamic script
loading was found in the opening closure.

The 94-module closure is still conservative because one shared runner imports
branch-only Paper, Shadow, and administrative modules. Further narrowing would
require entry-point separation or proven path-sensitive analysis.

## Expected Unrelated Development

| Class | Current V1 result | Correct treatment |
| --- | --- | --- |
| positively excluded Phase 13R/specialist/replay/exit research | changes identity | `MUST_NOT_CHANGE` after safe refinement |
| research-named code transitively used by opening | changes identity | `MUST_CHANGE` |
| historical/SQLite/offline package analysis outside closure | changes identity | `MUST_NOT_CHANGE` after safe refinement |
| WPF-only presentation source | unchanged | `MUST_NOT_CHANGE` |
| Roadmap/governance/release Markdown | unchanged | `MUST_NOT_CHANGE` |
| tests and fixtures not imported by runtime | unchanged | `MUST_NOT_CHANGE` |
| non-runner tools and review-bundle generation | unchanged unless imported | `DEPENDS_ON_SPECIFIC_SUBPATH` |
| shared runner's branch-only Paper/Shadow helpers | changes identity | `UNKNOWN_REQUIRES_CONSERVATIVE_INCLUSION` until entry points split |

`momentum_hunter/event_shock_specialist.py` is the positive research-only
fixture: it is outside the actual closure, has no dynamic/config reference,
yet a one-byte change changes V1 identity. The actual WPF fixture is
`src/MomentumHunter.Desktop.Wpf/MainWindow.xaml.cs` and does not change V1.
`ROADMAP.md` and `TASK_LOG.md` mutations also do not change V1.

## Mutation Results

| Mutation | V1 | Proposed closure qualification |
| --- | --- | --- |
| research-only Python | changed | unchanged |
| WPF-only source | unchanged | unchanged |
| Roadmap and second governance Markdown | unchanged | unchanged |
| supervisor | changed | changed |
| Python runner | changed | changed |
| PowerShell launcher | changed | changed |
| provider/parser | changed | changed |
| schema/plausibility | changed | changed |
| candidate model | changed | changed |
| scoring/rank | changed | changed |
| TradePlan/report/storage | changed | changed |
| calendar/session | changed | changed |
| opening candle readiness | changed | changed |
| runtime `.py` add/delete/rename/modify | changed | imported additions bind; unused additions stay excluded |
| project config change | approved identity changes | same required contract |
| unknown config field | fail closed | fail closed |
| installed `requests` version | environment changes | relevant dependency must bind |
| unused installed package | environment changes | should be excluded after safe refinement |

The existing execution-gate tests prove each changed approved component is
blocked before provider or runner authority. Add/delete/rename/modify are
automatic under V1's recursive package rule.

## Import And Dynamic-Load Safety

The current live graph has zero local import escapes and zero dynamic-import
sites. A disposable import from `tools/capture_job.py` to
`support/external_opening_dependency.py` demonstrates the raw V1 weakness:
the importer change forces one promotion, but later external-file mutation is
not in V1. The new qualification audit detects that outside-root dependency
and refuses to produce a closure fingerprint.

A disposable `importlib.import_module(...)` call is likewise detected and
rejected until explicitly classified. This static policy is the required guard
for any future narrowing. It does not change the active runtime gate.

## Configuration And Environment

Project fields `mode`, `provider`, `review_timezone`,
`evening_review_window`, and `morning_review_window` are all fingerprinted.
Unknown fields fail closed. Repository, interpreter, PowerShell, state,
Engine Host state, service host, poll interval, and release-root paths are
fingerprinted from the installed manifest context.

Python is bound by executable SHA-256 and version (`Python 3.12.6`),
PowerShell by executable SHA-256 and version (`5.1.26100.9168`), and the
service host by SHA-256. The six declared requirements and all fifteen
installed distributions are bound. This safely detects relevant drift but an
unrelated analysis package also forces promotion, hence
`ENVIRONMENT_BOUNDARY_OVERBROAD`.

## Promotion Frequency

The most recent 20 canonical commits produce:

- 4 V1 runtime promotions.
- 2 static-closure promotions.
- 16 Git-only commits under V1.
- 2 of the 4 V1 promotions were caused only by package work outside the
  measured opening closure.

This bounded sample indicates a defensible closure could halve runtime
promotions among commits that currently trigger them, while leaving 16/20
already-decoupled Git-only commits unchanged. It is evidence of meaningful
operational benefit, not a long-run forecast.

## Verification

- New boundary tests: 9/9 pass.
- Focused runtime identity, release, supervisor, planner, runner, and capture
  suites: 132/132 pass; one expected non-elevated symlink skip.
- Full Python discovery: 2,723/2,723 pass in 692.346 seconds; one expected
  non-elevated symlink skip. The first run's two failures were caused solely by
  the isolated worktree lacking its expected `.venv` path; both affected
  modules passed after an ignored junction to the canonical environment, and
  the complete suite then passed monolithically.
- Compileall: pass.
- PowerShell runner parse: pass.
- Diff/secret/capability/protected-path scans: pass at branch qualification.
- .NET: not required because no .NET or shared runtime source changed.

## Direct Answers

1. The active fingerprint is effectively whole-package, not dependency-based.
2. Yes. A committed `ROADMAP.md` change leaves opening identity unchanged.
3. No under V1. Proven research-only package Python still forces promotion.
4. Yes. WPF-only source leaves opening identity unchanged.
5. Supervisor, runner, launcher, any package Python, requirements/environment,
   classified runtime config, interpreter, PowerShell, service host, or loaded
   process change requires promotion under V1.
6. A package module cannot escape V1. A local module outside the package could
   escape after its importer was promoted, so the new static import-policy gate
   rejects such a future release before qualification.
7. No dynamic loading exists now; future dynamic-loading calls fail the new
   qualification test until explicitly classified and bound.
8. Yes. An unrelated installed package currently forces needless promotion.
9. No observed relevant dependency can escape: imported package code,
   requirements, all installed distributions, executables, config, and loaded
   bytes bind. Outside-root imports are now a qualification failure.
10. Yes. The current boundary is safe and broader than necessary.
11. Yes. The recent-20 sample drops promotion-triggering commits from 4 to 2.
12. No production change was made by this task.
13. Monday remained pending at 08:35/08:40 CT with 15 future openings, a
    Running/Automatic service, a fresh heartbeat, zero Shadow jobs, and
    unavailable order transmission at the last read-only check.

## Recommendation

Keep V1 unchanged through Monday. The global Roadmap remains led by the active
RTD experiment. The exact bounded successor for this reliability stream is
`ARGUS-AUTOMATION-RUNTIME-IDENTITY-003 - Dependency-Closure Refinement And
Promotion Integration`, to be scheduled after Monday evidence. It must turn
the offline policy into an authoritative promotion-time contract, narrow the
installed-distribution rule, and repeat physical release validation before V1
is replaced.
