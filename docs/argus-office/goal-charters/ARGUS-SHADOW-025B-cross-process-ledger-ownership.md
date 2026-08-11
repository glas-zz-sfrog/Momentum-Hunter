# ARGUS-SHADOW-025B Goal Charter

## Goal

Make the dormant SHADOW-025 event-cycle ledger safe for eventual service and
Engine Host writers in separate operating-system processes without wiring it
into runtime.

## Operator Value

One material prospective decision must remain one immutable record even when
two legitimate Momentum Hunter hosts attempt to append at the same time or one
host exits while owning persistence.

## Scope

- Add finite cross-process ownership around the complete ledger transaction.
- Preserve atomic replacement, append-only validation, and thread reentrancy.
- Prove Windows simultaneous writers, contention timeout, and process-exit
  recovery with synthetic temporary-directory tests.
- Keep the module dormant and every persistence path caller-supplied.

## Non-Goals

- No service, Engine Host, scheduler, provider, account, broker, Paper, Shadow,
  score, readiness, selector, Risk Governor, allocation, WPF, schema, package,
  credential, or production-store integration.
- No decision about the eventual installed ledger path or process owner.
- No canonical merge or installation before Tuesday operational evidence.

## Acceptance Evidence

- Python compileall passes.
- Focused process-contention and recovery tests pass under Windows spawn.
- Direct contract, adjacent protected-boundary, and full Python discovery pass.
- Static capability, credential, generated-artifact, protected-path, and diff
  reviews pass.
- Canonical checkout remains clean and synchronized at its frozen head.

## Classification

`IMPLEMENTED_PENDING_MERGE`
