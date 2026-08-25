# Opening Runtime Identity ADR V2

## Decision

Use a promotion-time static dependency closure for the approved opening
runtime. Keep `OpeningRuntimeReleaseV1` executable and promotable as the broad
rollback path. New operator promotions default to `OpeningRuntimeReleaseV2`.

V2 recomputes its boundary from these authoritative roots:

- `momentum_hunter.automation_supervisor`;
- `momentum_hunter.opening_runtime_release`;
- `tools/capture_job.py`.

It also binds the non-imported runtime files `tools/run_capture_job.ps1` and
`requirements.txt`. The Python capture entry point appears in both the entry
and explicit-file sets and is fingerprinted once.

## Source Closure

Promotion parses the actual Python sources with `ast`, follows every local
`momentum_hunter` import to a fixed point, and records the complete component
list and analysis evidence. Promotion fails closed when:

- an imported local module resolves outside the approved package or exact
  entry-file boundary;
- a reachable source uses an unclassified dynamic import/loading operation;
- an entry module, entry file, or explicit file is missing;
- closure counts, paths, hashes, or nested fingerprints contradict each other;
- a component is unreadable, a reparse point, or outside the repository root.

Subprocess sites are recorded in closure evidence. Their reachable source
bytes remain bound. The configured Python, PowerShell, and installed service
host executables are independently fingerprinted.

## Environment Closure

Imported non-stdlib roots are resolved through the configured Python
interpreter's package-to-distribution metadata. Each root must resolve to
exactly one installed distribution. Required transitive distributions are
followed conservatively; optional extras are not admitted without an explicit
contract.

Two current dependencies are explicit because static Python imports do not
express their runtime use:

- `lxml`, selected by literal parser name in `providers.py`;
- `tzdata`, required for IANA `zoneinfo` data on Windows.

Every selected distribution binds name, version, actual installed-file count,
and an SHA-256 fingerprint over its non-bytecode installed files. Unselected
installed distributions are not identity inputs. Missing, ambiguous, or
unfingerprintable dependency provenance fails promotion.

## Release Contract

`OpeningRuntimeReleaseV2` contains the complete surface identity, closure
evidence, canonicalized nonsecret configuration, narrowed environment
identity, authority denial fields, qualification references, and source Git
identity. The release store verifies every nested fingerprint and count before
acceptance. A malformed newly written release is removed rather than leaving a
poisoned immutable path.

Promotion receipts and the channel pointer retain their V1 schemas so one
ordered chain can contain V1 and V2 releases. Each receipt must name the policy
of its referenced immutable release. A prior V1 release can be promoted again
after V2, preserving the broad rollback implementation.

At execution, the active release schema selects its matching identity builder.
V1 releases recompute the broad V1 surface. V2 releases recompute V2 closure
and environment evidence. Both preserve clean-worktree, loaded supervisor,
loaded identity-gate, loaded service-host, configuration, environment, and
approved-runtime fingerprint checks before the opening runner is called.

## Promotion Decision

A repository commit does not itself require promotion. Promotion is required
when the recomputed approved runtime fingerprint changes. This includes an
included source/explicit file, configuration, executable, relevant installed
distribution, or platform identity change. Documentation, WPF-only source,
unreachable research Python, and unrelated installed distributions do not
change V2 identity.

The promotion wrapper defaults to `--policy v2`. `--policy v1` remains an
explicit rollback/reference option. No implicit promotion, service restart,
job repin, or authority expansion is introduced.

## Authority

Both release versions carry opening-capture authority only. Paper, Shadow,
broker orders, account access, and order transmission remain unavailable.
