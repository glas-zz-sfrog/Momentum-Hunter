# AUTOMATION-RUNTIME-IDENTITY-003A Diagnostic Inventory

## Current Status

`INTEGRATED / INSTALLED_PROMOTION_PENDING_UAC`

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

The non-mutating updater plan passed on clean synchronized `cb8a6ff` with zero
running jobs, unchanged manifest
`F293CE95F143BB8853E83F88D83F6ACED62A891CA88AFDE8780B95AB023EB862`,
and one changed opening component: `opening_runtime_identity.py`.

Two visible UAC launches were canceled before elevation. No updater mutation
occurred. The Automation Service remains Running/Automatic on its prior loaded
gate, and the active release remains
`OPENING-RUNTIME-EC11418BBC35F5285CA8`. Because canonical now contains the new
reachable gate bytes, opening execution correctly remains fail-closed until
the rollback-protected service refresh, V2 promotion, and installed status
verification complete.

## Next Gate

Complete the single elevated Automation Service refresh, promote the exact V2
candidate, verify `APPROVED_RUNTIME_MATCH`, and record final installed hashes.
Producer-001A is technically ready behind this gate but must not begin before
the installed closeout is terminal.
