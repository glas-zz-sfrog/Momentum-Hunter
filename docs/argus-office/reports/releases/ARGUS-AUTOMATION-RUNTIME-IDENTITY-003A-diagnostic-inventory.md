# AUTOMATION-RUNTIME-IDENTITY-003A Diagnostic Inventory

## Current Status

`COMPLETE / APPROVED_RUNTIME_ACTIVE`

Starting canonical: `6d5b15d0fff8f5fe48d56a5c82e2fc4b86cc94d0`

Qualified implementation and current canonical:
`cb8a6ff2efd686528c89539106df4fbe822cbd06`

## Correction

Identity-003 retained `packagePythonCount` and `excludedPackageCount` inside
the V2 dependency-closure and runtime-surface fingerprint material. Those
counts are useful diagnostics, but an opening-unreachable package addition or
removal could therefore change approved opening identity.

Identity-003A keeps both counts in release evidence and keeps their arithmetic
reconciliation fail-closed. It version-binds an exact two-field diagnostic
exclusion contract:

- `excludedPackageCount`;
- `packagePythonCount`.

The exclusion declaration itself remains authoritative. Reachable package
count, exact closure files, component bytes, entry and explicit files, import
roots, distribution contracts, subprocess sites, configuration, environment,
loaded bytes, and tamper checks remain identity inputs.

Records without the 003A identity-input version continue to verify with the
legacy V2 fingerprint algorithm. V1 remains executable as the broad rollback
policy.

## Mutation Evidence

- Add one unreachable package module: total and excluded counts each increase
  by one; legacy closure and surface hashes change; 003A closure, surface, and
  approved runtime fingerprints remain identical.
- Remove that unreachable package module: approved identity returns the same
  unchanged value.
- Add a module and make it reachable from the opening graph: approved identity
  changes.
- Change the newly reachable module bytes: approved identity changes again.
- Relevant module, explicit file, dependency, configuration, outside-root
  import, dynamic loading, loaded-byte drift, and post-promotion tamper tests
  retain their prior fail-closed behavior.

The exact disposable unreachable-add comparison records:

- baseline inventory `210 total / 96 reachable / 114 excluded`;
- added inventory `211 total / 96 reachable / 115 excluded`;
- legacy closure fingerprint changes from `321f5a5a...` to `e3296070...`;
- legacy surface fingerprint changes from `e7f726cc...` to `130303eb...`;
- corrected closure remains `96885a4e...`;
- corrected surface remains `f0137a05...`;
- approved runtime remains `f26f8c7b...` through add and remove.

The independent reachable-module mutation changes approved runtime from
`08912c8f...` to `bdd7a442...`; changing that reachable module again advances
it to `eb423235...`.

## Hard Chew

- Focused V2 identity suite: 10/10 pass.
- Identity/release/supervisor adjacency: 86/86 pass; one expected non-elevated
  Windows reparse skip.
- Full Python discovery: 2,755/2,755 pass in 2,478.555 seconds; one expected
  non-elevated Windows reparse skip.
- Compileall: pass.
- PowerShell opening launcher parse: pass.
- Diff, protected-path, and credential-shaped-value scans: pass.

## Isolated Physical Proof

Evidence root:
`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-AUTOMATION-RUNTIME-IDENTITY-003A-PHYSICAL-CB8A6FF`

- Status: `PHYSICAL_PROMOTION_RUNTIME_MATCH_PROVEN`.
- Release: `OPENING-RUNTIME-477BA48A176B291D28AE`.
- Closure fingerprint:
  `96885a4e27c2f44e5763043be64c5536ca73709e951c052d4817248b0daef892`.
- Surface fingerprint:
  `5d326bac26e068f570a7fe362546e862cce354a2c730c076aa2210adc6b9a8fe`.
- Configuration fingerprint:
  `c485b9dcb3364354fe7cadb9a4f76fc249baf6d4d6b8ee3ffeaea2b6706d113d`.
- Environment fingerprint:
  `5a1659095f498772bef47b662924f996b7812df5c494a1fd96dacdb1f172a66a`.
- 210 package modules, 96 reachable, 114 excluded diagnostics, 99 runtime
  components, and 10 relevant distributions.
- Production release root, service, manifest, scheduler, provider, account,
  and order state were not mutated.

## Installed Gate

The rollback-protected updater completed from clean synchronized `317c456` with
zero running jobs. Exact loaded-byte readback matches:

- Automation Service host:
  `D71660B49BC4EFD51F36AC0A7C53333BE844057FCC6EF4C3982CF1005F0F7558`;
- supervisor:
  `f9097fc9523e0873a756340397bda4e544b3573c7599693eda9927b1baf3cefd`;
- runtime identity gate:
  `9bbe2285ac6130b6df605ac4c85170d2986706e409193ab593f7339edf5afdb2`.

The manifest's JSON meaning is byte-for-byte-equivalent after canonical JSON
normalization to the updater backup. Its serialization hash changed from
`F293CE95F143BB8853E83F88D83F6ACED62A891CA88AFDE8780B95AB023EB862`
to `AFC55EC289E46E02DF96C2FC0B4DD501DEEC763FC94B82DBB2065B25F942700`.

Production V2 promotion created:

- release `OPENING-RUNTIME-D220AEA03F465DEA3B6A`;
- runtime fingerprint
  `d220aea03f465dea3b6ab970a417e08ec40b4649982d9a356336aafb93c67429`;
- release fingerprint
  `3947881e4c0c70108b536aad0cb27738b4d89d14a3993ded16c95ddf05ce944e`;
- closure fingerprint
  `96885a4e27c2f44e5763043be64c5536ca73709e951c052d4817248b0daef892`;
- environment fingerprint
  `597cf9d341952cf148da685f60d558efd038599af030465fa18ff5ca176db2b8`.

Installed status is `APPROVED_RUNTIME_MATCH`; an immediate plan is idempotent
with zero changed components. Automation, Continuous Runtime, and Continuous
Writer are Running/Automatic. Thirteen future openings remain; zero Shadow and
zero Paper jobs are enabled; order transmission is unavailable.

## Final Classifications

- `DEPENDENCY_CLOSURE_AUTHORITATIVE = YES`.
- `ENVIRONMENT_BOUNDARY_NARROWED = YES`.
- `FAIL_CLOSED_EQUIVALENCE_PRESERVED = YES`.
- `UNNECESSARY_PROMOTION_REDUCTION_PROVEN = YES`.
- `PHYSICAL_PROMOTION_RUNTIME_MATCH_PROVEN = YES`.
- `V1_ROLLBACK_PRESERVED = YES`.
- `CONTINUOUS_TRADEPLAN_PRODUCER_001A_READY_NEXT = YES`.

## Next Gate

Begin `ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001A` from the then-current clean
synchronized canonical baseline. Do not infer any Paper, Shadow, broker,
account, position, or order authority from this identity closeout.
