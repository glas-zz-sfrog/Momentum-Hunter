# ARGUS-SHADOW-025D Runtime Topology Contract

## Branch

`codex/ARGUS-SHADOW-025D-runtime-topology-contract`, stacked on verified
ARGUS-SHADOW-025C head `0d3fc9b`.

## Scope

The dormant continuous-decision stack now has a deterministic ownership and
relative-path contract. The Python Engine Host is the sole online reader and
writer. The Windows Automation Service remains supervisor-only, WPF must use
versioned Engine Host snapshots, and offline review is file-read-only.

Each evidence program and configuration receives four separate append-only
artifacts beneath an explicit caller-provided absolute root:

- `evidence/candidate-lifecycle.json`
- `evidence/continuous-plans.json`
- `evidence/runtime-source-admissions.json`
- `evidence/event-decision-cycles.json`

No installed root is selected and no path is created by this task.

## Files Changed

- `momentum_hunter/event_runtime_topology.py`
- `tests/test_event_runtime_topology.py`
- Branch-local Argus governance and this release report.

## Evidence

- Compileall: pass.
- Focused topology tests: 23 pass.
- Host/service/source contract tests: 222 pass.
- Combined continuous evidence contracts: 308 pass.
- Allocation/Paper/Shadow/candle boundaries: 259 pass.
- Full Python discovery: 1,757 pass in 237.8 seconds.
- `git diff --check`: pass.
- Static network/broker/order/persistence capability scan: pass.
- Runtime-import scan: only focused tests import the contract.
- Credential-shaped value scan: no credential found.

## Failure Modes Proved

- Relative, traversing, source, test, Git, or virtual-environment roots fail.
- Artifacts cannot collide, escape their namespace, change ownership, or lose
  append-only status.
- Engineering and official evidence programs cannot share paths.
- Configuration changes get separate evidence namespaces.
- Runtime-build changes preserve the program namespace but rotate topology and
  writer authority.
- A stale/replaced Engine Host claim cannot append under a different host or PID.
- Automation Service, WPF, offline review, and unknown roles cannot append.
- Automation Service and WPF cannot read canonical artifact files directly.
- Historical/replay mode and transmission availability cannot be enabled by a
  re-fingerprinted topology.
- Building, validating, and authorizing the contract creates no files.

## Protected Areas

No installed service, scheduler, Engine Host, WPF, provider, account, broker,
order, Paper, Shadow, selector, score, readiness, production store, schema, or
configuration changed. The contract is dormant and has no persistence or
external capability.

## Risks

The actual installed root, process startup claim/lease composition, source-
admission store implementation, and orchestration loop remain future work.
Reparse-point and filesystem ACL checks must be proved when a real root is
selected; this pure contract intentionally performs no installation inspection.

## Manual QA

None. This is nonvisual synthetic contract infrastructure.

## Recommendation

Preserve Tuesday's terminal opening and Paper evidence. Then reconcile this
latest successor against canonical master and integrate the continuous stack in
dependency order before selecting an installed root or wiring Engine Host
orchestration.

## Classification

`IMPLEMENTED_PENDING_MERGE`
