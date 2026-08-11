# ARGUS-SHADOW-025L Goal Charter

## Goal

Reconcile the proven ARGUS-SHADOW-025B through 025K serialized runtime,
evidence-chain, recovery, root-security, and writer-boundary contracts onto the
current Paper-engineering and scheduler-hardened canonical head without
activating any runtime path or choosing an installed writer architecture.

## Operator Value

Momentum Hunter needs one inspectable chain from a prospective event source to
write-once evidence before continuous intraday production can be activated.
This task preserves that chain on the current codebase while keeping Steven's
actual consequential decision narrow: which future process/principal may own
the raw evidence root and how provider credentials remain isolated.

## Scope

- Restore the exact SHADOW-025B through 025K source, tests, Goal Charters, and
  release reports from source branch head `203003b` onto current base
  `b4762c6`.
- Preserve cross-process ledger ownership, source admission, topology, source-
  admission ledger, writer session, evidence-chain, recovery, orchestration,
  root-security, and writer-boundary contracts.
- Prove current-head compilation, focused runtime-chain behavior, adjacent
  Paper/automation/Engine Host/Shadow/candle regressions, and full Python
  discovery.
- Prove no existing runtime module imports the restored stack and no restored
  module can contact a provider, account, broker/order path, service,
  scheduler, Engine Host process, WPF, or production store.
- Record the current same-SID Windows boundary and preserve both prospective
  writer shapes for a later explicit architecture decision.

## Non-Goals

- No runtime source or writer activation.
- No installed process, Windows principal, ACL, service, scheduler, Engine
  Host, WPF, provider, account, credential, broker, order, Paper, Shadow,
  database, production-store, or generated-evidence change.
- No provider credential move, reprovisioning, brokering, or scope change.
- No selection between a distinct-principal Engine Host and a dedicated
  evidence-writer process.

## Acceptance Evidence

- All 39 restored artifacts match source branch head `203003b` exactly.
- Compileall passes.
- The focused B-K runtime chain passes 196 tests.
- The full continuous-contract stack passes 412 tests.
- Adjacent current-runtime regressions pass 387 tests.
- Full Python discovery passes 1,873 tests.
- Existing-runtime import and forbidden-capability scans return zero hits.
- Credential-shape, protected-path, source-identity, whitespace, and final-diff
  reviews pass before commit.
- Canonical checkout remains clean and synchronized until clean fast-forward
  integration and exact-head schedule repinning.

## Consequence Gate

The present Automation Service, Engine Host, and WPF run under Steven's Windows
SID, so filesystem ACLs cannot distinguish the intended writer from the UI.
Installation therefore requires a later explicit choice between:

1. A distinct-principal Engine Host that is also sole writer, with separately
   approved provider-credential reprovisioning or brokering.
2. A dedicated evidence-writer process behind a strongly authenticated,
   nonpersistent capability channel; same-user SID-only pipe authentication is
   insufficient.

Neither option is selected by this task. Every boundary result retains
`activation_authorized=false`.

## Classification

`IMPLEMENTED_PENDING_MERGE`
