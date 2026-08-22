# Opening Runtime Identity ADR V1

## Decision

Use **Model B: current canonical checkout plus a conservative approved runtime
surface and environment fingerprint**.

The Automation Supervisor verifies the active `opening-capture` release
immediately before launch. Git HEAD remains evidence, while eligibility comes
from actual executable bytes, configuration, environment, loaded-process
identity, an immutable release, and its promotion chain.

## Models Compared

### Model A: Whole-Git Pin

Strengths:

- Simple, conservative, already physically proven to fail before the runner.
- Exact provenance and straightforward rollback.

Weaknesses:

- Treats every repository byte as opening behavior.
- A Roadmap, test, review-copy, research-documentation, or WPF-only commit
  invalidates every future opening despite byte-identical opening runtime.
- Requires recurring mass job rewrites and creates avoidable schedule risk.

Failure behavior is fail closed. Operational cost is now excessive. Model A
remains the rollback contract and the schema for legacy jobs/receipts.

### Model B: Checkout Plus Approved Runtime Fingerprint

Strengths:

- Gates the actual current bytes and nonsecret environment used by the runner.
- Detects uncommitted runtime mutation independently of Git metadata.
- Keeps the existing service, runner, schedule, data locations, and rollback.
- Decouples positively excluded repository areas without deploying another
  Python runtime.
- Supports explicit, write-once release promotion and stronger receipts.

Weaknesses:

- The runtime surface must be conservative and maintained as architecture
  changes.
- A changed checkout blocks opening until a matching release is promoted.
- Long-running process bytes need explicit loaded-identity evidence.

### Model C: Immutable Deployed Opening Runtime

Strengths:

- Strongest physical separation between repository development and execution.
- A prior deployed release can continue while master changes.

Weaknesses:

- Adds packaging, dependency copying, deployment ownership, garbage collection,
  and a second runtime topology.
- Creates new synchronization and rollback responsibilities beside the already
  installed Automation Service.
- Does not materially improve the current safety objective once Model B binds
  current bytes, environment, loaded processes, configuration, and promotion.

Model C is rejected for this milestone because its added infrastructure is not
justified by an identified safety gap in the selected model.

## Execution Dependency Map

```text
MomentumHunterAutomation service host
  -> loaded Python Automation Supervisor
  -> manifest schedule/session/latest-start admission
  -> approved opening-runtime execution gate
  -> tools/run_capture_job.ps1
  -> tools/capture_job.py
  -> momentum_hunter package imports
     config / time / scheduling / market calendar
     Finviz transport and parser / semantic gates
     candidate models / qualification / scoring / ranking
     opening candle readiness / TradePlan / reporting
     storage / immutable terminal evidence
  -> terminal service receipt
```

The runner invokes outcome maintenance for non-opening sessions only. Its full
launcher bytes are nevertheless included because those bytes choose the opening
branch and retry behavior.

## Included Runtime Surface

| Boundary | Class | Reason |
| --- | --- | --- |
| `momentum_hunter/**/*.py` | Python runtime | Conservative package boundary; every added, removed, renamed, or changed `.py` file is automatic. |
| `tools/capture_job.py` | Opening orchestrator | Direct opening Python entry point. |
| `tools/run_capture_job.ps1` | Opening launcher | Command, retry, deadline, and terminal-result semantics. |
| `requirements.txt` | Dependency contract | Declared dependency identity. |
| Configured Python executable | Environment | Interpreter bytes and version. |
| Configured Windows PowerShell executable | Environment | Launcher bytes and version. |
| Installed Automation Service executable | Environment | Outer watchdog/process-launch behavior. |
| Complete installed Python distribution set | Environment | Detects direct and transitive dependency drift without hashing secrets. |
| Windows/platform/timezone identity | Environment | Detects material execution-environment drift. |
| Nonsecret project and manifest runtime fields | Configuration | Provider mode, timezone/windows, paths, poll interval, and host/release roots. |
| Loaded supervisor, identity-gate, and service-host hashes | Process identity | Prevents a new disk release from authorizing stale long-running process code. |

The package boundary is intentionally broader than the current import closure.
This trades some promotion frequency for strong automatic coverage of future
runtime modules. It does not require per-job repinning.

## Exclusions

| Area | Why it is outside opening runtime identity |
| --- | --- |
| `docs/` and governance Markdown | Never imported or read by the service-to-opening execution path. |
| `tests/`, test fixtures, and synthetic proof outputs | Not importable by the production opening command and absent from runtime paths. |
| Review bundles and historical reports | Outputs/evidence; never executable inputs to opening capture. |
| `src/MomentumHunter.Wpf/` and presentation assets | Opening is headless and WPF is not launched or imported. |
| Other .NET UI/test projects | Not the installed Automation Service host. |
| RTD experiment worktree/evidence | Separate process, source, configuration, and evidence root. |
| OAuth tokens, passwords, API keys, account values | Mutable secrets/operational state; excluded from release artifacts and fingerprints. |
| Per-date job list | Scheduled-job identity, not runtime behavior; dates/times remain independently validated by the manifest. |

Unrecognized project configuration fields fail closed until their runtime
classification is explicit. The canonical worktree remains required to be
clean; non-runtime committed changes are permitted, while arbitrary dirty state
is not.

## Release And Promotion Contract

`OpeningRuntimeReleaseV1` is write once and contains source Git, runtime surface,
configuration, environment, qualification references, predecessor, authority,
and its SHA-256 fingerprint. `OpeningRuntimePromotionV1` receipts form an
ordered predecessor hash chain. `OpeningRuntimeChannelV1` is atomically replaced
and must match the final receipt and immutable release.

Promotion requires a clean synchronized canonical checkout, explicit
qualification references, the exact confirmation interlock, and loaded
supervisor/gate/service-host hashes matching candidate bytes. Merge, push,
Roadmap edit, or service restart never promotes implicitly.

## Execution Semantics

Future opening jobs carry `approvedRuntimeChannel: opening-capture` instead of
`expectedGitHead`. Immediately before any runner/provider boundary, the
supervisor verifies schedule admission, release/pointer/receipt integrity,
actual runtime/config/environment fingerprints, loaded process hashes, and a
clean worktree. A mismatch produces a terminal failed receipt and no executor
call.

Receipts retain release-source Git and current Git. A docs-only commit may make
those values differ while the runtime remains eligible. Legacy jobs retain
their exact-Git field and existing behavior.

## Rollback

Restore the preserved pre-migration manifest atomically, restart only the
Automation Service if required, and run the already-proven controlled future
repin tool against the resulting clean canonical head. Verify Monday remains
08:35/08:40 Pending, service heartbeat advances, Shadow enabled is zero, and
order transmission is unavailable. No reset, rebase, force-push, historical
receipt rewrite, or market replay is used.
