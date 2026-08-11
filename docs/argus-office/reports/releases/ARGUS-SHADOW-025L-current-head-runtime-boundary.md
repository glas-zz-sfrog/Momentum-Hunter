# ARGUS-SHADOW-025L Current-Head Runtime Boundary Reconciliation

## Branch

`codex/ARGUS-SHADOW-025L-current-head-runtime-boundary` from synchronized
canonical base `b4762c6`.

## Scope

This release reconciles the exact SHADOW-025B through 025K dormant contract
chain from source head `203003b` onto the current Paper-engineering and
scheduler-hardened codebase. It adds no runtime import or activation.

The reconciled chain provides:

- cross-process transaction ownership for event-cycle persistence;
- deterministic admission of candidate, plan, and safety trigger sources;
- one explicit runtime topology and artifact-access contract;
- write-once source-admission ledger evidence;
- a composed writer session and complete evidence-chain prefix;
- read-only crash/restart recovery classification;
- dormant orchestration with exact identity and replay behavior;
- root-path, principal, ACL, and reparse-point security contracts; and
- fail-closed evaluation of prospective installed writer architectures.

## Files Changed

- Ten runtime modules, including the current-head update to
  `event_driven_decision_cycle.py`.
- Nine test modules, including the matching decision-cycle update.
- The ten historical SHADOW-025B through 025K Goal Charters and release
  reports, restored byte-for-byte.
- This current-head Goal Charter/release report and shared governance records.

## Evidence

- Restored-source identity: 39/39 artifacts match source head `203003b`.
- Compileall: pass.
- Focused SHADOW-025B through 025K runtime chain: 196/196 pass.
- Full continuous-intraday contract stack: 412/412 pass.
- Adjacent TradePlan/RVOL, allocation, Paper lifecycle, automation,
  Engine Host, Shadow, and candle regressions: 387/387 pass.
- Full Python discovery: 1,873/1,873 pass in 234.156 seconds.
- Existing-runtime references to the reconciled modules: zero.
- Provider/network/broker/order/service/scheduler/process-start/fixed-
  production-path capabilities in the restored modules: zero.
- Test residue before full discovery: zero.
- No provider, account, position, preview, order, service command, Engine Host
  command, production-store, or generated-evidence action occurred.

## Architecture Result

The contracts prove that the current same-SID Windows layout cannot enforce a
raw-root boundary between WPF and the intended writer. They represent two
future shapes without selecting either:

1. A distinct-principal Engine Host owns the raw root. Current-user DPAPI
   credentials cannot silently move to that principal.
2. A dedicated evidence writer accepts authenticated, nonpersistent records
   while Engine Host retains provider access. Same-user SID-only pipe identity
   is not strong enough.

Every proposal remains `activation_authorized=false`. A later task must make
the consequential process/principal and credential-access decision, then prove
ACLs, reparse defenses, channel authentication/replay, handle isolation,
restart/crash recovery, and WPF nonmutation before installation.

## Protected Areas

No score, readiness, alert, candidate-production, TradePlan, allocation, Risk
Governor, provider, account, credential, broker, order, Paper, Shadow,
selector, service, scheduler, Engine Host runtime, WPF, database, production
store, Windows identity, ACL, raw data, or generated evidence behavior changed.
Only dormant contracts/tests and governance evidence were reconciled.

## Manual QA

None. This is nonvisual dormant infrastructure.

## Recommendation

Integrate and back up the dormant contracts after final diff and secret proof,
then repin the existing opening-dependent Paper schedule to the final canonical
head. Do not activate the source/writer chain or move credentials. Present the
writer-principal choice as the next explicit architecture gate while continuing
other bounded roadmap work that does not depend on installation.

## Classification

`IMPLEMENTED_PENDING_MERGE`
