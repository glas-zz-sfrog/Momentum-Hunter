# AUTOMATION-RUNTIME-IDENTITY-003 Dependency Closure

## Qualification Status

`IMPLEMENTED_PENDING_CONTROLLED_INTEGRATION`

Task branch: `codex/ARGUS-AUTOMATION-RUNTIME-IDENTITY-003`

Qualified implementation source: `4661568aaac1f2ac1ee3efb8a45db247ad120f84`

Starting canonical identity: `db91583f2d4e2318ee839d3cd6e86ebd237560e4`

The V2 source and environment boundary is implemented, the original
IDENTITY-002 comparison is reproduced, and an isolated physical promotion plus
runtime match passed. Production remains on V1 pending controlled integration.

## Direct Classifications

- `DEPENDENCY_CLOSURE_AUTHORITATIVE = YES` in the qualified V2 implementation.
- `ENVIRONMENT_BOUNDARY_NARROWED = YES`.
- `FAIL_CLOSED_EQUIVALENCE_PRESERVED = YES`.
- `UNNECESSARY_PROMOTION_REDUCTION_PROVEN = YES`.
- `PHYSICAL_PROMOTION_RUNTIME_MATCH_PROVEN = YES` in an isolated release root.
- `V1_ROLLBACK_PRESERVED = YES`.
- `CONTINUOUS_TRADEPLAN_PRODUCER_READY_NEXT = NO` until controlled integration
  and production readback are terminal.

## Root Findings

V1 is safe but binds 209 package Python modules plus three explicit files and
all 15 installed distributions. V2 recomputes from the supervisor, promotion
wrapper, and capture entry points. The qualified result is:

- 209 package Python modules present;
- 96 reachable package modules;
- 113 positively excluded package modules;
- 99 runtime components after three explicit files are included;
- zero local import escapes;
- zero unclassified dynamic-loading sites;
- 12 recorded subprocess sites;
- three imported third-party roots: `bs4`, `requests`, and `websocket`;
- two explicit non-imported distributions: `lxml` and `tzdata`.

The 10 relevant distributions are `beautifulsoup4`, `certifi`,
`charset-normalizer`, `idna`, `lxml`, `requests`, `soupsieve`, `tzdata`,
`urllib3`, and `websocket-client`. Each binds its actual installed files, not
only its version string. `PySide6`, its companion distributions, `shiboken6`,
`pip`, and any newly installed unrelated distribution are excluded.

## Mutation Proof

The V2 suite proves:

- included package source changes identity;
- the explicit PowerShell launcher changes identity;
- relevant distribution file identity changes environment and runtime identity;
- classified configuration changes identity;
- research-only `event_shock_specialist.py` does not change identity;
- WPF and Roadmap changes do not change identity;
- an unused installed distribution does not change environment identity;
- a new reachable package import expands the closure;
- a local outside-root import refuses identity construction;
- an unclassified `importlib.import_module` refuses identity construction;
- loaded supervisor mismatch refuses execution;
- included-file tampering after promotion refuses execution;
- V1 release execution still passes under V1 rules;
- a mixed V1 -> V2 -> V1 promotion chain verifies and restores V1.

## Recent-Commit Replay

The exact 20-commit IDENTITY-002 sample ending at
`d5d37cad84970bf8779eb1839568ad1eba5fdaa8` reproduces:

- V1 promotions: 4;
- V2 dependency-closure promotions: 2;
- Git-only commits under V1: 16.

Both changed decisions are explained:

1. `f2c2b65d3741d7658947aec7493b08ad5096336d`, terminal-dependency
   preservation for opening repin, changed an opening administration module,
   tests, tool, and docs. Its package module is unreachable from the approved
   opening/promotion roots, so V2 does not promote.
2. `e1ea386f4640686569e2fb5a9a88e261ac974da3`, Continuous canary recovery,
   changed Continuous-only package modules, tests, and governance. Those
   modules are unreachable from opening/promotion roots, so V2 does not
   promote.

The two retained promotions are `ec199549...`, which changed the supervisor
and runtime-identity gate, and `e69426b3...`, which changed Schwab modules
shared by the opening path. Both correctly remain promotion-requiring.

## Physical Proof

Isolated release root:

`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-AUTOMATION-RUNTIME-IDENTITY-003-PHYSICAL-4661568`

Result: `PHYSICAL_PROMOTION_RUNTIME_MATCH_PROVEN`

- isolated release: `OPENING-RUNTIME-54F89E6AC65407AA8EB9`;
- release fingerprint:
  `164e10f78015add004e15923962a651d10285bee2f0965678580d98dedfa2820`;
- dependency-closure fingerprint:
  `ebd7aa74b81da57bb7eca51409a73bbb9c0e0dcd71a60bd60d2db732c67fadcc`;
- runtime-surface fingerprint:
  `5a7e617f7031d28ce79ba24d40983a49c14c788c8ddd59cc2a517ea194981a62`;
- environment fingerprint:
  `7048a15811991a343bf898272d3cb702f9692e6e9c98a7741a3a8ca111760b94`;
- runtime match: true;
- production release root mutated: false.

The proof used actual configured Python, PowerShell, service-host bytes,
configuration, and installed dependencies. It wrote only the isolated release
root. No provider, account, Paper, Shadow, position, or order request occurred.

## Hard Chew

- V2 mutation and release tests: 7/7 pass.
- Focused opening/automation/capture/scheduling regression: 159/159 pass; one
  expected non-elevated reparse skip.
- First full discovery: 2 environment-only failures because the isolated
  worktree lacked `./.venv`; no product failure.
- Exact two affected modules after ignored `.venv` junction: 39/39 pass.
- Corrected full Python discovery: 2,737/2,737 pass in 942.807 seconds; one
  expected non-elevated reparse skip.
- Compileall: pass.
- PowerShell opening runner parse: pass.
- Diff check and secret scan: pass.
- Authority scan: opening only; Paper, Shadow, broker orders, and transmission
  remain false/unavailable.

## Production Nonmutation At Qualification

Canonical and `origin/master` remain clean at
`db91583f2d4e2318ee839d3cd6e86ebd237560e4`. The active production release is
still V1 `OPENING-RUNTIME-2698312C5F3749F4916C` and reports
`APPROVED_RUNTIME_MATCH` with a fresh heartbeat. Automation, Continuous Runtime,
and Continuous Writer remain Running/Automatic. The Automation manifest,
Continuous config, Automation service host, and Continuous service-host hashes
remain unchanged. Thirteen future opening jobs use `opening-capture`; zero
Shadow and zero Paper jobs are enabled; order transmission is unavailable.

## Controlled Integration Requirement

Merging this runtime code changes the broad V1 disk surface. Therefore a
controlled integration must update the loaded Automation Supervisor/identity
gate and promote the exact integrated V2 runtime before the next opening. The
current V1 release record must remain immutable and available for rollback. No
job repin is required.
