# ARGUS-SHADOW-025K Runtime Writer Boundary Contract

## Branch

`codex/ARGUS-SHADOW-025K-writer-boundary-contract`, stacked on verified
ARGUS-SHADOW-025J head `1015bbd`.

## Scope

This slice adds a dormant architecture contract between 025J's root-security
policy and any future installed runtime. It models the service, Engine Host,
WPF, and evidence writer; validates one exact process/principal topology; and
classifies the proposal as blocked or feasible pending physical proof.

Two prospective shapes are representable:

1. A distinct-principal Engine Host is also the sole root writer. This requires
   separately approved provider-credential reprovisioning or a proven broker;
   current-user DPAPI cannot silently follow it.
2. A distinct evidence-writer process receives records over an authenticated,
   nonpersistent capability while Engine Host retains current-user DPAPI access.
   Same-user SID-only named-pipe authentication is insufficient.

Neither shape is selected or installed. Every result keeps
`activation_authorized=false` and lists the required elevated access, process
identity, credential/redaction, channel/replay, handle-isolation, restart,
crash-recovery, and WPF-nonmutation proofs.

## Files Changed

- `momentum_hunter/event_runtime_writer_boundary.py`
- `tests/test_event_runtime_writer_boundary.py`
- Branch-local Goal Charter, Roadmap, branch/task/changelog/risk records, and
  this release report.

## Evidence

- Compileall: pass.
- Focused writer-boundary tests: 22 pass.
- Adjacent SHADOW runtime chain: 196 pass.
- Full Python discovery: 1,871 pass in 234.13 seconds.
- Static tests prove no OS, filesystem, ACL, network, provider, account,
  credential-store, broker, order, service, scheduler, process-start, or
  activation capability exists.
- Canonical checkout remained clean and synchronized at frozen `78db1bf`.

## Failure Modes Proved

- Current service/Engine Host/WPF same-SID architecture is blocked.
- Writer aliases with service, WPF, or a separate Engine Host are blocked.
- WPF or supervisor direct-root access and multiple root writers are blocked.
- Same-user SID-only named-pipe authority cannot distinguish WPF from Engine Host.
- Shared, persisted, or interactive-visible channel capabilities are blocked.
- A distinct Engine Host cannot reuse current-user DPAPI credentials.
- Separate DPAPI requires an explicit later reprovisioning decision.
- Ephemeral credential brokering requires distinct authentication and cannot
  expose material to WPF or persist it for the writer.
- Root-security policy drift, malformed role facts, and fingerprint tampering
  fail closed.

## Protected Areas

No score, readiness, alert, provider, account, credential, broker, order,
Paper, Shadow, selector, service, scheduler, Engine Host runtime, WPF, database,
production store, Windows identity, ACL, raw data, generated evidence, or
installed runtime changed.

## Risks

`CONTRACT_FEASIBLE_PENDING_PROOF` is not an architecture selection. A dedicated
writer still needs same-user process-handle isolation proof; a distinct Engine
Host needs a consequential credential-access design. Both require elevated ACL,
restart, crash, channel, and WPF nonmutation proof before installation.

## Manual QA

None. This is nonvisual dormant security infrastructure.

## Recommendation

Preserve Tuesday's opening and Paper terminal evidence, reconcile 025A through
025K, then choose one writer architecture before any installed root or runtime
import. Do not move or reprovision credentials as part of integration.

## Classification

`IMPLEMENTED_PENDING_MERGE`
