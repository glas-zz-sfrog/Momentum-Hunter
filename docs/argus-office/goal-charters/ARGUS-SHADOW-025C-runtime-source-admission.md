# ARGUS-SHADOW-025C Goal Charter

## Goal

Define the dormant admission boundary that selects exactly one immutable,
canonical source for each prospective continuous decision cycle.

## Operator Value

Momentum Hunter must not create duplicate decisions because a candidate event,
regime change, catalyst update, volume update, and plan refresh describe the
same market change in different records. One new plan version must yield at
most one admitted trigger whose authority can be audited later.

## Scope

- Admit setup-bound candidate lifecycle events only from their validated ledger.
- Consolidate all other material context changes through one validated successor
  continuous-plan version.
- Bind the resulting trigger to the exact plan, predecessor, policy, source
  record, timestamps, and fingerprints.
- Reject discovery-only, unpersisted, stale, contradictory, replayed, or
  nonmaterial source claims.
- Keep the adapter dormant, deterministic, offline, and nonpersisting.

## Non-Goals

- No provider, account, broker, order, Paper, Shadow, selector, service,
  scheduler, Engine Host, WPF, score, readiness, production-store, or installed
  runtime wiring.
- No selection of the installed ledger path or owning process.
- No canonical merge or installation before Tuesday operational evidence.

## Acceptance Evidence

- Python compileall passes.
- Focused source-admission and event-cycle tests pass.
- Combined continuous and adjacent protected-boundary regressions pass.
- Full Python discovery passes within a bounded timeout.
- Static capability, credential, protected-path, generated-artifact, and diff
  reviews pass.
- Canonical checkout remains clean and synchronized at its frozen head.

## Classification

`IMPLEMENTED_PENDING_MERGE`
