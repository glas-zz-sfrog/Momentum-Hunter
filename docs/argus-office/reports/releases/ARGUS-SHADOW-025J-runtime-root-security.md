# ARGUS-SHADOW-025J Runtime Root Security Contract

## Branch

`codex/ARGUS-SHADOW-025J-runtime-root-security`, stacked on verified
ARGUS-SHADOW-025I head `dce582c`.

## Scope

The dormant continuous-decision stack now has a versioned eligibility contract
for a future installed evidence root. It consumes supplied Windows path and
effective-access evidence and reports whether that evidence meets the contract;
it contains no filesystem inspector, installer, ACL mutation, or activation
method.

The contract requires a complete absolute local component chain, no symlink or
reparse traversal, trusted ownership, a protected root DACL, complete
effective-access evidence, one distinct writer principal with append/atomic-
replace rights but no ACL/ownership control, no interactive or broad root
mutation, and no destructive ancestor access. Every policy, snapshot, and
result is fingerprinted, and every result keeps `activation_authorized=false`.

## Files Changed

- `momentum_hunter/event_runtime_root_security.py`
- `tests/test_event_runtime_root_security.py`
- Branch-local Goal Charter, Roadmap, branch/task/changelog/risk records, and
  this release report.

## Evidence

- Compileall: pass.
- Focused root-security tests: 19 pass.
- Root/topology/writer/chain/recovery/orchestration/cycle tests: 145 pass.
- Full Python discovery: 1,849 pass in 234.59 seconds.
- Static tests prove the module has no filesystem, ACL, network, provider,
  account, broker, order, service, scheduler, or host-start capability and no
  existing runtime imports it.
- Source inspection shows the service installer selects the current Windows
  identity and `PythonAutomationSupervisorWorker.BuildStartInfo()` supplies no
  alternate username, so the child Engine Host inherits the service identity.
  The interactive WPF process therefore shares that SID in the current design.
- Canonical checkout remained clean and synchronized at frozen `78db1bf`.

## Failure Modes Proved

- Writer and interactive identities cannot be the same.
- Writer, interactive, and broad principals cannot own the protected root.
- Missing or malformed path/effective-access evidence fails closed.
- Root or ancestor symlink/reparse state blocks eligibility.
- Untrusted ownership, missing root, file-shaped root, inherited root DACL,
  missing writer rights, writer ACL control, nonwriter mutation, and ancestor
  replacement rights each block eligibility.
- Relative, UNC, traversing, outside-base, base-equal, and incomplete component
  paths fail or block.
- Snapshot and result tampering fails validation.
- Even a contract-eligible synthetic snapshot cannot authorize activation.

## Protected Areas

No score, readiness, alert, provider, account, broker, order, Paper, Shadow,
selector, service, scheduler, Engine Host runtime, WPF, database migration,
production store, Windows principal, ACL, credential, raw data, generated
report, or installed runtime changed.

## Risks

The current same-user service/Engine Host/WPF design cannot satisfy filesystem
process-role isolation. A later architecture decision must either give the
evidence writer a distinct Windows principal or introduce another genuinely
enforceable security boundary. This contract evaluates supplied facts only;
an elevated read-only Windows ACL inspector, safe provisioning, TOCTOU defense,
and actual restart proof remain separate work.

## Manual QA

None. This is nonvisual dormant security infrastructure.

## Recommendation

Preserve Tuesday's terminal opening and Paper evidence. During stacked-branch
reconciliation, choose and prove a distinct writer security boundary before
any installed-root creation or Engine Host import.

## Classification

`IMPLEMENTED_PENDING_MERGE`
